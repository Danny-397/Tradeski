"""Tests for get_screener_data() in tracker/price_fetcher.py."""

from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from tracker.price_fetcher import get_screener_data


def _mock_ticker(info_dict):
    ticker = MagicMock()
    type(ticker).info = PropertyMock(return_value=info_dict)
    return ticker


@patch("tracker.price_fetcher.yf.Ticker")
def test_returns_expected_fields(mock_ticker_cls):
    mock_ticker_cls.return_value = _mock_ticker({
        "currentPrice":      182.50,
        "trailingPE":        29.4,
        "marketCap":         2_800_000_000_000,
        "sector":            "Technology",
        "fiftyTwoWeekHigh":  199.62,
        "fiftyTwoWeekLow":   124.17,
        "52WeekChange":      0.235,
        "shortName":         "Apple Inc.",
    })
    result = get_screener_data("AAPL")

    assert result is not None
    assert result["symbol"]     == "AAPL"
    assert result["name"]       == "Apple Inc."
    assert result["price"]      == 182.50
    assert result["pe"]         == 29.4
    assert result["market_cap"] == 2_800_000_000_000
    assert result["sector"]     == "Technology"
    assert result["high_52w"]   == 199.62
    assert result["low_52w"]    == 124.17
    assert result["perf_52w"]   == pytest.approx(23.5, abs=0.01)


@patch("tracker.price_fetcher.yf.Ticker")
def test_returns_none_when_no_price(mock_ticker_cls):
    mock_ticker_cls.return_value = _mock_ticker({
        "currentPrice": None,
        "regularMarketPrice": None,
        "previousClose": None,
    })
    assert get_screener_data("FAKE") is None


@patch("tracker.price_fetcher.yf.Ticker")
def test_returns_none_on_exception(mock_ticker_cls):
    mock_ticker_cls.side_effect = Exception("Network error")
    assert get_screener_data("AAPL") is None


@patch("tracker.price_fetcher.yf.Ticker")
def test_uses_forward_pe_when_trailing_missing(mock_ticker_cls):
    mock_ticker_cls.return_value = _mock_ticker({
        "currentPrice":  300.0,
        "trailingPE":    None,
        "forwardPE":     22.5,
        "sector":        "Technology",
        "shortName":     "Some Corp",
    })
    result = get_screener_data("SOME")
    assert result is not None
    assert result["pe"] == 22.5


@patch("tracker.price_fetcher.yf.Ticker")
def test_etf_gets_etf_sector(mock_ticker_cls):
    mock_ticker_cls.return_value = _mock_ticker({
        "currentPrice": 450.0,
        "sector":       None,
        "quoteType":    "ETF",
        "shortName":    "SPDR S&P 500",
    })
    result = get_screener_data("SPY")
    assert result is not None
    assert result["sector"] == "ETF"


@patch("tracker.price_fetcher.yf.Ticker")
def test_missing_optional_fields_return_none(mock_ticker_cls):
    mock_ticker_cls.return_value = _mock_ticker({
        "currentPrice": 55.0,
        "shortName":    "Minimal Corp",
    })
    result = get_screener_data("MIN")
    assert result is not None
    assert result["pe"]        is None
    assert result["market_cap"] is None
    assert result["high_52w"]  is None
    assert result["low_52w"]   is None
    assert result["perf_52w"]  is None


@patch("tracker.price_fetcher.yf.Ticker")
def test_perf_52w_converted_to_percent(mock_ticker_cls):
    """52WeekChange from yfinance is a decimal — should be multiplied by 100."""
    mock_ticker_cls.return_value = _mock_ticker({
        "currentPrice":  100.0,
        "52WeekChange":  0.50,
        "shortName":     "Half Up Corp",
    })
    result = get_screener_data("HUC")
    assert result is not None
    assert result["perf_52w"] == pytest.approx(50.0, abs=0.01)


@patch("tracker.price_fetcher.yf.Ticker")
def test_uses_previous_close_fallback(mock_ticker_cls):
    mock_ticker_cls.return_value = _mock_ticker({
        "currentPrice":       None,
        "regularMarketPrice": None,
        "previousClose":      175.0,
        "shortName":          "Fallback Corp",
    })
    result = get_screener_data("FBC")
    assert result is not None
    assert result["price"] == 175.0


