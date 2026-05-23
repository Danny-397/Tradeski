from typing import List, Tuple, Optional, Dict
import numpy as np
from .logger import get_logger

logger = get_logger(__name__)


def _extract_prices(data: List[Tuple[str, float]]) -> np.ndarray:
    """
    Extract only the price values from a list of (timestamp, price) tuples.
    """
    return np.array([p for _, p in data], dtype=float)


def simple_moving_average(prices: np.ndarray, window: int) -> Optional[float]:
    """
    Compute a simple moving average over the given window.
    """
    if len(prices) < window:
        return None
    return float(prices[-window:].mean())


def exponential_moving_average(prices: np.ndarray, window: int) -> Optional[float]:
    """
    Compute an exponential moving average over the given window.
    """
    if len(prices) < window:
        return None

    weights = np.exp(np.linspace(-1.0, 0.0, window))
    weights /= weights.sum()
    return float((prices[-window:] * weights).sum())


def rsi(prices: np.ndarray, period: int = 14) -> Optional[float]:
    """
    Compute the Relative Strength Index (RSI).
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
    """
    if len(prices) < window:
        return None
    return float(prices[-window:].std())


def z_score_latest(prices: np.ndarray, window: int = 20) -> Optional[float]:
    """
    Compute the z-score of the most recent price relative to the window.
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

    Returns both:
    - raw indicator names (sma20, ema20, rsi14, z_score, etc.)
    - normalized names used by the alert engine (sma, ema, rsi, zscore)
    """
    if not data:
        return {}

    prices = _extract_prices(data)

    sma20 = simple_moving_average(prices, 20)
    ema20 = exponential_moving_average(prices, 20)
    rsi14 = rsi(prices, 14)
    vol20 = volatility(prices, 20)
    z_val = z_score_latest(prices, 20)
    pred = linear_regression_prediction(data, 1)

    return {
        "sma20": sma20,
        "sma50": simple_moving_average(prices, 50),
        "ema20": ema20,
        "rsi14": rsi14,
        "vol20": vol20,
        "z_score": z_val,
        "prediction_next": pred,
        "sma": sma20,
        "ema": ema20,
        "rsi": rsi14,
        "zscore": z_val,
    }
