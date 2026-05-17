from typing import Optional
import yfinance as yf

from .logger import get_logger

logger = get_logger(__name__)


def get_stock_price(symbol: str) -> Optional[float]:
    """
    Retrieve the latest stock price for a given symbol using yfinance.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL").

    Returns:
        The latest price as a float, or None if unavailable or an error occurs.
    """
    try:
        ticker = yf.Ticker(symbol)

        # Fast path: use fast_info if available
        price = ticker.fast_info.get("last_price")

        # Fallback: use historical data
        if price is None:
            data = ticker.history(period="1d")
            if data.empty:
                logger.warning("No price data for symbol %s", symbol)
                return None

            price = float(data["Close"].iloc[-1])

        return float(price)

    except Exception as error:
        logger.error("Error retrieving price for %s: %s", symbol, error)
        return None