# --------------------------------------------------------------------------- #
# Falling back to the chart endpoint when .info is unavailable
#
# Yahoo blocks the quoteSummary endpoint behind `.info` from some datacenter
# IPs, including Render's. Every universe row then came back None and
# /screener answered 200 with an empty table, so the dashboard looked loaded
# but empty. These pin the fallback that keeps the rows populated.
# --------------------------------------------------------------------------- #
BARS_1Y = (
    [{"timestamp": "2025-10-20T00:00:00", "open": 100.0, "high": 104.0,
      "low": 96.0, "close": 100.0, "volume": 1_000}]
    + [{"timestamp": "2026-04-20T00:00:00", "open": 120.0, "high": 190.0,
        "low": 80.0, "close": 120.0, "volume": 1_000}]
    + [{"timestamp": "2026-10-20T00:00:00", "open": 150.0, "high": 151.0,
        "low": 149.0, "close": 150.0, "volume": 1_000}]
)


@patch("tracker.price_fetcher.get_ohlc_history", return_value=BARS_1Y)
@patch("tracker.price_fetcher._safe_info", return_value={})
def test_falls_back_to_history_when_info_is_empty(_info, _hist):
    """The Render failure mode: .info gives nothing, history still works."""
    result = get_screener_data("AAPL")

    assert result is not None, "an empty .info must not blank the whole row"
    assert result["price"]    == 150.0          # last close
    assert result["high_52w"] == 190.0          # max high over the year
    assert result["low_52w"]  == 80.0           # min low over the year
    assert result["perf_52w"] == pytest.approx(50.0, abs=0.01)  # 100 -> 150
    # No fallback exists for these, so they stay visibly blank.
    assert result["pe"]         is None
    assert result["market_cap"] is None
    assert result["sector"]     == "—"
    assert result["name"]       == "AAPL"


@patch("tracker.price_fetcher.get_ohlc_history", return_value=[])
@patch("tracker.price_fetcher._safe_info", return_value={})
def test_returns_none_when_both_sources_fail(_info, _hist):
    """With no price from either source there is genuinely nothing to show."""
    assert get_screener_data("FAKE") is None


@patch("tracker.price_fetcher.get_ohlc_history", return_value=BARS_1Y)
@patch("tracker.price_fetcher._safe_info")
def test_history_fills_only_the_missing_columns(mock_info, _hist):
    """A partial .info keeps its own values and tops up the rest."""
    mock_info.return_value = {
        "currentPrice": 333.0,
        "trailingPE":   11.0,
        "sector":       "Technology",
        "shortName":    "Partial Corp",
    }
    result = get_screener_data("PC")

    assert result["price"]  == 333.0            # .info wins over last close
    assert result["pe"]     == 11.0
    assert result["sector"] == "Technology"
    assert result["name"]   == "Partial Corp"
    assert result["high_52w"] == 190.0          # filled from bars
    assert result["low_52w"]  == 80.0


@patch("tracker.price_fetcher.get_ohlc_history")
@patch("tracker.price_fetcher._safe_info")
def test_complete_info_skips_the_extra_request(mock_info, mock_hist):
    """A full .info must not trigger a second network call per symbol.

    The screener fans out over 29 symbols, so an unconditional history fetch
    would double the request count for no benefit.
    """
    mock_info.return_value = {
        "currentPrice":     182.5,
        "trailingPE":       29.4,
        "marketCap":        2_800_000_000_000,
        "sector":           "Technology",
        "fiftyTwoWeekHigh": 199.62,
        "fiftyTwoWeekLow":  124.17,
        "52WeekChange":     0.235,
        "shortName":        "Apple Inc.",
    }
    result = get_screener_data("AAPL")

    assert result["price"] == 182.5
    mock_hist.assert_not_called()


@patch("tracker.price_fetcher.yf.Ticker")
def test_safe_info_swallows_errors(mock_ticker_cls):
    """_safe_info is the guard that lets the fallback run at all."""
    from tracker.price_fetcher import _safe_info

    mock_ticker_cls.side_effect = Exception("403 Forbidden")
    assert _safe_info("AAPL") == {}


@patch("tracker.price_fetcher.yf.Ticker")
def test_safe_info_rejects_non_dict(mock_ticker_cls):
    """yfinance has returned None here; .get() on it would raise."""
    ticker = MagicMock()
    type(ticker).info = PropertyMock(return_value=None)
    mock_ticker_cls.return_value = ticker

    from tracker.price_fetcher import _safe_info
    assert _safe_info("AAPL") == {}
