from tracker.analyzer import (
    sma,
    ema,
    rsi,
    volatility,
    zscore,
    linear_regression_prediction,
    analyze_series,
)


def test_indicator_functions_basic():
    values = [float(i) for i in range(1, 51)]

    sma20 = sma(values, 20)
    sma50 = sma(values, 50)
    ema20 = ema(values, 20)
    rsi14 = rsi(values, 14)
    vol20 = volatility(values, 20)
    z_vals = zscore(values, 20)
    pred = linear_regression_prediction(values)

    assert len(sma20) == len(values)
    assert len(sma50) == len(values)
    assert len(ema20) == len(values)
    assert len(rsi14) == len(values)
    assert len(vol20) == len(values)
    assert len(z_vals) == len(values)
    assert pred is not None


def test_analyze_series_basic():
    # Simple increasing price series
    data = [(str(i), float(i)) for i in range(1, 51)]

    result = analyze_series(data)

    # SMA20 should be the mean of last 20 numbers (31–50)
    expected_sma20 = sum(range(31, 51)) / 20

    assert result["sma20"] == expected_sma20
    assert result["sma50"] is not None
    assert result["ema20"] is not None
    assert result["rsi14"] is not None
    assert result["vol20"] is not None
    assert result["z_score"] is not None
    assert result["prediction_next"] is not None
