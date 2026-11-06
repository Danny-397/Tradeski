"""Alerts fire: evaluation against price history, persistence, and the /alerts API.

Until this was added, alerts were stored and listed but nothing ever checked
them; these tests are the proof that one now does.
"""

import datetime as dt
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "Plotly dashboard")]

import tracker.database as db  # noqa: E402
from tracker import alert_eval as ae, auth  # noqa: E402

NY = ae.MARKET_TZ


def hourly(start: str, closes, highs=None, lows=None, volumes=None):
    """Hourly bars from a New York local start time, e.g. "2026-11-02T10:00"."""
    t0 = dt.datetime.fromisoformat(start)
    out = []
    for i, c in enumerate(closes):
        out.append({"timestamp": (t0 + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S"),
                    "open": c, "close": c,
                    "high": highs[i] if highs else c, "low": lows[i] if lows else c,
                    "volume": volumes[i] if volumes else 1000})
    return out


def daily(start: str, closes, volumes=None):
    d0 = dt.date.fromisoformat(start)
    return [{"timestamp": f"{d0 + dt.timedelta(days=i)}T00:00:00", "open": c, "high": c, "low": c, "close": c,
             "volume": volumes[i] if volumes else 1000} for i, c in enumerate(closes)]


def ny(s: str) -> float:
    return dt.datetime.fromisoformat(s).replace(tzinfo=NY).timestamp()


# ── evaluation ──────────────────────────────────────────────

def test_price_above_fires_on_the_first_bar_whose_high_reaches_it():
    bars = hourly("2026-11-02T10:00", [100, 101, 102, 103], highs=[100, 101, 105, 103])
    hit = ae.evaluate("price_above", "AAPL", 104.0, ny("2026-11-02T09:00"), bars)
    assert hit["triggered_at"] == ny("2026-11-02T12:00")
    assert hit["price"] == 104.0
    assert "AAPL traded at or above $104.00" in hit["message"] and "Nov 02, 12:00 ET" in hit["message"]


def test_bars_before_the_alert_was_created_never_fire_it():
    bars = hourly("2026-11-02T10:00", [100, 90, 100])
    assert ae.evaluate("price_below", "AAPL", 95.0, ny("2026-11-02T11:30"), bars) is None
    # ...but a later dip does.
    later = bars + hourly("2026-11-02T13:00", [94])
    assert ae.evaluate("price_below", "AAPL", 95.0, ny("2026-11-02T11:30"), later)["price"] == 95.0


def test_nothing_fires_when_the_condition_is_never_met():
    bars = hourly("2026-11-02T10:00", [100] * 10)
    assert ae.evaluate("price_above", "AAPL", 150.0, 0, bars) is None
    assert ae.evaluate("price_above", "AAPL", None, 0, bars) is None
    assert ae.evaluate("rsi_overbought", "AAPL", None, 0, daily("2026-01-01", [100] * 40)) is None


def test_daily_bars_open_at_market_open():
    assert ae.bar_start({"timestamp": "2026-11-02T00:00:00"}) == ny("2026-11-02T09:30")


def test_rsi_alerts_use_the_indicator():
    up = daily("2026-01-01", [100 + i for i in range(40)])
    hit = ae.evaluate("rsi_overbought", "NVDA", None, ny("2026-01-20T00:00"), up)
    assert hit and "RSI rose to" in hit["message"]
    down = daily("2026-01-01", [200 - i for i in range(40)])
    assert ae.evaluate("rsi_oversold", "NVDA", None, ny("2026-01-20T00:00"), down)
    assert ae.evaluate("rsi_oversold", "NVDA", None, ny("2026-01-20T00:00"), up) is None


def test_volume_spike_compares_with_the_bars_before_it():
    vols = [1000] * 25 + [2500] + [1000] * 3
    bars = daily("2026-01-01", [100] * 29, volumes=vols)
    hit = ae.evaluate("volume_spike", "TSLA", None, ny("2026-01-02T00:00"), bars)
    assert hit["triggered_at"] == ae.bar_start(bars[25]) and "2.5x" in hit["message"]


def test_volatility_spike_on_a_large_move():
    closes = [100 + (i % 2) * 0.5 for i in range(30)] + [110]
    bars = daily("2026-01-01", closes)
    hit = ae.evaluate("volatility_spike", "SPY", None, ny("2026-01-25T00:00"), bars)
    assert hit and "standard deviations" in hit["message"]


def test_history_request_uses_hourly_bars_while_yahoo_has_them():
    now = 1_800_000_000
    assert ae.history_request("price_above", now - 86400, now) == ("3mo", "60m")
    assert ae.history_request("price_above", now - 90 * 86400, now) == ("1y", "1d")
    assert ae.history_request("rsi_oversold", now - 86400, now) == ("1y", "1d")


# ── persistence ─────────────────────────────────────────────

_TEST_DB = "data/test_alerts.db"


@pytest.fixture
def fresh_db():
    db.DB_PATH = _TEST_DB
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)
    db.init_db()
    yield
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)


