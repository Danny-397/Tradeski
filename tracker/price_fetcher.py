# tracker/price_fetcher.py
# Fetches latest stock prices via yfinance.

from typing import Optional
import yfinance as yf


def get_stock_price(symbol: str) -> Optional[float]:
    """
    Return the latest closing price for a symbol, or None on failure.

    Tests expect:
        - None on error/empty
        - a positive float on success
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")

        if hist.empty:
            return None

        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def get_ohlc_history(symbol: str, period: str = "1mo", interval: str = "1d") -> list:
    """
    Return a list of OHLC + volume dicts for the requested period/interval.

    Each dict: {timestamp, open, high, low, close, volume}
    Returns [] on any failure.

    Valid period/interval combos (yfinance):
      "1d"/"5m", "5d"/"15m", "1mo"/"1d", "3mo"/"1d", "6mo"/"1d", "1y"/"1d"
    """
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df.empty:
            return []

        result = []
        for idx, row in df.iterrows():
            result.append({
                "timestamp": idx.strftime("%Y-%m-%dT%H:%M:%S"),
                "open":   round(float(row["Open"]),   4),
                "high":   round(float(row["High"]),   4),
                "low":    round(float(row["Low"]),    4),
                "close":  round(float(row["Close"]),  4),
                "volume": int(row.get("Volume", 0) or 0),
            })
        return result
    except Exception:
        return []
