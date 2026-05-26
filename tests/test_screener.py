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
