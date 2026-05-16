from typing import Optional
import yfinance as yf
from .logger import get_logger

logger = get_logger(__name__)


def get_stock_price(symbol: str) -> Optional[float]:
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info.get("last_price")

        if price is None:
            data = ticker.history(period="1d")
            if data.empty:
                logger.warning("No price data for symbol %s", symbol)
                return None
            price = float(data["Close"].iloc[-1])

        return float(price)

    except Exception as e:
        logger.error("Error retrieving price for %s: %s", symbol, e)
        return None
