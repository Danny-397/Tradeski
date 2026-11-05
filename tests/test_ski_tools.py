"""Tests for Ski's tools (tracker/ski_tools.py) and the tool loop in app.py.

No network: data sources are fakes, and the Anthropic client is a fake that
replays scripted responses.
"""

import datetime
import json
import math
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "Plotly dashboard")]

import app  # noqa: E402
from tracker import ski_tools as st  # noqa: E402


def make_bars(n=252, start=100.0, daily=0.001, wobble=0.01, phase=0.0):
    """Deterministic daily bars: a drift plus a sine wobble."""
    day = datetime.date(2025, 1, 1)
    bars, price = [], start
    for i in range(n):
        price *= 1 + daily + wobble * math.sin(i / 3 + phase)
        bars.append({"timestamp": f"{day + datetime.timedelta(days=i)}T00:00:00",
                     "open": price, "high": price * 1.01, "low": price * 0.99, "close": price, "volume": 1})
    return bars


def fake_data(holdings=None, bars=None, risk=None):
    bars = bars or {}
    return st.SkiData(
        bars=lambda s, p: bars.get(s, make_bars()) if s != "NOPE" else [],
        fundamentals=lambda s: {"symbol": s, "pe": 30.1, "sector": "Technology"},
        news=lambda s: [{"title": f"{s} beats", "source": "Reuters", "published_at": "2026-11-03T12:00:00Z"}],
        macro_history=lambda sid, n: [{"date": f"2026-{m:02d}-01", "value": "3.1"} for m in range(n, 0, -1)],
        holdings=lambda: list(holdings or []),
        risk=risk or (lambda raw: ({"sharpe": 1.0, "beta": 1.1, "volatility": 20.0}, None)),
    )


# ── calculations ────────────────────────────────────────────

def test_price_summary_returns_match_the_bars():
    bars = make_bars()
    out = st.price_summary("AAPL", bars)
    closes = [b["close"] for b in bars]
    assert out["close"] == round(closes[-1], 2)
    assert out["return_pct"]["1_week"] == round((closes[-1] / closes[-6] - 1) * 100, 1)
    assert out["high_52w"] >= out["close"] >= out["low_52w"]
    assert out["rsi_14"]["now"] is not None and out["rsi_14"]["5_days_ago"] is not None
    json.dumps(out, allow_nan=False)  # valid JSON: no NaN slips through


def test_price_summary_needs_history():
    assert "error" in st.price_summary("X", make_bars(10))


def test_correlation_aligns_on_common_dates():
    a = make_bars(80)
    b = make_bars(80, phase=0.0)[5:]   # same moves, fewer days
    out = st.correlation({"A": a, "B": b, "NONE": []})
    pair = out["pairs_most_correlated_first"][0]
    assert pair["correlation"] == pytest.approx(1.0, abs=0.01)
    assert out["missing"] == ["NONE"]


def test_apply_changes_buys_sells_and_caps_at_zero():
    book = [{"symbol": "AAPL", "shares": 10, "avg_cost": 100}, {"symbol": "TSLA", "shares": 4, "avg_cost": 200}]
    after, notes = st.apply_changes(book, [
        {"symbol": "tsla", "shares_change": -10},   # more than held
        {"symbol": "NVDA", "shares_change": 3},
        {"symbol": "AAPL", "shares_change": float("nan")},
    ])
    assert {h["symbol"]: h["shares"] for h in after} == {"AAPL": 10, "NVDA": 3}
    assert any("only 4" in n for n in notes) and any("invalid" in n for n in notes)
    assert book[1]["shares"] == 4  # input not mutated


# ── tool dispatch ───────────────────────────────────────────

