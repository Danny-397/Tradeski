# tracker/main.py
# Main real-time stock tracker: ingestion, alerts, scheduler, WebSocket push.

import argparse
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from dashboard.app import get_socketio
from . import database
from .alerts import (
    AlertEngine,
    AlertRule,
    price_above,
    price_below,
    rsi_overbought,
    rsi_oversold,
    sma_cross_down,
    sma_cross_up,
)
from .analyzer import analyze_series
from .config import load_app_config, load_pushover_config
from .daily_summary import generate_daily_summary
from .logger import get_logger
from .notifier import Notifier
from .price_fetcher import get_stock_price
from .pruning import prune_old_data
from .scheduler import SchedulerManager
from .dashboard import run_dashboard

logger = get_logger(__name__)
socketio = get_socketio()

# Global flag used to stop the tracking loop
running = True


def stop_listener() -> None:
    """Background thread that waits for 'stop' to quit the app."""
    global running

    while running:
        command = input("\nType 'stop' to quit:\n").lower()
        if command == "stop":
            running = False
            logger.info("Stop command received. Shutting down...")
            break


def get_user_alert_price() -> float:
    """Prompt the user for a target price alert (limit-style)."""
    while True:
        try:
            value = float(
                input(
                    "Enter the price you want to be alerted at "
                    "(like a limit order): "
                )
            )
            return value
        except ValueError:
            print("Invalid number. Please enter a valid price.")


def load_user_alerts(alert_engine: AlertEngine) -> None:
    """Load user-defined alerts from the database into the alert engine."""
    rows = database.get_alerts()
    for row in rows:
        (
            alert_id,
            symbol,
            alert_type,
            threshold,
            multiplier,
            zscore,
            active,
            created_at,
        ) = row

        if not active:
            continue

        if alert_type == "price_above":
            rule = AlertRule(
                name=f"{symbol} Price Above {threshold}",
                condition=lambda d, t=threshold: d["price"] > t,
                message=f"Price crossed above {threshold}",
            )
        elif alert_type == "price_below":
            rule = AlertRule(
                name=f"{symbol} Price Below {threshold}",
                condition=lambda d, t=threshold: d["price"] < t,
                message=f"Price dropped below {threshold}",
            )
        elif alert_type == "rsi_over":
            rule = AlertRule(
                name=f"{symbol} RSI Over {threshold}",
                condition=lambda d, t=threshold: d["rsi"] > t,
                message=f"RSI crossed above {threshold}",
            )
        elif alert_type == "rsi_under":
            rule = AlertRule(
                name=f"{symbol} RSI Under {threshold}",
                condition=lambda d, t=threshold: d["rsi"] < t,
                message=f"RSI dropped below {threshold}",
            )
        else:
            # Unknown type; skip for now
            continue

        alert_engine.add_rule(rule)


def compute_volume_stats(
    symbol: str,
) -> Tuple[float, float]:
    """Compute current volume and average recent volume for a symbol."""
    recent_volumes: List[float] = database.get_recent_volumes(
        symbol, limit=50
    )
    avg_volume = (
        sum(recent_volumes) / len(recent_volumes)
        if recent_volumes
        else 0.0
    )
    current_volume = recent_volumes[0] if recent_volumes else 0.0
    return current_volume, avg_volume


