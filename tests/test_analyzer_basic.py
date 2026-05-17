from tracker.analyzer import analyze_series


def test_analyze_series_basic():
    # Create a simple increasing price series
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
