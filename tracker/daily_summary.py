# tracker/daily_summary.py
# Generates a daily summary of price and volume changes.


import time
from datetime import datetime, timedelta


def generate_daily_summary(db, symbols):
    """
    Build a text summary for the last trading day.

    Args:
        db: Database instance with get_prices_in_range().
        symbols: List of stock symbols to summarize.

    Returns:
        A formatted multi-line string summary.
    """
    now = datetime.utcnow()
    start = now - timedelta(days=1)
    start_ts = start.timestamp()

    lines = []
    lines.append(f"Daily Summary ({now.strftime('%Y-%m-%d')})")
    lines.append("-" * 32)

    for symbol in symbols:
        rows = db.get_prices_in_range(symbol, start_ts, time.time())
        if not rows:
            lines.append(f"{symbol}: no data for period")
            continue

        # rows: list of (timestamp, price, volume, ...)
        first_price = rows[0][1]
        last_price = rows[-1][1]
        change = last_price - first_price
        pct = (change / first_price) * 100 if first_price else 0

        total_volume = sum(r[2] for r in rows)

        lines.append(
            f"{symbol}: {last_price:.2f} "
            f"({change:+.2f}, {pct:+.2f}%) | Vol: {total_volume:,}"
        )

    return "\n".join(lines)
