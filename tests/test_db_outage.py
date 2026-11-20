"""The server keeps answering when the database is down, and prices come from memory."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "Plotly dashboard"))

import app  # noqa: E402


def test_health_reports_a_database_outage(monkeypatch):
    monkeypatch.setattr(app, "_db_error", "Your account or project has exceeded the quota.")
    body = app.app.test_client().get("/health").get_json()
    assert body["status"] == "degraded"
    assert "quota" in body["db_error"]


def test_health_ok_with_the_database(monkeypatch):
    monkeypatch.setattr(app, "_db_error", None)
    body = app.app.test_client().get("/health").get_json()
    assert body["status"] == "ok" and "db_error" not in body


def test_latest_prices_keep_the_last_two_ticks(monkeypatch):
    monkeypatch.setattr(app, "_latest_prices", {})
    for p in (10.0, 11.0, 12.0):
        app._remember_price("AAPL", p)
    assert [t[1] for t in app._latest_prices["AAPL"]] == [11.0, 12.0]


def test_holding_uses_the_newest_price(monkeypatch):
    monkeypatch.setattr(app, "_latest_prices", {})
    app._remember_price("AAPL", 100.0)
    app._remember_price("AAPL", 110.0)
    monkeypatch.setattr(app, "get_stock_price", lambda s: (_ for _ in ()).throw(AssertionError("not needed")))
    h = app._enrich_holding({"symbol": "AAPL", "shares": 2, "avg_cost": 100.0})
    assert h["market_value"] == 220.0
