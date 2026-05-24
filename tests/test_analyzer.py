def analyze_series(data: list[tuple[str, float]]) -> dict:
    """Compute all indicators from a list of (timestamp, price) tuples."""
    if not data:
        return {}

    prices = [p for _, p in data]

    sma20_vals = sma(prices, 20)
    ema20_vals = ema(prices, 20)
    rsi14_vals = rsi(prices, 14)
    upper_bb, lower_bb = bollinger_bands(prices, 20)
    macd_line, signal_line, histogram = macd(prices)
    z_vals = zscore(prices, 20)
    vol_vals = volatility(prices, 20)
    lr_pred = linear_regression_prediction(prices)

    return {
        "sma20": sma20_vals[-1],
        "ema20": ema20_vals[-1],
        "rsi14": rsi14_vals[-1],
        "bb_upper": upper_bb[-1],
        "bb_lower": lower_bb[-1],
        "macd": macd_line[-1],
        "macd_signal": signal_line[-1],
        "macd_hist": histogram[-1],
        "zscore": z_vals[-1],
        "volatility": vol_vals[-1],
        "prediction_next": lr_pred,
    }
