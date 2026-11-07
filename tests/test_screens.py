"""Saved screener setups: validation, storage and the /screens API."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "Plotly dashboard")]

import tracker.database as db  # noqa: E402
from tracker import auth, screens  # noqa: E402

_TEST_DB = "data/test_screens.db"


def screen(name="Oversold large caps", **kw):
    s = {"name": name,
         "filters": {"ranges": {"market_cap": [10, None], "rsi": [None, 30]},
                     "selects": {}, "earnings": "", "search": ""},
         "sort": {"col": "market_cap", "dir": -1}, "view": "technical",
         "seen": ["MSFT", "AAPL"], "seen_at": "2026-11-06"}
    s.update(kw)
    return s


# ── validation ──────────────────────────────────────────────

def test_a_valid_screen_round_trips_with_tidied_fields():
    out = screens.clean_screen(screen(name="  Oversold  ", seen=["MSFT", "AAPL", "MSFT"]))
    assert out["name"] == "Oversold"
    assert out["filters"]["ranges"] == {"market_cap": [10.0, None], "rsi": [None, 30.0]}
    assert out["seen"] == ["AAPL", "MSFT"]          # de-duplicated and sorted
    assert out["sort"] == {"col": "market_cap", "dir": -1} and out["view"] == "technical"


def test_empty_bounds_and_selects_are_dropped():
    out = screens.clean_screen(screen(filters={"ranges": {"pe": [None, None]}, "selects": {"sector": ""}}))
    assert out["filters"] == {"ranges": {}, "selects": {}, "earnings": "", "search": ""}


def test_a_new_screen_has_no_seen_list_until_it_is_looked_at():
    out = screens.clean_screen(screen(seen=None, seen_at=None))
    assert out["seen"] is None and out["seen_at"] is None


@pytest.mark.parametrize("bad", [
    screen(name=""),
    screen(name=5),
    screen(filters={"ranges": {"pe; drop": [1, 2]}}),
    screen(filters={"ranges": {"pe": [1]}}),
    screen(filters={"ranges": {"pe": ["10", None]}}),
    screen(filters={"ranges": {"pe": [float("nan"), None]}}),
    screen(filters={"earnings": "tomorrow"}),
    screen(filters={"selects": {"sector": "x" * 81}}),
    screen(seen=["<script>"]),
    screen(seen=["A"] * (screens.MAX_SEEN + 1)),
    screen(seen_at="yesterday"),
    screen(sort={"col": "pe desc", "dir": 1}),
])
def test_bad_screens_are_rejected(bad):
    with pytest.raises(ValueError):
        screens.clean_screen(bad)


def test_list_limits_and_unique_names():
    with pytest.raises(ValueError):
        screens.clean_screens([screen(name=f"s{i}") for i in range(screens.MAX_SCREENS + 1)])
    with pytest.raises(ValueError):
        screens.clean_screens([screen(name="Value"), screen(name="value")])
    with pytest.raises(ValueError):
        screens.clean_screens({"name": "not a list"})
    assert len(screens.clean_screens([screen(name="a"), screen(name="b")])) == 2


# ── storage and API ─────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    db.DB_PATH = _TEST_DB
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)
    db.init_db()
    import app
    monkeypatch.setattr(app.limiter, "enabled", False)
    client = app.app.test_client()
    u1 = db.create_user("s1@example.com", "h")
    u2 = db.create_user("s2@example.com", "h")
    yield client, {"Authorization": f"Bearer {auth.generate_token(u1)}"}, \
        {"Authorization": f"Bearer {auth.generate_token(u2)}"}
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)


def test_screens_need_sign_in(api):
    client, _, _ = api
    assert client.get("/screens").status_code == 401
    assert client.put("/screens", json={"screens": []}).status_code == 401


def test_save_list_and_replace_screens_per_user(api):
    client, h1, h2 = api
    assert client.get("/screens", headers=h1).get_json() == {"screens": []}
    r = client.put("/screens", json={"screens": [screen(), screen(name="Value")]}, headers=h1)
    assert r.status_code == 200
    got = client.get("/screens", headers=h1).get_json()["screens"]
    assert [s["name"] for s in got] == ["Oversold large caps", "Value"]
    assert client.get("/screens", headers=h2).get_json() == {"screens": []}   # not shared

    client.put("/screens", json={"screens": [screen(name="Value", seen=["XOM"])]}, headers=h1)
    got = client.get("/screens", headers=h1).get_json()["screens"]
    assert len(got) == 1 and got[0]["seen"] == ["XOM"]


def test_invalid_payload_is_refused_and_nothing_changes(api):
    client, h1, _ = api
    client.put("/screens", json={"screens": [screen()]}, headers=h1)
    r = client.put("/screens", json={"screens": [screen(name="")]}, headers=h1)
    assert r.status_code == 400 and "name" in r.get_json()["error"]
    assert len(client.get("/screens", headers=h1).get_json()["screens"]) == 1


def test_unreadable_stored_data_reads_as_empty(api):
    client, h1, _ = api
    uid = auth.verify_token(h1["Authorization"].split()[1])
    db.set_saved_screens(uid, "{not json")
    assert client.get("/screens", headers=h1).get_json() == {"screens": []}
