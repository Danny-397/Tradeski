"""Guards for the ticker-search index (frontend/symbols.js).

The symbol box suggests from a static list; these catch the list going
missing, loading too late, or carrying symbols the price API rejects.
"""
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")


def _read(name):
    with open(os.path.join(FRONTEND, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def symbols():
    m = re.search(r"window\.TRADESKI_SYMBOLS\s*=\s*(\[.*\]);\s*$", _read("symbols.js"), re.S)
    assert m, "symbols.js does not assign window.TRADESKI_SYMBOLS"
    return json.loads(m.group(1))


def test_symbols_load_before_dashboard():
    srcs = [os.path.basename(s) for s in
            re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", _read("index.html"))]
    assert "symbols.js" in srcs
    assert srcs.index("symbols.js") < srcs.index("dashboard.js")


def test_symbols_are_unique_pairs(symbols):
    assert len(symbols) > 400
    assert all(isinstance(p, list) and len(p) == 2 and p[0] and p[1] for p in symbols)
    syms = [p[0] for p in symbols]
    assert len(syms) == len(set(syms)), "duplicate symbols"


def test_symbols_use_the_api_spelling(symbols):
    """The price API answers BRK-B but not BRK.B."""
    bad = [s for s, _ in symbols if not re.fullmatch(r"[A-Z0-9-]{1,10}", s)]
    assert not bad, "symbols the API will not accept: %s" % bad[:10]


def test_ticker_strip_symbols_are_searchable(symbols):
    have = {s for s, _ in symbols}
    for s in ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SOFI", "RDW", "GOOGL", "META", "SPY", "QQQ"]:
        assert s in have, s
