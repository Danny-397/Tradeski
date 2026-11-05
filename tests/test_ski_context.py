"""Tests for the chart snapshot Ski is given, and for what its prompt claims.

The chart snapshot arrives from the browser, so it is checked both for
correct wording (MACD crossovers) and for not crashing on bad values.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "Plotly dashboard")]

import app  # noqa: E402

fmt = app._format_chart_context


def _macd_line(**ctx):
    text = fmt({"symbol": "AAPL", "timeframe": "1D", **ctx})
    return next(line for line in text.splitlines() if "MACD" in line)


def test_crossover_only_when_histogram_changes_sign():
    line = _macd_line(macd=1.2, macd_signal=1.0, macd_histogram=0.2, macd_histogram_prev=-0.1)
    assert "bullish crossover" in line

    line = _macd_line(macd=0.8, macd_signal=1.0, macd_histogram=-0.2, macd_histogram_prev=0.1)
    assert "bearish crossover" in line


def test_macd_above_signal_is_not_called_a_crossover():
    # The old wording called every positive histogram a "bullish crossover".
    line = _macd_line(macd=1.2, macd_signal=1.0, macd_histogram=0.2, macd_histogram_prev=0.15)
    assert "crossover" not in line
    assert "above its signal line" in line


def test_missing_histogram_is_derived_not_called_bearish():
    line = _macd_line(macd=1.2, macd_signal=1.0, macd_histogram=None)
    assert "above its signal line" in line
    assert "bearish" not in line


def test_volatility_is_shown_in_dollars():
    text = fmt({"symbol": "AAPL", "timeframe": "1D", "volatility": 3.456})
    assert "$3.46" in text


def test_malformed_browser_values_are_dropped_not_fatal():
    text = fmt({
        "symbol": "<b>aapl</b>", "timeframe": "1D<script>",
        "close": "190", "rsi": float("nan"), "sma20": True, "zscore": [1],
        "macd": "x", "macd_signal": 1.0,
    })
    assert "AAPL" in text and "<" not in text
    assert "close" not in text.lower()
    assert "RSI" not in text and "SMA" not in text and "Z-Score" not in text
    assert fmt("not a dict") == ""


def test_prompt_no_longer_claims_data_ski_never_receives():
    prompt = app._SKI_SYSTEM_PROMPT
    assert "alert functionality" not in prompt
    assert "Stochastic" not in prompt
    assert "does NOT feed you any of these readings" in prompt
