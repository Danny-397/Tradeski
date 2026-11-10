"""Guards for the frontend's offline demo mode.

The dashboard is a static client: when the API host is unreachable it falls back
to a recorded snapshot of real responses (frontend/demo-mode.js +
frontend/demo-snapshot.js) rather than rendering raw fetch failures.

These tests do not exercise the browser. They check the things that silently
break the fallback: the snapshot going missing, losing its shape, or the wrapper
being loaded after the code it is supposed to wrap.
"""
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")

SNAPSHOT_JS = os.path.join(FRONTEND, "demo-snapshot.js")
DEMO_JS = os.path.join(FRONTEND, "demo-mode.js")
INDEX_HTML = os.path.join(FRONTEND, "index.html")

# Symbols the dashboard's ticker strip requests on load.
TICKER_SYMS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SOFI", "RDW", "GOOGL", "META", "SPY", "QQQ"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def snapshot():
    """Parse the generated snapshot file back into a dict."""
    raw = _read(SNAPSHOT_JS)
    m = re.search(r"window\.TRADESKI_SNAPSHOT\s*=\s*(\{.*\});\s*$", raw, re.S)
    assert m, "demo-snapshot.js does not assign window.TRADESKI_SNAPSHOT"
    return json.loads(m.group(1))


def test_demo_mode_files_exist():
    for path in (DEMO_JS, SNAPSHOT_JS):
        assert os.path.exists(path), "missing %s" % os.path.basename(path)


def test_demo_mode_loads_before_dashboard():
    """The fetch wrapper is useless if dashboard.js has already called fetch."""
    html = _read(INDEX_HTML)
    # Match real script tags only — prose in a comment must not count as a load.
    srcs = re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", html)
    names = [os.path.basename(s) for s in srcs]
    assert "demo-mode.js" in names, "index.html does not load demo-mode.js"
    assert "dashboard.js" in names, "index.html does not load dashboard.js"
    assert names.index("demo-mode.js") < names.index("dashboard.js"), \
        "demo-mode.js must be loaded before dashboard.js"


def test_snapshot_has_metadata(snapshot):
    assert snapshot.get("capturedAt"), "snapshot has no capture timestamp"
    assert snapshot.get("defaultSymbol") in TICKER_SYMS
    assert isinstance(snapshot.get("endpoints"), dict)


def test_iv_history_merge_replaces_a_rerun_of_the_same_day():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import capture_snapshot as cap
    h = cap.merge_iv({}, "2026-11-05", {"AAPL": {"iv": 0.2512345, "dte": 28}})
    h = cap.merge_iv(h, "2026-11-06", {"AAPL": {"iv": 0.26, "dte": 27}, "SPY": {"iv": 0.14, "dte": 27}})
    h = cap.merge_iv(h, "2026-11-06", {"AAPL": {"iv": 0.27, "dte": 27}})
    assert h["symbols"]["AAPL"] == [["2026-11-05", 0.2512, 28], ["2026-11-06", 0.27, 27]]
    assert h["symbols"]["SPY"] == [["2026-11-06", 0.14, 27]]
    assert h["updated"] == "2026-11-06"
    assert cap.nearest_expiry([{"date": "a", "dte": 7}, {"date": "b", "dte": 35}], 30) == "b"
    assert cap.nearest_expiry([], 30) is None


def test_snapshot_covers_every_ticker_symbol(snapshot):
    """A gap here shows up as a blank cell in the ticker strip."""
    eps = snapshot["endpoints"]
    missing = [s for s in TICKER_SYMS if "/stats?symbol=%s" % s not in eps]
    assert not missing, "no snapshot stats for: %s" % ", ".join(missing)


def test_snapshot_covers_default_chart_timeframes(snapshot):
    eps = snapshot["endpoints"]
    sym = snapshot["defaultSymbol"]
    missing = [
        tf for tf in ("1D", "5D", "1M", "3M", "6M", "1Y")
        if "/price_history?symbol=%s&tf=%s" % (sym, tf) not in eps
    ]
    assert not missing, "no snapshot price history for %s at: %s" % (sym, ", ".join(missing))


def test_snapshot_panels_present(snapshot):
    for path in ("/screener", "/macro"):
        assert path in snapshot["endpoints"], "snapshot missing %s" % path


def test_snapshot_stats_have_the_fields_the_ticker_reads(snapshot):
    stats = snapshot["endpoints"]["/stats?symbol=AAPL"]
    for key in ("close", "change_pct", "open", "high", "low"):
        assert key in stats, "stats snapshot missing %r" % key
        assert isinstance(stats[key], (int, float))


