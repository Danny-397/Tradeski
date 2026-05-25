from typing import List, Tuple

from tracker.analyzer import (
    sma,
    ema,
    rsi,
    volatility,
    zscore,
    linear_regression_prediction,
    stochastic,
)


def analyze_series(data: List[Tuple[str, float]]) -> dict:
    """Return latest indicator values for a (timestamp, price) series."""
    if not data:
        return {}

    # Extract price series
    prices = [price for _, price in data]

    # Core indicators
    sma20_vals = sma(prices, 20)
    sma50_vals = sma(prices, 50)
    ema20_vals = ema(prices, 20)
    rsi_vals = rsi(prices, 14)
    vol_vals = volatility(prices, 20)
    z_vals = zscore(prices, 20)
    prediction = linear_regression_prediction(prices)

    # Stochastic uses price as proxy for high/low
    k_vals, d_vals = stochastic(prices, prices, prices)

    return {
        "sma20": sma20_vals[-1],
        "sma50": sma50_vals[-1],
        "ema20": ema20_vals[-1],
        "rsi14": rsi_vals[-1],
        "vol20": vol_vals[-1],
        "z_score": z_vals[-1],
        "prediction_next": prediction,   # REQUIRED BY TESTS
        "stoch_k": k_vals[-1],
        "stoch_d": d_vals[-1],
    }
