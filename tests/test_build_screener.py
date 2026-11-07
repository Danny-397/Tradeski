"""Tests for the screener data build (scripts/build_screener.py). No network."""

import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import build_screener as bs  # noqa: E402

NASDAQ = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N
ZVZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N
ABCDW|ABCD Corp - Warrants|G|N|N|100|N|N
SPAC|Example Acquisition Corp. - Class A Ordinary Shares|G|N|N|100|N|N
File Creation Time: 1107202600:00|||||||"""

OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Class B Common Stock|N|BRK.B|N|100|N|BRK=B
BAC$K|Bank of America Corp 6.45% Preferred|N|BAC$K|N|100|N|BAC-K
UNH|UnitedHealth Group Incorporated Common Stock|N|UNH|N|100|N|UNH
XYZU|XYZ Holdings Units|A|XYZU|N|100|N|XYZU"""


def test_directory_keeps_only_common_stocks():
    assert bs.parse_directory(NASDAQ, "nasdaqlisted") == [("AAPL", "Apple Inc.", "NASDAQ")]
    # Class shares become Yahoo's dash form; preferreds and units go; "United" is not "unit".
    assert bs.parse_directory(OTHER, "otherlisted") == [
        ("BRK-B", "Berkshire Hathaway Inc.", "NYSE"), ("UNH", "UnitedHealth Group Incorporated", "NYSE")]


def _bars(closes, start="2025-11-07", volume=1000):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return [{"date": (d0 + dt.timedelta(days=i)).isoformat(), "open": c, "high": c * 1.01, "low": c * 0.99,
             "close": c, "volume": volume} for i, c in enumerate(closes)]


def test_technicals_from_a_steady_uptrend():
    closes = [100 * 1.001 ** i for i in range(260)]
    bars = _bars(closes)
    bars[-1]["volume"] = 3000
    t = bs.technicals(bars, {b["date"]: b["close"] for b in bars})
    assert t["price"] == pytest.approx(closes[-1], abs=0.01)
    assert t["change"] == pytest.approx(0.1, abs=0.01)
    assert t["perf_1m"] == pytest.approx((1.001 ** 21 - 1) * 100, abs=0.01)
    assert t["perf_1y"] == pytest.approx((1.001 ** 251 - 1) * 100, abs=0.01)
    assert t["from_high"] == 0 and t["from_low"] > 0
    assert t["rsi"] == 100.0                                   # never a down day
    assert t["sma20"] > 0 and t["sma200"] > t["sma50"] > 0
    assert t["beta"] == pytest.approx(1.0, abs=1e-6)           # against itself
    assert t["rel_volume"] == pytest.approx(3000 / ((62 * 1000 + 3000) / 63), abs=0.01)


def test_technicals_refuse_short_histories_and_skip_missing_long_windows():
    assert bs.technicals(_bars([10.0] * 10)) is None
    t = bs.technicals(_bars([10.0 + i * 0.1 for i in range(60)]))
    assert t["sma200"] is None and t["perf_1y"] is None and t["perf_6m"] is None
    assert t["beta"] is None                                    # no benchmark given


def test_rsi_matches_the_dashboards_own_rsi():
    # The screener's RSI must agree with the one the chart sidebar shows (tracker/analyzer.py).
    sys.path.insert(0, ROOT)
    from tracker.analyzer import rsi
    closes = [100 + 10 * math.sin(i / 5) + i * 0.05 for i in range(120)]
    assert bs._rsi(closes) == pytest.approx(rsi(closes)[-1], abs=1e-9)


