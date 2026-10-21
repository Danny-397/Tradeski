"""Tests for get_ohlc_history() and the JSON-safety helper in price_fetcher.

The bug these pin: yfinance emits a placeholder bar for the current trading
session whose OHLC is all NaN but whose Volume is a real integer. It therefore
survived the `int(volume)` guard and reached every consumer -- /stats returned
a NaN close, the chart and sparkline endpoints got a gap, and np.corrcoef
turned one NaN row into a whole NaN correlation matrix. NaN is also not valid
JSON: it serialises as the bare token `NaN`, which strict parsers reject.
"""

import json
import math
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tracker.price_fetcher import _num, get_ohlc_history


def _frame(rows):
    """Build a yfinance-shaped OHLCV frame with a DatetimeIndex."""
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {
            "Open":   [r[1] for r in rows],
            "High":   [r[2] for r in rows],
            "Low":    [r[3] for r in rows],
            "Close":  [r[4] for r in rows],
            "Volume": [r[5] for r in rows],
        },
        index=idx,
    )


def _ticker(df):
    t = MagicMock()
    t.history.return_value = df
    return t


@patch("tracker.price_fetcher.yf.Ticker")
def test_drops_the_nan_placeholder_bar(mock_cls):
    """The exact shape yfinance returns intraday: NaN prices, real volume."""
    mock_cls.return_value = _ticker(_frame([
        ("2026-10-19", 340.78, 346.00, 340.12, 342.94, 34_573_200),
        ("2026-10-20", float("nan"), float("nan"), float("nan"),
         float("nan"), 35_678_066),
    ]))

    bars = get_ohlc_history("AAPL", "1y", "1d")

    assert len(bars) == 1, "the NaN placeholder bar must not be returned"
    assert bars[0]["close"] == 342.94
    assert bars[-1]["close"] == 342.94, "last bar must be a real one"


@patch("tracker.price_fetcher.yf.Ticker")
def test_output_is_strict_json(mock_cls):
    """allow_nan=False is what a strict client effectively enforces."""
    mock_cls.return_value = _ticker(_frame([
        ("2026-10-19", 1.0, 2.0, 0.5, 1.5, 100),
        ("2026-10-20", float("nan"), float("nan"), float("nan"),
         float("nan"), 200),
    ]))

    bars = get_ohlc_history("AAPL")
    json.dumps(bars, allow_nan=False)   # raises ValueError if any NaN survived


@patch("tracker.price_fetcher.yf.Ticker")
def test_drops_infinite_bars_too(mock_cls):
    mock_cls.return_value = _ticker(_frame([
        ("2026-10-19", 1.0, float("inf"), 0.5, 1.5, 100),
        ("2026-10-20", 1.0, 2.0, 0.5, 1.5, 200),
    ]))

    bars = get_ohlc_history("AAPL")
    assert len(bars) == 1
    assert bars[0]["timestamp"].startswith("2026-10-20")


@patch("tracker.price_fetcher.yf.Ticker")
def test_a_nan_volume_does_not_discard_a_good_bar(mock_cls):
    """Volume is incidental; prices are what consumers plot."""
    mock_cls.return_value = _ticker(_frame([
        ("2026-10-20", 1.0, 2.0, 0.5, 1.5, float("nan")),
    ]))

    bars = get_ohlc_history("AAPL")
    assert len(bars) == 1
    assert bars[0]["volume"] == 0
    assert bars[0]["close"] == 1.5


@patch("tracker.price_fetcher.yf.Ticker")
def test_all_bars_valid_is_unchanged(mock_cls):
    """The common path must keep every row and round to 4dp."""
    mock_cls.return_value = _ticker(_frame([
        ("2026-10-19", 1.23456, 2.0, 0.5, 1.5, 10),
        ("2026-10-20", 2.0, 3.0, 1.0, 2.5, 20),
    ]))

    bars = get_ohlc_history("AAPL")
    assert len(bars) == 2
    assert bars[0]["open"] == 1.2346


@patch("tracker.price_fetcher.yf.Ticker")
def test_empty_frame_returns_empty_list(mock_cls):
    mock_cls.return_value = _ticker(pd.DataFrame())
    assert get_ohlc_history("AAPL") == []


@patch("tracker.price_fetcher.yf.Ticker", side_effect=Exception("boom"))
def test_failure_returns_empty_list(_mock_cls):
    assert get_ohlc_history("AAPL") == []


# --------------------------------------------------------------------------- #
# _num: the output guard
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_num_rejects_non_finite(bad):
    assert _num(bad) is None


@pytest.mark.parametrize("value,expected", [
    (1.234, 1.23),
    ("2.5", 2.5),
    (3, 3.0),
    (None, None),
    ("not a number", None),
    ([], None),
])
def test_num_coerces_or_gives_up(value, expected):
    assert _num(value) == expected


def test_num_honours_digits():
    assert _num(1.23456789, 6) == 1.234568


def test_num_keeps_zero_distinct_from_none():
    """0.0 is a real value; callers decide whether to treat it as missing."""
    assert _num(0.0) == 0.0
    assert math.isfinite(_num(0.0))