def test_marking_triggered_is_scoped_to_the_owner(fresh_db):
    u1 = db.create_user("a1@example.com", "h")
    u2 = db.create_user("a2@example.com", "h")
    aid = db.create_alert("AAPL", "price_above", threshold=200, user_id=u1)
    assert db.mark_alert_triggered(aid, u2, 1.0, 200, "x") is False   # not theirs
    assert db.mark_alert_triggered(aid, u1, 1.0, 200, "fired") is True
    assert db.mark_alert_triggered(aid, u1, 2.0, 200, "again") is False  # fires once
    assert db.get_alerts(u1) == []
    assert db.get_triggered_alerts(u1)[0][-1] == "fired"
    assert db.get_triggered_alerts(u2) == []


# ── the API ─────────────────────────────────────────────────

@pytest.fixture
def api(fresh_db, monkeypatch):
    import app
    from cache import SimpleCache
    monkeypatch.setattr(app, "_cache", SimpleCache())
    monkeypatch.setattr(app.limiter, "enabled", False)
    client = app.app.test_client()
    uid = db.create_user("api@example.com", "h")
    headers = {"Authorization": f"Bearer {auth.generate_token(uid)}"}
    return app, client, headers, uid


def test_alert_that_crossed_while_the_server_slept_fires_on_the_next_load(api, monkeypatch):
    app, client, headers, uid = api
    assert client.post("/alerts", json={"symbol": "AAPL", "alert_type": "price_below", "threshold": 95},
                       headers=headers).status_code == 200
    # Hourly bars starting after the alert was created; one dips through the level.
    start = dt.datetime.now(NY).replace(minute=0, second=0, microsecond=0, tzinfo=None) + dt.timedelta(hours=1)
    bars = hourly(start.isoformat(), [100, 96, 93, 97])
    monkeypatch.setattr(app, "get_ohlc_history", lambda s, p, i: bars if (s, i) == ("AAPL", "60m") else [])

    body = client.get("/alerts", headers=headers).get_json()
    assert body["active"] == []
    (aid, sym, typ, thr, when, price, message), = body["triggered"]
    assert sym == "AAPL" and price == 95 and "at or below $95.00" in message


def test_alert_that_has_not_crossed_stays_active(api, monkeypatch):
    app, client, headers, uid = api
    client.post("/alerts", json={"symbol": "AAPL", "alert_type": "price_above", "threshold": 500}, headers=headers)
    monkeypatch.setattr(app, "get_ohlc_history", lambda s, p, i: hourly("2030-01-01T10:00", [100, 101]))
    body = client.get("/alerts", headers=headers).get_json()
    assert len(body["active"]) == 1 and body["triggered"] == []


def test_price_alert_needs_a_positive_threshold(api):
    _app, client, headers, _uid = api
    for bad in (None, 0, -5):
        r = client.post("/alerts", json={"symbol": "AAPL", "alert_type": "price_above", "threshold": bad},
                        headers=headers)
        assert r.status_code == 400
    r = client.post("/alerts", json={"symbol": "AAPL", "alert_type": "rsi_oversold"}, headers=headers)
    assert r.status_code == 200  # indicator alerts need no price


def test_active_alerts_are_capped(api):
    app, client, headers, _uid = api
    for _ in range(app.MAX_ACTIVE_ALERTS):
        client.post("/alerts", json={"symbol": "AAPL", "alert_type": "rsi_oversold"}, headers=headers)
    r = client.post("/alerts", json={"symbol": "AAPL", "alert_type": "rsi_oversold"}, headers=headers)
    assert r.status_code == 400


def test_no_alert_is_ever_broadcast_to_every_visitor():
    with open(os.path.join(ROOT, "Plotly dashboard", "app.py"), encoding="utf-8") as fh:
        source = fh.read()
    assert '"alert_triggered"' not in source and "def broadcast_alert" not in source
