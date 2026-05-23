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
