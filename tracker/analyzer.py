from typing import List, Tuple, Optional, Dict
import numpy as np
from .logger import get_logger

logger = get_logger(__name__)


def _extract_prices(data: List[Tuple[str, float]]) -> np.ndarray:
    """
    Extract only the price values from a list of (timestamp, price) tuples.

    Args:
        data: A list of (timestamp, price) tuples.

    Returns:
        A NumPy array of price values.
    """
    return np.array([p for _, p in data], dtype=float)


def simple_moving_average(prices: np.ndarray, window: int) -> Optional[float]:
    """
    Compute a simple moving average over the given window.

    Args:
        prices: Array of price values.
        window: Number of periods to average.

    Returns:
        The SMA value, or None if insufficient data.
    """
    if len(prices) < window:
        return None
    return float(prices[-window:].mean())


def exponential_moving_average(prices: np.ndarray, window: int) -> Optional[float]:
    """
    Compute an exponential moving average over the given window.

    Args:
        prices: Array of price values.
        window: Number of periods to average.

    Returns:
        The EMA value, or None if insufficient data.
    """
    if len(prices) < window:
        return None

    weights = np.exp(np.linspace(-1.0, 0.0, window))
    weights /= weights.sum()

    return float((prices[-window:] * weights).sum())


def rsi(prices: np.ndarray, period: int = 14) -> Optional[float]:
    """
    Compute the Relative Strength Index (RSI).

    Args:
        prices: Array of price values.
        period: Lookback period for RSI.

    Returns:
        RSI value between 0 and 100, or None if insufficient data.
    """
    if len(prices) <= period:
        return None

    deltas = np.diff(prices)
    gains = deltas.clip(min=0)
    losses = -deltas.clip(max=0)

    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def volatility(prices: np.ndarray, window: int = 20) -> Optional[float]:
    """
    Compute rolling volatility (standard deviation).

    Args:
        prices: Array of price values.
        window: Number of periods to compute volatility.

    Returns:
        Standard deviation of the window, or None if insufficient data.
    """
    if len(prices) < window:
        return None
    return float(prices[-window:].std())


def z_score_latest(prices: np.ndarray, window: int = 20) -> Optional[float]:
    """
    Compute the z-score of the most recent price relative to the window.

    Args:
        prices: Array of price values.
        window: Number of periods to compute z-score.

    Returns:
        Z-score of the latest price, or None if insufficient data.
    """
    if len(prices) < window:
        return None

    window_data = prices[-window:]
    mean = window_data.mean()
    std = window_data.std()

    if std == 0:
        return 0.0

    return float((window_data[-1] - mean) / std)


def linear_regression_prediction(
    data: List[Tuple[str, float]],
    horizon_steps: int = 1
) -> Optional[float]:
    """
    Predict a future price using simple linear regression.

    Args:
        data: List of (timestamp, price) tuples.
        horizon_steps: How many steps ahead to predict.

    Returns:
        Predicted price, or None if insufficient data.
    """
    if len(data) < 5:
        return None

    prices = _extract_prices(data)
    x = np.arange(len(prices))

    slope, intercept = np.polyfit(x, prices, 1)
    future_x = len(prices) + horizon_steps

    return float(slope * future_x + intercept)


def analyze_series(data: List[Tuple[str, float]]) -> Dict[str, Optional[float]]:
    """
    Run a full technical analysis on a price series.

    Args:
        data: List of (timestamp, price) tuples.

    Returns:
        A dictionary containing SMA, EMA, RSI, volatility, z-score,
        and a linear regression prediction.
    """
    if not data:
        return {}

    prices = _extract_prices(data)

    return {
        "sma20": simple_moving_average(prices, 20),
        "sma50": simple_moving_average(prices, 50),
        "ema20": exponential_moving_average(prices, 20),
        "rsi14": rsi(prices, 14),
        "vol20": volatility(prices, 20),
        "z_score": z_score_latest(prices, 20),
        "prediction_next": linear_regression_prediction(data, 1),
    }