def test_snapshot_price_history_series_align(snapshot):
    """Chart traces are zipped together, so unequal lengths render garbage."""
    hist = snapshot["endpoints"]["/price_history?symbol=AAPL&tf=1D"]
    lengths = {k: len(v) for k, v in hist.items() if isinstance(v, list)}
    assert lengths, "price history snapshot has no series"
    assert len(set(lengths.values())) == 1, "series lengths disagree: %s" % lengths


def test_macro_snapshot_shape_matches_backend(snapshot):
    """Same keys tracker.fred.get_macro_snapshot emits, so the strip renders."""
    macro = snapshot["endpoints"]["/macro"]
    assert macro, "macro snapshot is empty"
    for series_id, entry in macro.items():
        for key in ("label", "unit", "description", "value", "prev_value", "date", "trend"):
            assert key in entry, "macro %s missing %r" % (series_id, key)
        assert entry["trend"] in ("up", "down", "neutral")


def test_demo_mode_never_fakes_a_write():
    """Falling back on POST/DELETE would invent successful writes."""
    js = _read(DEMO_JS)
    assert 'method !== "GET"' in js, "demo-mode.js no longer restricts fallback to GET"


def test_demo_mode_passes_through_real_responses():
    """A 401/404/429 is real state and must reach the caller untouched."""
    js = _read(DEMO_JS)
    assert "res.status < 500" in js, "demo-mode.js no longer passes non-5xx responses through"


def _eod(symbol, spot=100.0):
    rows = [{"strike": k, "bid": 1.0, "ask": 1.2, "lastPrice": 1.1, "volume": 5.0, "openInterest": 50.0,
             "impliedVolatility": 0.3} for k in (70.0, 85.0, 100.0, 115.0, 130.0)]
    return {"symbol": symbol, "captured_at": "2026-11-07T01:14:00+00:00", "spot": spot, "dividend_yield": 0.01,
            "chains": {"2026-12-18": {"calls": rows, "puts": rows}}}


def test_archive_keeps_strikes_near_the_spot_and_the_quotes():
    sys.path.insert(0, ROOT)
    from tracker import options as opt
    a = opt.archive_entry(_eod("AAPL"))
    assert [r[0] for r in a["expiries"]["2026-12-18"]["calls"]] == [85.0, 100.0, 115.0]   # within 20%
    assert a["expiries"]["2026-12-18"]["puts"][0] == [85.0, 1.0, 1.2, 5.0, 50.0]
    assert a["spot"] == 100.0 and a["dividend_yield"] == 0.01


def test_archive_is_dated_by_the_us_trading_day():
    sys.path.insert(0, ROOT)
    from tracker import options as opt
    # A run GitHub started late, past midnight UTC, still belongs to the day before in New York.
    assert opt.archive_day([_eod("AAPL")], "2026-11-07T01:14:00+00:00")["date"] == "2026-11-06"
    assert opt.archive_day([_eod("AAPL")], "2026-11-09T21:40:00+00:00")["date"] == "2026-11-09"
    day = opt.archive_day([_eod("AAPL"), {"symbol": "X", "chains": {}}], "2026-11-09T21:40:00Z")
    assert set(day["symbols"]) == {"AAPL"}


def test_write_archive_adds_the_day_to_the_index(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    sys.path.insert(0, ROOT)
    import capture_snapshot as cap
    from tracker import options as opt
    monkeypatch.setattr(cap, "ARCHIVE_DIR", str(tmp_path))
    cap.write_archive(opt.archive_day([_eod("AAPL")], "2026-11-09T21:40:00Z"))
    cap.write_archive(opt.archive_day([_eod("AAPL")], "2026-11-06T22:00:00Z"))
    cap.write_archive(opt.archive_day([_eod("AAPL")], "2026-11-09T22:30:00Z"))   # a rerun
    assert json.load(open(tmp_path / "index.json"))["days"] == ["2026-11-06", "2026-11-09"]
    assert json.load(open(tmp_path / "2026-11-09.json"))["captured_at"] == "2026-11-09T22:30:00Z"


def test_the_committed_archive_is_consistent():
    idx = json.load(open(os.path.join(ROOT, "data", "options-archive", "index.json")))
    assert idx["days"] == sorted(idx["days"]) and idx["days"]
    for d in idx["days"]:
        day = json.load(open(os.path.join(ROOT, "data", "options-archive", d + ".json")))
        assert day["date"] == d and day["symbols"]
