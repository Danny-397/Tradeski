"""Inputs the browser never sends are still refused, and the cache cannot grow without bound."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "Plotly dashboard"))

import app  # noqa: E402
from cache import SimpleCache  # noqa: E402


def test_portfolio_refuses_nan_and_infinity(monkeypatch):
    stored = []
    monkeypatch.setattr(app.database, "upsert_holding", lambda *a: stored.append(a) or 1)
    client = app.app.test_client()
    headers = {"Authorization": f"Bearer {app.auth.generate_token(1)}", "Content-Type": "application/json"}
    for body in ('{"symbol": "AAPL", "shares": NaN}',
                 '{"symbol": "AAPL", "shares": Infinity}',
                 '{"symbol": "AAPL", "shares": 1, "avg_cost": NaN}'):
        assert client.post("/portfolio", data=body, headers=headers).status_code == 400, body
    assert stored == []
    assert client.post("/portfolio", data='{"symbol": "AAPL", "shares": 2.5, "avg_cost": 180}',
                       headers=headers).status_code == 200
    assert stored == [(1, "AAPL", 2.5, 180.0)]


def test_cache_drops_expired_entries_once_full(monkeypatch):
    monkeypatch.setattr(SimpleCache, "MAX_ENTRIES", 3)
    c = SimpleCache()
    for key in ("a", "b", "c"):
        c.set(key, 1, ttl=-1)          # already expired, never read again
    c.set("fresh", 2, ttl=60)
    assert set(c.store) == {"fresh"} and c.get("fresh") == 2
