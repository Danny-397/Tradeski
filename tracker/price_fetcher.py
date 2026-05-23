# tracker/price_fetcher.py
# Retrieves latest price + volume using yfinance.

from typing import Optional, Tuple
import yfinance as yf

from .logger import get_logger

logger = get_logger(__name__)


def get_stock_price(symbol: str) -> Optional[Tuple[float, float]]:
    """
    Retrieve the latest stock price and volume for a given symbol.

    Returns:
        (price, volume) tuple, or None if unavailable.
    """
    try:
        ticker = yf.Ticker(symbol)

        # Fast path: use fast_info if available
        price = ticker.fast_info.get("last_price")
        volume = ticker.fast_info.get("last_volume")

        # Fallback: use historical data
        if price is None or volume is None:
            data = ticker.history(period="1d")
            if data.empty:
                logger.warning("No price data for symbol %s", symbol)
                return None

            price = float(data["Close"].iloc[-1])
            volume = float(data["Volume"].iloc[-1])

        return float(price), float(volume)

    except Exception as error:
        logger.error("Error retrieving price for %s: %s", symbol, error)
        return None
