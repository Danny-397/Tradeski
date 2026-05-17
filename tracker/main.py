import threading
import time
from datetime import datetime
from typing import Any, Dict

from . import database
from .analyzer import analyze_series
from .config import (
    load_app_config,
    load_pushover_config,
)
from .dashboard import run_dashboard
from .logger import get_logger
from .notifier import Notifier
from .price_fetcher import get_stock_price

logger = get_logger(__name__)

running = True


def stop_listener() -> None:
    """
    Listen for a stop command and shut down gracefully.
    """
    global running

    while running:
        command = input(
            "\nType 'stop' to quit:\n"
        ).lower()

        if command == "stop":
            running = False
            logger.info(
                "Stop command received. "
                "Shutting down..."
            )
            break


def main() -> None:
    """
    Run the real-time stock tracker.
    """
    app_config = load_app_config()
    pushover_config = load_pushover_config()

    notifier = Notifier(
        pushover_config
    )

    database.init_db()

    symbol: str = app_config.stock_symbol
    check_interval: int = (
        app_config.check_interval
    )

    initial_price = get_stock_price(
        symbol
    )

    if initial_price is None:
        logger.error(
            "Invalid stock symbol: %s",
            symbol,
        )
        return

    logger.info(
        "Tracking %s | "
        "Starting price: %.2f",
        symbol,
        initial_price,
    )

    database.insert_price(
        symbol,
        initial_price,
    )

    start_time = datetime.now()

    last_price: float = (
        initial_price
    )
    unchanged_minutes: int = 0
    alert_sent: bool = False

    threading.Thread(
        target=stop_listener,
        daemon=True,
    ).start()

    if app_config.enable_dashboard:
        threading.Thread(
            target=run_dashboard,
            daemon=True,
        ).start()

    try:
        while running:
            current_price = (
                get_stock_price(symbol)
            )

            if current_price is None:
                logger.warning(
                    "Unable to retrieve price."
                )
                time.sleep(
                    check_interval
                )
                continue

            database.insert_price(
                symbol,
                current_price,
            )

            drop_percent = (
                (
                    initial_price
                    - current_price
                )
                / initial_price
            ) * 100

            logger.info(
                "%s | Price: %.2f | "
                "Drop: %.2f%%",
                symbol,
                current_price,
                drop_percent,
            )

            series = (
                database.get_recent_prices(
                    symbol,
                    limit=200,
                )
            )

            analysis: Dict[
                str,
                Any,
            ] = analyze_series(
                series
            )

            # DROP ALERT
            if (
                drop_percent
                >= app_config
                .drop_threshold_percent
                and not alert_sent
            ):
                msg_lines = [
                    (
                        "Stock dropped "
                        f"{drop_percent:.2f}%"
                    ),
                    (
                        "Current Price: "
                        f"${current_price:.2f}"
                    ),
                ]

                rsi14 = analysis.get(
                    "rsi14"
                )

                if rsi14 is not None:
                    msg_lines.append(
                        f"RSI: {rsi14:.2f}"
                    )

                vol20 = analysis.get(
                    "vol20"
                )

                if vol20 is not None:
                    msg_lines.append(
                        "Volatility (20): "
                        f"{vol20:.4f}"
                    )

                prediction = (
                    analysis.get(
                        "prediction_next"
                    )
                )

                if prediction is not None:
                    msg_lines.append(
                        "Predicted next "
                        f"price: "
                        f"${prediction:.2f}"
                    )

                notifier.alert(
                    symbol,
                    "drop",
                    f"{symbol} Drop Alert",
                    "\n".join(
                        msg_lines
                    ),
                )

                alert_sent = True

            # NO CHANGE ALERT
            if (
                current_price
                == last_price
            ):
                unchanged_minutes += 1
            else:
                unchanged_minutes = 0

            if (
                unchanged_minutes
                >= app_config
                .unchanged_minutes_threshold
            ):
                notifier.alert(
                    symbol,
                    "no_change",
                    (
                        f"{symbol} "
                        "No Change"
                    ),
                    (
                        "No price change "
                        f"for "
                        f"{app_config.unchanged_minutes_threshold} "
                        "minutes.\n"
                        "Likely market "
                        "closed.\n"
                        f"Price: "
                        f"${current_price:.2f}"
                    ),
                )

                unchanged_minutes = 0

            # ANOMALY ALERT
            z_score = analysis.get(
                "z_score"
            )

            if (
                z_score is not None
                and abs(z_score)
                >= 2.5
            ):
                notifier.alert(
                    symbol,
                    "anomaly",
                    (
                        f"{symbol} "
                        "Anomaly Detected"
                    ),
                    (
                        "Price deviated "
                        f"{z_score:.2f}σ "
                        "from recent "
                        "mean.\n"
                        "Current Price: "
                        f"${current_price:.2f}"
                    ),
                )

            last_price = (
                current_price
            )

            time.sleep(
                check_interval
            )

    except KeyboardInterrupt:
        logger.info(
            "Stopped with CTRL + C"
        )

    end_time = datetime.now()

    runtime_minutes = (
        end_time - start_time
    ).total_seconds() / 60

    percent_change = (
        (
            last_price
            - initial_price
        )
        / initial_price
    ) * 100

    summary_msg = (
        f"Runtime: "
        f"{runtime_minutes:.1f} "
        "minutes\n"
        f"Start Price: "
        f"${initial_price:.2f}\n"
        f"End Price: "
        f"${last_price:.2f}\n"
        f"Change: "
        f"{percent_change:.2f}%"
    )

    notifier.alert(
        symbol,
        "summary",
        f"{symbol} Summary",
        summary_msg,
    )

    logger.info(
        "Program ended."
    )


if __name__ == "__main__":
    main()