def test_every_tool_definition_is_strict_and_closed():
    for tool in st.TOOLS:
        assert tool["strict"] is True
        schema = tool["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_what_if_reports_before_and_after():
    data = fake_data(holdings=[{"symbol": "AAPL", "shares": 10, "avg_cost": 1},
                               {"symbol": "TSLA", "shares": 10, "avg_cost": 1}])
    out = st.run_tool("portfolio_what_if", {"changes": [{"symbol": "TSLA", "shares_change": -10}]}, data)
    assert set(out["before"]["weights_pct"]) == {"AAPL", "TSLA"}
    assert out["after"]["weights_pct"] == {"AAPL": 100.0}
    assert out["after"]["risk"]["sharpe"] == 1.0


def test_what_if_without_a_portfolio():
    assert "error" in st.run_tool("portfolio_what_if", {"changes": []}, fake_data())


def test_bad_input_becomes_an_error_result_not_an_exception():
    block, out = st.tool_result_block("id1", "get_correlation", {"symbols": ["AAPL"]}, fake_data())
    assert block["is_error"] is True and out is None
    block, _ = st.tool_result_block("id2", "no_such_tool", {}, fake_data())
    assert block["is_error"] is True


def test_data_source_failure_is_hidden_from_the_model():
    data = fake_data()
    data.fundamentals = lambda s: 1 / 0
    block, _ = st.tool_result_block("id", "get_fundamentals", {"symbol": "AAPL"}, data)
    assert block["is_error"] and "ZeroDivision" not in block["content"]


def test_macro_history_clamps_count_and_rejects_unknown_series():
    out = st.run_tool("get_macro_history", {"series_id": "UNRATE", "count": 500}, fake_data())
    assert len(out["readings_newest_first"]) == st.MAX_MACRO_POINTS
    with pytest.raises(ValueError):
        st.run_tool("get_macro_history", {"series_id": "SP500", "count": 3}, fake_data())


def test_unknown_symbol_says_so():
    assert "error" in st.run_tool("get_price_summary", {"symbol": "nope"}, fake_data())


# ── the loop in app.py ──────────────────────────────────────

def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(i, name, args):
    return SimpleNamespace(type="tool_use", id=i, name=name, input=args)


def resp(stop, *blocks):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


class FakeClient:
    def __init__(self, *responses, reject_first=0):
        self.responses = list(responses)
        self.calls = []
        self.reject_first = reject_first
        self.messages = self

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        if self.reject_first:
            self.reject_first -= 1
            raise app.anthropic.BadRequestError(
                "rejected", response=SimpleNamespace(status_code=400, headers={}, request=None), body=None)
        return self.responses.pop(0)


def test_loop_runs_tools_then_answers():
    client = FakeClient(
        resp("tool_use", tool_use("t1", "get_price_summary", {"symbol": "NVDA"}),
             tool_use("t2", "get_news", {"symbol": "NVDA"})),
        resp("end_turn", text("Bottom line: NVDA is up.")),
    )
    out = app._run_ski(client, "sys", [{"role": "user", "content": "how is nvda"}], fake_data())
    assert out["reply"] == "Bottom line: NVDA is up."
    assert out["tools_used"] == ["get_price_summary", "get_news"]
    # Both results go back together, in one user message, matched by id.
    results = client.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert len(out["tool_outputs"]) == 2


def test_loop_forces_an_answer_after_the_round_limit():
    looping = [resp("tool_use", tool_use(f"t{i}", "get_news", {"symbol": "AAPL"}))
               for i in range(app.SKI_MAX_TOOL_ROUNDS)]
    client = FakeClient(*looping, resp("end_turn", text("Bottom line: done.")))
    out = app._run_ski(client, "sys", [{"role": "user", "content": "q"}], fake_data())
    assert out["reply"] == "Bottom line: done."
    assert client.calls[-1]["tool_choice"] == {"type": "none"}
    assert all("tool_choice" not in c for c in client.calls[:-1])


def test_loop_returns_the_refusal_message():
    client = FakeClient(resp("refusal"))
    out = app._run_ski(client, "sys", [{"role": "user", "content": "q"}], fake_data())
    assert out["reply"] == app.SKI_REFUSAL


def test_loop_resumes_a_paused_search():
    client = FakeClient(resp("pause_turn", text("")), resp("end_turn", text("Bottom line: ok.")))
    out = app._run_ski(client, "sys", [{"role": "user", "content": "q"}], fake_data())
    assert out["reply"] == "Bottom line: ok."
    assert client.calls[1]["messages"][-1]["role"] == "assistant"


def test_loop_drops_web_search_then_all_tools_when_rejected():
    client = FakeClient(resp("end_turn", text("Bottom line: plain.")), reject_first=2)
    out = app._run_ski(client, "sys", [{"role": "user", "content": "q"}], fake_data())
    assert out["reply"] == "Bottom line: plain."
    names = [[t["name"] for t in c.get("tools", [])] for c in client.calls]
    assert names[0][0] == "web_search" and "web_search" not in names[1] and names[2] == []
