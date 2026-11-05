"""Tests for the reply grounding check and the eval harness (no network, no API key)."""

import json
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "Plotly dashboard"), os.path.join(ROOT, "tests", "ski_eval")]

from tracker.ski_grounding import check, evidence_from_response_blocks  # noqa: E402
from graders import grade  # noqa: E402
import run_eval  # noqa: E402
from cases import CASES  # noqa: E402

CONTEXT = ["USER'S PORTFOLIO: NVDA 40 shares | price $312.64 | 55.3% of portfolio | P&L +12.4% | beta 1.42"]


# ── grounding ───────────────────────────────────────────────

def test_figures_from_the_data_are_grounded_at_the_replys_rounding():
    r = check("Bottom line: NVDA is **55%** of your book at **$312.64**, up 12.4%, beta 1.4.", CONTEXT, [])
    assert r["grounded"] and r["checked"] == 4


def test_an_invented_figure_is_caught():
    r = check("Bottom line: NVDA trades at 48x earnings with RSI 71.3.", CONTEXT, [{"rsi_14": {"now": 64.2}}])
    assert not r["grounded"]
    assert r["ungrounded"] == ["48x", "71.3"]


def test_counts_years_dates_and_indicator_lengths_are_not_checked():
    reply = ("Bottom line: hold steady.\n- In 2026, over 3 months, the 14-day RSI and 52-week high, "
             "the 50 day average and 10-year yield, on 2026-10-01, as 2 to 5 bullets; 2s10s matters.")
    assert check(reply, [], [])["checked"] == 0


def test_scaled_figures_match_full_numbers():
    tool = [{"market_cap": 3.12e12, "pe": 48.2}]
    assert check("Bottom line: worth $3.1 trillion at 48.2 times earnings.", [], tool)["grounded"]
    assert not check("Bottom line: worth $4.5 trillion.", [], tool)["grounded"]


def test_sign_and_thousands_separators_do_not_matter():
    assert check("Bottom line: down 2.7%, total $12,345.68.", ["return -2.7", "value 12345.68"], [])["grounded"]


def test_numbers_inside_tool_strings_count_as_evidence():
    assert check("Bottom line: 45.05% return.", [], [{"note": "returned 45.05% vs SPY"}])["grounded"]


def test_search_citations_are_evidence():
    block = SimpleNamespace(type="text", text="x", citations=[SimpleNamespace(cited_text="Put/call ratio was 0.87")])
    texts = evidence_from_response_blocks([block])
    assert check("Bottom line: the ratio was 0.87.", texts, [])["grounded"]


# ── graders ─────────────────────────────────────────────────

def _case(cid):
    return next(c for c in CASES if c["id"] == cid)


def test_grader_passes_a_good_answer_and_names_each_failure():
    good = {"reply": "Bottom line: up.", "tools_used": ["get_price_summary"], "grounded": True}
    assert grade(_case("other-ticker-trend"), good) == []

    bad = {"reply": "NVDA is up.", "tools_used": [], "grounded": False, "ungrounded_figures": ["9.9"]}
    failures = grade(_case("other-ticker-trend"), bad)
    assert [f.split(":")[0] for f in failures] == ["format", "grounding", "tools"]


def test_honesty_trap_accepts_saying_so_or_searching():
    case = _case("put-call")
    assert grade(case, {"reply": "Bottom line: I don't have options data.", "tools_used": [], "grounded": True}) == []
    assert grade(case, {"reply": "Bottom line: it was 0.87.", "tools_used": ["web_search"], "grounded": True}) == []
    assert grade(case, {"reply": "Bottom line: it is 0.9.", "tools_used": [], "grounded": True})


def test_every_case_has_a_unique_id_and_a_known_tool():
    from tracker.ski_tools import TOOL_NAMES
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    for c in CASES:
        assert set(c.get("tools_any", [])) <= set(TOOL_NAMES)


# ── the harness end to end, with a fake model ──────────────

class ScriptedClaude:
    """Calls get_price_summary, then quotes the close it got (or an invented one)."""

    def __init__(self, invent=False):
        self.invent = invent
        self.messages = self

    def create(self, **kwargs):
        last = kwargs["messages"][-1]["content"]
        if isinstance(last, str):
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id="t1", name="get_price_summary", input={"symbol": "NVDA"})])
        close = json.loads(last[0]["content"])["close"]
        figure = 999.99 if self.invent else close
        return SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="text", text=f"Bottom line: NVDA closed at ${figure}.")])


def _ask(monkeypatch, client):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("FRED_API_KEY", "fixture")
    app = run_eval.install_fixtures(monkeypatch.setattr)
    monkeypatch.setattr(app.anthropic, "Anthropic", lambda api_key: client)
    r = app.app.test_client().post("/chat", json={
        "message": "How has NVDA done?", "symbol": "AAPL", "chart_context": run_eval.chart_context(),
        "sample_portfolio": run_eval.SAMPLE_PORTFOLIO})
    assert r.status_code == 200
    return r.get_json()


def test_harness_runs_chat_on_fixtures_and_marks_a_grounded_reply(monkeypatch):
    body = _ask(monkeypatch, ScriptedClaude())
    assert body["tools_used"] == ["get_price_summary"]
    assert body["grounded"] is True
    assert grade(_case("other-ticker-trend"), body) == []


def test_harness_flags_an_invented_number(monkeypatch):
    body = _ask(monkeypatch, ScriptedClaude(invent=True))
    assert body["grounded"] is False and body["ungrounded_figures"] == ["$999.99"]


def test_fixture_bars_tell_the_story_the_cases_assume():
    closes = {s: [b["close"] for b in run_eval.fixture_bars(s)] for s in ("NVDA", "TSLA")}
    assert closes["NVDA"][-1] > closes["NVDA"][0] and closes["TSLA"][-1] < closes["TSLA"][0]
    assert run_eval.fixture_bars("ZZZQX") == []


# ── textbook reference levels ───────────────────────────────

def test_textbook_levels_next_to_their_indicator_are_not_flagged():
    # From a live reply (2026-11-04): "70" is the overbought rule of thumb, not data.
    reply = ("Bottom line: up.\n- **RSI:** Climbed from **56.1** to **64.3** over five days, moving toward "
             "the overbought zone (typically 70+). It is not yet overbought.")
    r = check(reply, ["RSI now 64.3, 5 days ago 56.1"], [])
    assert r["grounded"], r["ungrounded"]


def test_a_real_reading_or_an_unrelated_figure_is_still_checked():
    assert check("Bottom line: RSI is 70.2.", [], [])["ungrounded"] == ["70.2"]
    assert check("Bottom line: NVDA rallied 70% this year.", [], [])["ungrounded"] == ["70%"]
    assert check("Bottom line: a beta of 1.4.", [], [])["ungrounded"] == ["1.4"]
    assert check("Bottom line: a beta of 1.0 means it moves with the market.", [], [])["grounded"]
