def analyze_series(data: list[tuple[str, float]]) -> dict:
    """Compute all indicators from a list of (timestamp, price) tuples."""
    if not data:
        return {}

    prices = [p for _, p in data]

    sma20_vals = sma(prices, 20)
    sma50_vals = sma(prices, 50)
    ema20_vals = ema(prices, 20)
    rsi14_vals = rsi(prices, 14)
    vol20_vals = volatility(prices, 20)
    z_vals = zscore(prices, 20)
    lr_pred = linear_regression_prediction(prices)

    return {
        "sma20": sma20_vals[-1],
        "sma50": sma50_vals[-1],
        "ema20": ema20_vals[-1],
        "rsi14": rsi14_vals[-1],
        "vol20": vol20_vals[-1],
        "z_score": z_vals[-1],
        "prediction_next": lr_pred,
    }