def main() -> None:
    """Main function that runs the real-time stock tracker."""
    global running

    # Load configuration files
    app_config = load_app_config()
    pushover_config = load_pushover_config()

    # Notification handler
    notifier = Notifier(pushover_config)

    # Initialize SQLite database
    database.init_db()

    # Load stock symbol and interval from config
    symbol: str = app_config.stock_symbol
    check_interval: int = app_config.check_interval

    # Fetch initial price
    initial_price = get_stock_price(symbol)
    if initial_price is None:
        logger.error("Invalid stock symbol: %s", symbol)
        return

    # Ask user for a custom price alert
    alert_price = get_user_alert_price()
    alert_triggered = False

    logger.info(
        "Tracking %s | Starting price: %.2f | Alert at: %.2f",
        symbol,
        initial_price,
        alert_price,
    )

    # Store initial price in database
    database.insert_price(symbol, initial_price)

    start_time = datetime.now()

    # State variables
    last_price: float = initial_price
    unchanged_minutes: int = 0
    drop_alert_sent: bool = False

    # Alert engine setup
    alert_engine = AlertEngine(notifier)

    # Static example rules
    alert_engine.add_rule(
        AlertRule(
            name="Price Above Target",
            condition=price_above(200),
            message="Price is above target: {price}",
        )
    )
    alert_engine.add_rule(
        AlertRule(
            name="Price Below Target",
            condition=price_below(150),
            message="Price dropped below threshold: {price}",
        )
    )
    alert_engine.add_rule(
        AlertRule(
            name="RSI Overbought",
            condition=rsi_overbought(),
            message="RSI is overbought at {rsi}",
        )
    )
    alert_engine.add_rule(
        AlertRule(
            name="RSI Oversold",
            condition=rsi_oversold(),
            message="RSI is oversold at {rsi}",
        )
    )
    alert_engine.add_rule(
        AlertRule(
            name="SMA Bullish Crossover",
            condition=sma_cross_up(),
            message="SMA crossed above EMA (bullish)",
        )
    )
    alert_engine.add_rule(
        AlertRule(
            name="SMA Bearish Crossover",
            condition=sma_cross_down(),
            message="SMA crossed below EMA (bearish)",
        )
    )

    # Load user-defined alerts from DB
    load_user_alerts(alert_engine)

    # Scheduler setup
    scheduler = SchedulerManager()

    # Daily pruning at 4:00 AM
    scheduler.add_daily_job(
        func=lambda: prune_old_data("tracker.db", days=30),
        hour=4,
        minute=0,
        name="daily_prune",
    )

    # Optional: run analytics refresh every 10 minutes
    scheduler.add_interval_job(
        func=lambda: logger.info("Analytics refresh tick"),
        seconds=600,
        name="analytics_refresh",
    )

    # Daily summary at ~4:05 PM
    def send_daily_summary() -> None:
        summary = generate_daily_summary(database, [symbol])
        notifier.alert(
            symbol="SUMMARY",
            alert_type="Daily Summary",
            title="Daily Market Summary",
            message=summary,
        )

    scheduler.add_daily_job(
        func=send_daily_summary,
        hour=16,
        minute=5,
        name="daily_summary",
    )

    scheduler.start()

    # Start stop-listener thread
    threading.Thread(target=stop_listener, daemon=True).start()

    # Start dashboard if enabled
    if app_config.enable_dashboard:
        threading.Thread(target=run_dashboard, daemon=True).start()

    # here is the main loop
    try:
        while running:
            # Fetch current price
            current_price = get_stock_price(symbol)

            # Handle API failure
            if current_price is None:
                logger.warning("Unable to retrieve price.")
                time.sleep(check_interval)
                continue

            # Store price in database
            database.insert_price(symbol, current_price)

            # Fetch recent price series for analysis
            series = database.get_recent_prices(symbol, limit=200)
            analysis: Dict[str, Any] = analyze_series(series)

            # Calculate percent drop from initial price
            drop_percent = (
                (initial_price - current_price) / initial_price
            ) * 100

            logger.info(
                "%s | Price: %.2f | Drop: %.2f%%",
                symbol,
                current_price,
                drop_percent,
            )

            # Indicators for alerts
            rsi14 = analysis.get("rsi14")
            z_score = analysis.get("z_score")

            # Volume stats for volume-based alerts
            volume, avg_volume = compute_volume_stats(symbol)

            alert_data: Dict[str, Any] = {
                "price": current_price,
                "rsi": rsi14 if rsi14 is not None else 0.0,
                "zscore": z_score if z_score is not None else 0.0,
                "volume": volume,
                "avg_volume": avg_volume,
            }

            alert_engine.evaluate(symbol, alert_data)

            # USER-DEFINED PRICE ALERT (limit-style notification)
            if not alert_triggered and current_price <= alert_price:
                notifier.alert(
                    symbol,
                    "price_alert",
                    f"{symbol} Price Alert",
                    (
                        "Your target price was reached.\n"
                        f"Alert Price: ${alert_price:.2f}\n"
                        f"Current Price: ${current_price:.2f}"
                    ),
                )
                logger.info(
                    "User price alert triggered at %.2f for %s",
                    current_price,
                    symbol,
                )
                alert_triggered = True

            # DROP ALERT
            if (
                drop_percent >= app_config.drop_threshold_percent
                and not drop_alert_sent
            ):
                msg_lines = [
                    f"Stock dropped {drop_percent:.2f}%",
                    f"Current Price: ${current_price:.2f}",
                ]

                rsi_val = analysis.get("rsi14")
                if rsi_val is not None:
                    msg_lines.append(f"RSI: {rsi_val:.2f}")

                vol20 = analysis.get("vol20")
                if vol20 is not None:
                    msg_lines.append(f"Volatility (20): {vol20:.4f}")

                prediction = analysis.get("prediction_next")
                if prediction is not None:
                    msg_lines.append(
                        f"Predicted next price: ${prediction:.2f}"
                    )

                notifier.alert(
                    symbol,
                    "drop",
                    f"{symbol} Drop Alert",
                    "\n".join(msg_lines),
                )
                drop_alert_sent = True

            # Real-time WebSocket push
            socketio.emit(
                "price_update",
                {
                    "symbol": symbol,
                    "price": current_price,
                    "rsi": rsi14,
                    "zscore": z_score,
                    "volume": volume,
                    "avg_volume": avg_volume,
                },
                namespace="/stream",
            )

            # NO CHANGE ALERT
            if current_price == last_price:
                unchanged_minutes += 1
            else:
                unchanged_minutes = 0

            if (
                unchanged_minutes
                >= app_config.unchanged_minutes_threshold
            ):
                notifier.alert(
                    symbol,
                    "no_change",
                    f"{symbol} No Change",
                    (
                        "No price change for "
                        f"{app_config.unchanged_minutes_threshold} minutes.\n"
                        "Likely market closed.\n"
                        f"Price: ${current_price:.2f}"
                    ),
                )
                unchanged_minutes = 0

            # ANOMALY ALERT (Z-score)
            if z_score is not None and abs(z_score) >= 2.5:
                notifier.alert(
                    symbol,
                    "anomaly",
                    f"{symbol} Anomaly Detected",
                    (
                        "Price deviated "
                        f"{z_score:.2f}σ from recent mean.\n"
                        f"Current Price: ${current_price:.2f}"
                    ),
                )

            # Update last price
            last_price = current_price

            # Wait for next cycle
            time.sleep(check_interval)

    except KeyboardInterrupt:
        logger.info("Stopped with CTRL + C")
        running = False
        scheduler.stop()

    # SUMMARY ON EXIT
    end_time = datetime.now()
    runtime_minutes = (end_time - start_time).total_seconds() / 60
    percent_change = (
        (last_price - initial_price) / initial_price
    ) * 100

    summary_msg = (
        f"Runtime: {runtime_minutes:.1f} minutes\n"
        f"Start Price: ${initial_price:.2f}\n"
        f"End Price: ${last_price:.2f}\n"
        f"Change: {percent_change:.2f}%"
    )

    notifier.alert(
        symbol,
        "summary",
        f"{symbol} Summary",
        summary_msg,
    )

    logger.info("Program ended.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Prune old DB rows and exit",
    )
    args = parser.parse_args()

    if args.prune:
        removed = prune_old_data("tracker.db", days=30)
        print(f"Pruned {removed} rows")
    else:
        main()
