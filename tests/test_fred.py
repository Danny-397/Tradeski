"""Tests for tracker/fred.py — uses unittest.mock to avoid hitting the real API."""

from unittest.mock import patch, MagicMock

from tracker.fred import get_macro_snapshot, format_macro_context


def _make_obs(value: str, date: str = "2025-01-01") -> dict:
    return {"value": value, "date": date}


def _mock_obs(series_responses: dict):
    """Return a side_effect for requests.get that serves canned observations."""
    def _side_effect(url, params=None, **kwargs):
        sid = (params or {}).get("series_id", "")
        obs = series_responses.get(sid, [])
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.json.return_value = {"observations": obs}
        return mock
    return _side_effect


@patch("tracker.fred.requests.get")
def test_get_macro_snapshot_happy_path(mock_get):
    mock_get.side_effect = _mock_obs({
        "CPIAUCSL":     [_make_obs("3.2"), _make_obs("3.0")],
        "FEDFUNDS":     [_make_obs("5.33"), _make_obs("5.33")],
        "GDP":          [_make_obs("22000"), _make_obs("21900")],
        "UNRATE":       [_make_obs("3.9"), _make_obs("4.0")],
        "DGS10":        [_make_obs("4.3"), _make_obs("4.1")],
        "T10Y2Y":       [_make_obs("-0.5"), _make_obs("-0.3")],
        "BAMLH0A0HYM2": [_make_obs("3.5"), _make_obs("3.4")],
    })

    snap = get_macro_snapshot("fake_key")

    assert "CPIAUCSL" in snap
    assert snap["CPIAUCSL"]["value"] == 3.2
    assert snap["CPIAUCSL"]["trend"] == "up"

    assert snap["UNRATE"]["trend"] == "down"   # 3.9 < 4.0

    assert snap["FEDFUNDS"]["trend"] == "neutral"  # same value


@patch("tracker.fred.requests.get")
def test_get_macro_snapshot_handles_missing_series(mock_get):
    mock_get.side_effect = _mock_obs({})  # all series return empty

    snap = get_macro_snapshot("fake_key")

    for info in snap.values():
        assert info["value"] is None
        assert info["trend"] == "neutral"


@patch("tracker.fred.requests.get")
def test_get_macro_snapshot_ignores_dot_values(mock_get):
    mock_get.side_effect = _mock_obs({
        "CPIAUCSL": [{"value": ".", "date": "2025-01-01"}],
    })

    snap = get_macro_snapshot("fake_key")
    assert snap["CPIAUCSL"]["value"] is None


@patch("tracker.fred.requests.get")
def test_format_macro_context(mock_get):
    mock_get.side_effect = _mock_obs({
        "CPIAUCSL":     [_make_obs("3.2"), _make_obs("3.0")],
        "FEDFUNDS":     [_make_obs("5.33"), _make_obs("5.33")],
        "GDP":          [_make_obs("22000"), _make_obs("21900")],
        "UNRATE":       [_make_obs("3.9"), _make_obs("4.0")],
        "DGS10":        [_make_obs("4.3"), _make_obs("4.1")],
        "T10Y2Y":       [_make_obs("-0.5"), _make_obs("-0.3")],
        "BAMLH0A0HYM2": [_make_obs("3.5"), _make_obs("3.4")],
    })
    snap = get_macro_snapshot("fake_key")
    ctx = format_macro_context(snap)

    assert "LIVE FRED MACRO DATA" in ctx
    assert "CPI" in ctx
    assert "3.2" in ctx
    assert "↑" in ctx
