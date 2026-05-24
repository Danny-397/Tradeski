import numpy as np
from typing import List, Tuple


def sma(values: List[float], period: int) -> List[float]:
    """Simple Moving Average (exact, no floating‑point drift)."""
    if len(values) < period:
        return [None] * len(values)

    result = [None] * (period - 1)

    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        avg = sum(window) / period
        result.append(avg)

    return result


def ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    result = []
    k = 2 / (period + 1)
    ema_prev = values[0]

    for price in values:
        ema_prev = price * k + ema_prev * (1 - k)
        result.append(ema_prev)

    return result


def rsi(values: List[float], period: int = 14) -> List[float]:
    """Relative Strength Index."""
    if len(values) < period + 1:
        return [None] * len(values)

    deltas = np.diff(values)
    seed = deltas[:period]
    up = seed[seed > 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0

    rsi_list = [None] * period
    rsi_list.append(100 - (100 / (1 + rs)))

    for delta in deltas[period:]:
        up_val = max(delta, 0)
        down_val = -min(delta, 0)

        up = (up * (period - 1) + up_val) / period
        down = (down * (period - 1) + down_val) / period

        rs = up / down if down != 0 else 0
        rsi_list.append(100 - (100 / (1 + rs)))

    return rsi_list


def bollinger_bands(
    values: List[float],
    period: int = 20,
    std_factor: float = 2.0
) -> Tuple[List[float], List[float]]:
    """Bollinger Bands."""
    if len(values) < period:
        return [None] * len(values), [None] * len(values)

    sma_vals = sma(values, period)
    upper = []
    lower = []

    for i in range(len(values)):
        if i < period - 1:
            upper.append(None)
            lower.append(None)
            continue

        window = values[i - period + 1:i + 1]
        std = np.std(window)

        upper.append(sma_vals[i] + std_factor * std)
        lower.append(sma_vals[i] - std_factor * std)

    return upper, lower


def macd(values: List[float]) -> Tuple[List[float], List[float], List[float]]:
    """MACD indicator."""
    ema12 = ema(values, 12)
    ema26 = ema(values, 26)

    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal_line = ema(macd_line, 9)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]

    return macd_line, signal_line, histogram


def zscore(values: List[float], period: int = 20) -> List[float]:
    """Rolling Z‑score."""
    result = []

    for i in range(len(values)):
        if i < period:
            result.append(None)
            continue

        window = values[i - period:i]
        mean = np.mean(window)
        std = np.std(window)

        if std == 0:
            result.append(0)
        else:
            result.append((values[i] - mean) / std)

    return result


def volatility(values: List[float], period: int = 20) -> List[float]:
    """Rolling volatility (standard deviation)."""
    result = []

    for i in range(len(values)):
        if i < period:
            result.append(None)
            continue

        window = values[i - period:i]
        result.append(np.std(window))

    return result


def linear_regression_prediction(values: List[float]) -> float | None:
    """Predict next value using least‑squares linear regression."""
    if len(values) < 10:
        return None

    x = np.arange(len(values))
    y = np.array(values)

    A = np.vstack([x, np.ones(len(x))]).T
    m, b = np.linalg.lstsq(A, y, rcond=None)[0]

    return float(m * len(values) + b)


def analyze_series(data: List[Tuple[str, float]]) -> dict:
    """Compute key indicators from a list of (timestamp, price) tuples."""
    if not data:
        return {}

    prices = [p for _, p in data]

    sma20_vals = sma(prices, 20)
    sma50_vals = sma(prices, 50)
    ema20_vals = ema(prices, 20)
    rsi14_vals = rsi(prices, 14)
    vol20_vals = volatility(prices, 20)
    z_vals = zscore(prices, 20)
    pred = linear_regression_prediction(prices)

    return {
        "sma20": sma20_vals[-1],
        "sma50": sma50_vals[-1],
        "ema20": ema20_vals[-1],
        "rsi14": rsi14_vals[-1],
        "vol20": vol20_vals[-1],
        "z_score": z_vals[-1],
        "prediction_next": pred,
    }
