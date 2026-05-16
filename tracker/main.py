import time
import threading
from datetime import datetime

from .config import load_app_config, load_pushover_config
from .logger import get_logger
from . import database
from .price_fetcher import get_stock_price
from .notifier import Notifier
from .analyzer import analyze_series
from .dashboard import run_dashboard

logger = get_logger(__name__)

running = True


def stop_listener():
    global running
    while running:
        command = input("\nType 'stop' to quit:\n").lower()
        if command == "stop":
            running = False
            logger.info("Stop command received. Shutting down...")
            break


def main():
    global running

    app_config = load_app_config()
    pushover_config = load_pushover_config()
    notifier = Notifier(pushover_config)

    database.init_db()

    symbol = app_config.stock_symbol
    check_interval = app_config.check_interval

    initial_price = get_stock_price(symbol)
    if initial_price is None:
        logger.error("Invalid stock symbol: %s", symbol)
        return

    logger.info("Tracking %s | Starting price: %.2f", symbol, initial_price)
    database.insert_price(symbol, initial_price)

    start_time = datetime.now()
    last_price = initial_price
    unchanged_minutes = 0
    alert_sent = False

    threading.Thread(target=stop_listener, daemon=True).start()

    if app_config.enable_dashboard:
        threading.Thread(target=run_dashboard, daemon=True).start()

    try:
        while running:
            current_price = get_stock_price(symbol)
            if current_price is None:
                logger.warning("Unable to retrieve price.")
                time.sleep(check_interval)
                continue

            database.insert_price(symbol, current_price)

            drop_percent = ((initial_price - current_price) / initial_price) * 100
            logger.info(
                "%s | Price: %.2f | Drop: %.2f%%",
                symbol,
                current_price,
                drop_percent,
            )

            series = database.get_recent_prices(symbol, limit=200)
            analysis = analyze_series(series)

            # DROP ALERT
            if drop_percent >= app_config.drop_threshold_percent and not alert_sent:
                msg_lines = [
                    f"Stock dropped {drop_percent:.2f}%",
                    f"Current Price: ${current_price:.2f}",
                ]
                if analysis.get("rsi14") is not None:
                    msg_lines.append(f"RSI: {analysis['rsi14']:.2f}")
                if analysis.get("vol20") is not None:
                    msg_lines.append(f"Volatility (20): {analysis['vol20']:.4f}")
                if analysis.get("prediction_next") is not None:
                    msg_lines.append(
                        f"Predicted next price: ${analysis['prediction_next']:.2f}"
                    )

                notifier.alert(
                    symbol,
                    "drop",
                    f"{symbol} Drop Alert",
                    "\n".join(msg_lines),
                )
                alert_sent = True

            # NO CHANGE ALERT
            if current_price == last_price:
                unchanged_minutes += 1
            else:
                unchanged_minutes = 0

            if unchanged_minutes >= app_config.unchanged_minutes_threshold:
                notifier.alert(
                    symbol,
                    "no_change",
                    f"{symbol} No Change",
                    f"No price change for {app_config.unchanged_minutes_threshold} minutes.\n"
                    f"Likely market closed.\nPrice: ${current_price:.2f}",
                )
                unchanged_minutes = 0

            # Anomaly alert (z-score)
            z = analysis.get("z_score")
            if z is not None and abs(z) >= 2.5:
                notifier.alert(
                    symbol,
                    "anomaly",
                    f"{symbol} Anomaly Detected",
                    f"Price deviated {z:.2f}σ from recent mean.\n"
                    f"Current Price: ${current_price:.2f}",
                )

            last_price = current_price
            time.sleep(check_interval)

    except KeyboardInterrupt:
        logger.info("Stopped with CTRL + C")

    end_time = datetime.now()
    runtime_minutes = (end_time - start_time).total_seconds() / 60
    summary_msg = (
        f"Runtime: {runtime_minutes:.1f} minutes\n"
        f"Start Price: ${initial_price:.2f}\n"
        f"End Price: ${last_price:.2f}\n"
        f"Change: {((last_price - initial_price) / initial_price) * 100:.2f}%"
    )
    notifier.alert(symbol, "summary", f"{symbol} Summary", summary_msg)
    logger.info("Program ended.")


if __name__ == "__main__":
    main()
