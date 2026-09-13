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
    for path in ("/screener", "/correlation", "/macro"):
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
