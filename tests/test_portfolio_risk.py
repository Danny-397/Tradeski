"""Portfolio risk: the Sharpe ratio uses the current fed funds rate, not a constant."""

import datetime
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "Plotly dashboard")]

import app  # noqa: E402
from cache import SimpleCache  # noqa: E402


def snapshot(fed_funds):
    return {"FEDFUNDS": {"value": fed_funds}}


def bars(daily, phase=0.0):
    day, price, out = datetime.date(2025, 1, 1), 100.0, []
    for i in range(252):
        price *= 1 + daily + 0.01 * math.sin(i / 3 + phase)
        out.append({"timestamp": f"{day + datetime.timedelta(days=i)}T00:00:00", "close": price})
    return out


def test_risk_free_rate_comes_from_fed_funds(monkeypatch):
    monkeypatch.setattr(app, "_cache", SimpleCache())
    app._cache.set("macro_snapshot", snapshot(3.88), ttl=60)
    assert app._risk_free_rate() == (0.0388, "fed_funds")


def test_risk_free_rate_falls_back_when_fred_is_missing_or_nonsense(monkeypatch):
    monkeypatch.setattr(app, "_cache", SimpleCache())
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert app._risk_free_rate() == (app.DEFAULT_RISK_FREE, "default")
    for bad in (None, float("nan"), -1, 400):
        app._cache.set("macro_snapshot", snapshot(bad), ttl=60)
        assert app._risk_free_rate() == (app.DEFAULT_RISK_FREE, "default")


def test_sharpe_moves_with_the_rate_and_reports_it(monkeypatch):
    monkeypatch.setattr(app, "_cache", SimpleCache())
    series = {"AAPL": bars(0.001), "SPY": bars(0.0005, phase=1.0)}
    monkeypatch.setattr(app, "get_ohlc_history", lambda s, p, i: series.get(s, []))
    holdings = [{"symbol": "AAPL", "market_value": 1000.0}]

    app._cache.set("macro_snapshot", snapshot(1.0), ttl=60)
    low, _ = app._compute_portfolio_risk(holdings)
    app._cache.set("macro_snapshot", snapshot(5.0), ttl=60)
    high, _ = app._compute_portfolio_risk(holdings)

    assert low["risk_free_pct"] == 1.0 and high["risk_free_pct"] == 5.0
    assert low["risk_free_source"] == "fed_funds"
    assert high["sharpe"] < low["sharpe"]  # a higher hurdle lowers excess return
    assert low["beta"] == high["beta"] and low["volatility"] == high["volatility"]


def test_price_history_no_longer_sends_an_unshown_prediction():
    with open(os.path.join(ROOT, "Plotly dashboard", "app.py"), encoding="utf-8") as fh:
        assert '"prediction"' not in fh.read()
