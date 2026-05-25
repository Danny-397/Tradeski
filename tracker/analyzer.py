import numpy as np
from typing import List, Tuple, Optional


def sma(values: List[float], period: int) -> List[Optional[float]]:
    """Simple Moving Average (exact, no floating-point drift)."""
    if len(values) < period:
        return [None] * len(values)

    result: List[Optional[float]] = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    k       = 2 / (period + 1)
    ema_val = values[0]
    result  = []
    for price in values:
        ema_val = price * k + ema_val * (1 - k)
        result.append(ema_val)
    return result


def rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    """Relative Strength Index (Wilder smoothing)."""
    if len(values) < period + 1:
        return [None] * len(values)

    deltas = np.diff(values)
    seed   = deltas[:period]
    up     = seed[seed > 0].sum() / period
    down   = -seed[seed < 0].sum() / period
    rs     = up / down if down != 0 else 0

    result: List[Optional[float]] = [None] * period
    result.append(100 - (100 / (1 + rs)))

    for delta in deltas[period:]:
        up_v   = max(delta, 0)
        down_v = -min(delta, 0)
        up     = (up * (period - 1) + up_v) / period
        down   = (down * (period - 1) + down_v) / period
        rs     = up / down if down != 0 else 0
        result.append(100 - (100 / (1 + rs)))

    return result


def bollinger_bands(
    values: List[float],
    period: int = 20,
    std_factor: float = 2.0,
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """Bollinger Bands (upper, lower)."""
    if len(values) < period:
        return [None] * len(values), [None] * len(values)

    sma_vals = sma(values, period)
    upper, lower = [], []

    for i in range(len(values)):
        if i < period - 1:
            upper.append(None)
            lower.append(None)
        else:
            std = np.std(values[i - period + 1:i + 1])
            upper.append(sma_vals[i] + std_factor * std)
            lower.append(sma_vals[i] - std_factor * std)

    return upper, lower


def macd(
    values: List[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> Tuple[List[float], List[float], List[float]]:
    """MACD indicator (line, signal, histogram)."""
    ema_fast   = ema(values, fast)
    ema_slow   = ema(values, slow)
    macd_line  = [a - b for a, b in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal_period)
    histogram  = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram


def zscore(values: List[float], period: int = 20) -> List[Optional[float]]:
    """Rolling Z-score."""
    result: List[Optional[float]] = []
    for i in range(len(values)):
        if i < period:
            result.append(None)
            continue
        window = values[i - period:i]
        mean   = np.mean(window)
        std    = np.std(window)
        result.append(0.0 if std == 0 else (values[i] - mean) / std)
    return result


def volatility(values: List[float], period: int = 20) -> List[Optional[float]]:
    """Rolling standard deviation (volatility proxy)."""
    result: List[Optional[float]] = []
    for i in range(len(values)):
        if i < period:
            result.append(None)
        else:
            result.append(float(np.std(values[i - period:i])))
    return result


def atr(
    high: List[float],
    low: List[float],
    close: List[float],
    period: int = 14,
) -> List[Optional[float]]:
    """Average True Range — measures market volatility."""
    if len(close) < 2:
        return [None] * len(close)

    tr_vals: List[float] = [high[0] - low[0]]
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        )
        tr_vals.append(tr)

    result: List[Optional[float]] = [None] * (period - 1)
    atr_val = float(np.mean(tr_vals[:period]))
    result.append(atr_val)

    for i in range(period, len(tr_vals)):
        atr_val = (atr_val * (period - 1) + tr_vals[i]) / period
        result.append(atr_val)

    return result


def stochastic(
    high: List[float],
    low: List[float],
    close: List[float],
    k_period: int = 14,
    d_period: int = 3,
) -> Tuple[List[Optional[float]], List[Optional[float]]]:
    """Stochastic Oscillator (%K, %D).

    %K measures where the close sits within the high-low range.
    %D is a smoothed signal line of %K.
    """
    k_vals: List[Optional[float]] = []

    for i in range(len(close)):
        if i < k_period - 1:
            k_vals.append(None)
            continue
        h_max = max(high[i - k_period + 1:i + 1])
        l_min = min(low [i - k_period + 1:i + 1])
        denom = h_max - l_min
        k_vals.append(((close[i] - l_min) / denom * 100) if denom != 0 else 50.0)

    # %D = 3-period SMA of %K (skip None values)
    k_clean = [v if v is not None else 0.0 for v in k_vals]
    d_raw   = sma(k_clean, d_period)
    # Mask leading Nones from %K into %D
    first_valid_k = next((i for i, v in enumerate(k_vals) if v is not None), len(k_vals))
    d_vals = [None] * min(first_valid_k + d_period - 1, len(d_raw))
    d_vals += d_raw[len(d_vals):]

    return k_vals, d_vals


def linear_regression_prediction(values: List[float]) -> Optional[float]:
    """Predict next value via least-squares linear regression."""
    if len(values) < 10:
        return None
    x   = np.arange(len(values))
    y   = np.array(values)
    A   = np.vstack([x, np.ones(len(x))]).T
    m, b = np.linalg.lstsq(A, y, rcond=None)[0]
    return float(m * len(values) + b)


def analyze_series(data: List[Tuple[str, float]]) -> dict:
    """Unified interface: (timestamp, price) list → dict of latest indicator values."""
    if not data:
        return {}

    prices = [p for _, p in data]

    sma20_vals  = sma(prices, 20)
    sma50_vals  = sma(prices, 50)
    ema20_vals  = ema(prices, 20)
    rsi14_vals  = rsi(prices, 14)
    vol20_vals  = volatility(prices, 20)
    z_vals      = zscore(prices, 20)
    pred        = linear_regression_prediction(prices)

    # Stochastic uses price as a proxy for high/low (single price series)
    k_vals, d_vals = stochastic(prices, prices, prices)

    return {
        "sma20":        sma20_vals[-1],
        "sma50":        sma50_vals[-1],
        "ema20":        ema20_vals[-1],
        "rsi14":        rsi14_vals[-1],
        "vol20":        vol20_vals[-1],
        "z_score":      z_vals[-1],
        "prediction":   pred,
        "stoch_k":      k_vals[-1],
        "stoch_d":      d_vals[-1],
    }
