from tracker.analyzer import analyze_series


def test_analyze_series_empty():
    result = analyze_series([])
    assert result == {}


def test_analyze_series_basic():
    data = [(str(i), float(i)) for i in range(1, 30)]
    result = analyze_series(data)
    assert "sma20" in result