def test_fundamentals_and_price_derived_ratios():
    info = {"sharesOutstanding": 1_000_000, "trailingEps": 5.0, "forwardEps": 6.0, "totalRevenue": 50_000_000,
            "bookValue": 20.0, "dividendRate": 2.0, "profitMargins": 0.25, "debtToEquity": 84.0,
            "targetMeanPrice": 120.0, "earningsTimestamp": 1795000000, "shortName": "Example",
            "recommendationMean": 1.9}
    fund = bs.fundamentals_from_info(info, "2026-11-07")
    assert fund["profit_margin"] == 25.0 and fund["debt_equity"] == 0.84
    assert fund["earnings_date"] == "2026-11-18"
    d = bs.derive({"price": 100.0}, fund)
    assert d == {"market_cap": 100_000_000, "pe": 20.0, "forward_pe": 16.67, "ps": 2.0, "pb": 5.0,
                 "dividend_yield": 2.0, "upside": 20.0}
    # A loss-making company has no P/E (not a negative one).
    assert bs.derive({"price": 100.0}, {**fund, "eps": -1.0})["pe"] is None
    assert bs.fundamentals_from_info({}, "2026-11-07") is None


def test_row_follows_the_field_order_and_prefers_yahoo_names():
    tech = bs.technicals(_bars([50.0 + math.sin(i) for i in range(260)]))
    tech.pop("last_date")
    row = bs.build_row("EX", "Example Inc.", "NYSE", tech, {"name": "Example", "sector": "Industrials", "shares": 10})
    assert len(row) == len(bs.FIELDS)
    rec = dict(zip(bs.FIELDS, row))
    assert rec["symbol"] == "EX" and rec["name"] == "Example" and rec["sector"] == "Industrials"
    assert rec["market_cap"] == int(rec["price"] * 10)
    assert dict(zip(bs.FIELDS, bs.build_row("EX", "Example Inc.", "NYSE", tech, None)))["name"] == "Example Inc."


def _info(sym):
    return {"sharesOutstanding": 100, "trailingEps": 1.0, "shortName": sym}


def test_fundamentals_keep_going_when_some_companies_lack_data():
    # Companies without data are not refusals: no back-off, everything else fetched.
    info = lambda s: {} if s.startswith("N") else _info(s)  # noqa: E731
    out = bs.fetch_fundamentals(["A", "N1", "B", "N2"], "2026-11-07", info_fn=info, chunk=2, pause=0)
    assert sorted(out) == ["A", "B"]


def test_fundamentals_back_off_then_stop_when_refused():
    calls = []

    def refusing(sym):
        calls.append(sym)
        raise RuntimeError("401 Invalid Crumb")

    out = bs.fetch_fundamentals([f"S{i}" for i in range(10)], "2026-11-07", info_fn=refusing, chunk=2, pause=0)
    assert out == {}
    assert len(calls) == 4          # two refused chunks, then it stops asking


def test_fundamentals_recover_after_one_refused_chunk():
    state = {"n": 0}

    def flaky(sym):
        state["n"] += 1
        if state["n"] <= 2:
            raise RuntimeError("429")
        return _info(sym)

    out = bs.fetch_fundamentals(["A", "B", "C", "D"], "2026-11-07", info_fn=flaky, chunk=2, pause=0)
    assert sorted(out) == ["C", "D"]


def test_refresh_order_fetches_missing_then_stalest_big_names_first():
    prev = {"OLD": {"fundamentals_date": "2026-11-01"}, "NEW": {"fundamentals_date": "2026-11-06"}}
    assert bs.refresh_order(["NEW", "OLD", "NONE"], prev) == ["NONE", "OLD", "NEW"]
    # Among never-fetched stocks, the dashboard's index (large caps) goes first.
    assert bs.refresh_order(["AAAA", "MSFT", "ZZZZ", "NVDA"], {}, frozenset({"MSFT", "NVDA"})) == \
        ["MSFT", "NVDA", "AAAA", "ZZZZ"]
    assert {"AAPL", "MSFT", "NVDA"} <= bs.priority_symbols()


def test_screener_earnings_date_is_the_next_one_not_the_last():
    import datetime as dt
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=40)).timestamp()
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5)).timestamp()
    fund = bs.fundamentals_from_info({"sharesOutstanding": 1, "earningsTimestamp": past,
                                      "earningsTimestampStart": future}, "2026-11-07")
    assert fund["earnings_date"] == dt.datetime.fromtimestamp(future, dt.timezone.utc).date().isoformat()
    only_past = bs.fundamentals_from_info({"sharesOutstanding": 1, "earningsTimestamp": past}, "2026-11-07")
    assert only_past["earnings_date"] is None
