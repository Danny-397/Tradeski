# Main entry point for the real-time stock tracker.
# Handles:
# - Config loading
# - User-defined price alert
# - Dashboard startup
# - Stop listener thread
# - Tracking loop
# - Alerts (drop, no-change, anomaly, price alert)
# - Summary notification

import threading
import time
from datetime import datetime
from typing import Any, Dict
from .scheduler import SchedulerManager
from .pruning import prune_old_data

from . import database
from .analyzer import analyze_series
from .config import load_app_config, load_pushover_config
from .dashboard import run_dashboard
from .logger import get_logger
from .notifier import Notifier
from .price_fetcher import get_stock_price
from .alerts import AlertEngine, AlertRule, price_above, price_below, rsi_overbought, rsi_oversold, sma_cross_up, sma_cross_down


logger = get_logger(__name__)


# Global flag used to stop the tracking loop
running = True


def stop_listener() -> None:
    # Background thread that waits for the user to type 'stop'
    # When triggered, it sets the global `running` flag to False
    global running

    while running:
        command = input("\nType 'stop' to quit:\n").lower()

        if command == "stop":
            running = False
            logger.info("Stop command received. Shutting down...")
            break


def get_user_alert_price() -> float:
    # Prompt the user for a target price alert (limit-style)
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

    last_prune = 0
PRUNE_INTERVAL = 86400  # once per day



def main() -> None:
    # Main function that runs the real-time stock tracker

    # Load configuration files
    app_config = load_app_config()
    pushover_config = load_pushover_config()

    # Notification handler
    notifier = Notifier(pushover_config)

    alert_engine = AlertEngine(notifier)
# Initalize the alert engine 
# Example alert rules
alert_engine.add_rule(AlertRule(
    name="Price Above Target",
    condition=price_above(200),
    message="Price is above target: {price}"
))

alert_engine.add_rule(AlertRule(
    name="Price Below Target",
    condition=price_below(150),
    message="Price dropped below threshold: {price}"
))

alert_engine.add_rule(AlertRule(
    name="RSI Overbought",
    condition=rsi_overbought(),
    message="RSI is overbought at {rsi}"
))

alert_engine.add_rule(AlertRule(
    name="RSI Oversold",
    condition=rsi_oversold(),
    message="RSI is oversold at {rsi}"
))

alert_engine.add_rule(AlertRule(
    name="SMA Bullish Crossover",
    condition=sma_cross_up(),
    message="SMA crossed above EMA (bullish)"
))

alert_engine.add_rule(AlertRule(
    name="SMA Bearish Crossover",
    condition=sma_cross_down(),
    message="SMA crossed below EMA (bearish)"


alert_engine.evaluate(symbol, {
    "price": price,
    "sma": sma,
    "ema": ema,
    "rsi": rsi
})

))


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

    # Start stop-listener thread
    threading.Thread(target=stop_listener, daemon=True).start()

    # Start dashboard if enabled
    if app_config.enable_dashboard:
        threading.Thread(target=run_dashboard, daemon=True).start()

    
    # MAIN TRACKING LOOP
scheduler.start()


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

            # Run pruning once per day
if time.time() - last_prune > PRUNE_INTERVAL:
    removed = prune_old_data("tracker.db", days=30)
    logger.info(f"Pruned {removed} old rows from database")
    last_prune = time.time()
# logs how many rows were removed

    if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--prune", action="store_true", help="Prune old DB rows and exit")
    args = parser.parse_args()

    if args.prune:
        removed = prune_old_data("tracker.db", days=30)
        print(f"Pruned {removed} rows")
        exit()


            # Fetch recent price series for analysis
            series = database.get_recent_prices(symbol, limit=200)
            analysis: Dict[str, Any] = analyze_series(series)

            
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

                # Add RSI if available
                rsi14 = analysis.get("rsi14")
                if rsi14 is not None:
                    msg_lines.append(f"RSI: {rsi14:.2f}")

                # Add volatility if available
                vol20 = analysis.get("vol20")
                if vol20 is not None:
                    msg_lines.append(f"Volatility (20): {vol20:.4f}")

                # Add prediction if available
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
            
            z_score = analysis.get("z_score")
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
        scheduler.stop()


    # SUMMARY ON EXIT
    end_time = datetime.now()

    runtime_minutes = (
        end_time - start_time
    ).total_seconds() / 60

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
    main()
# initzilize scheduler 
scheduler = SchedulerManager()


# Daily pruning at 4:00 AM
scheduler.add_daily_job(
    func=lambda: prune_old_data("tracker.db", days=30),
    hour=4,
    minute=0,
    name="daily_prune"
)

# Optional: run analytics refresh every 10 minutes
scheduler.add_interval_job(
    func=lambda: logger.info("Analytics refresh tick"),
    seconds=600,
    name="analytics_refresh"
)

