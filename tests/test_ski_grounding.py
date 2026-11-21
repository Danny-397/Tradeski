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
    case = _case("short-interest")
    assert grade(case, {"reply": "Bottom line: I don't have short interest data.", "tools_used": [],
                        "grounded": True}) == []
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


def test_chat_caps_each_history_turn(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    app = run_eval.install_fixtures(monkeypatch.setattr)
    sent = {}

    def fake_run(client, system, messages, data, web_search=True):
        sent["messages"] = messages
        return {"reply": "ok", "search_texts": [], "tool_outputs": [], "tools_used": [], "lookups": []}

    monkeypatch.setattr(app, "_run_ski", fake_run)
    huge = "x" * 1_000_000
    r = app.app.test_client().post("/chat", json={
        "message": "hi", "history": [{"role": "user", "content": huge},
                                     {"role": "assistant", "content": huge}]})
    assert r.status_code == 200
    assert [len(m["content"]) for m in sent["messages"]] == [app.SKI_HISTORY_TURN_CHARS] * 2 + [2]


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


# ── 2026-11-15 fixes from the first real eval run ───────────

def test_a_probability_stored_as_a_fraction_matches_its_percent():
    tool = [{"prob_profit": 0.3684, "chance_ends_beyond_target": 0.0799}]
    assert check("Bottom line: about **37%** to profit, **8%** to end above $140.", ["spot 140"], tool)["grounded"]
    # Only when written as a percent, and still within rounding.
    assert check("Bottom line: 37 contracts at risk.", [], tool)["ungrounded"] == ["37"]
    assert check("Bottom line: about 45% to profit.", [], tool)["ungrounded"] == ["45%"]


def test_arithmetic_passes_only_when_its_inputs_are_shown_and_grounded():
    data = [{"close": 465.07, "high_52w": 470.65, "spot": 127.27, "expected_move": 8.56}]
    shown = "Bottom line: closed at **$465.07** against a high of **$470.65**, a gap of $5.58."
    assert check(shown, [], data)["grounded"]
    assert check("Bottom line: between $118.71 and $135.83 around $127.27 (±$8.56).", [], data)["grounded"]
    # Same derived figure without its inputs: the reader can't check it.
    assert check("Bottom line: MSFT is $5.58 below its high.", [], data)["ungrounded"] == ["$5.58"]
    # Inputs shown but one is invented: the derived figure doesn't launder it.
    r = check("Bottom line: closed at $465.07 against a high of $480.00, a gap of $14.93.", [], data)
    assert set(r["ungrounded"]) == {"$480.00", "$14.93"}
    # An invented figure that isn't a sum or difference of the shown ones still fails.
    assert check(shown + " Fair value is $512.40.", [], data)["ungrounded"] == ["$512.40"]


def test_tolerances_add_for_shown_arithmetic():
    # $3.12 - $0.61 = $2.51, and each leg was rounded to the cent, so $2.515 is consistent.
    assert check("Bottom line: buy at $3.12, sell at $0.61, net $2.515 a share.", [],
                 [{"buy": 3.12, "sell": 0.61}])["grounded"]


def test_about_widens_only_trailing_zeros():
    tool = [{"open_interest": 8806}]
    assert check("Bottom line: about 8,800 contracts open.", [], tool)["grounded"]
    assert check("Bottom line: 8,800 contracts open.", [], tool)["ungrounded"] == ["8,800"]
    assert check("Bottom line: about 8,900 contracts open.", [], tool)["ungrounded"] == ["8,900"]
    assert check("Bottom line: about 8,812 contracts open.", [], tool)["ungrounded"] == ["8,812"]


def test_scale_denominators_and_the_contract_size_are_not_data():
    assert check("Bottom line: it sits near the top of its band (96/100).", ["position 96"], [])["grounded"]
    assert check("Bottom line: a covered call needs 100 shares.", [], [])["grounded"]
    assert check("Bottom line: each options contract covers 100 shares.", [], [])["grounded"]
    # Elsewhere 100 is still checked.
    assert check("Bottom line: the stock is up 100% this year.", [], [])["ungrounded"] == ["100%"]


def test_bottom_line_in_bold_passes_the_format_check_like_the_ui():
    case = _case("biggest-position")
    for reply in ("Bottom line: NVDA.", "**Bottom line:** NVDA.", "**Bottom line**: NVDA."):
        assert grade(case, {"reply": reply, "tools_used": [], "grounded": True}) == [], reply
    for reply in ("NVDA. Bottom line: NVDA.", "Bottom line NVDA.", "**Summary:** NVDA."):
        assert grade(case, {"reply": reply, "tools_used": [], "grounded": True}), reply


def test_unknown_ticker_accepts_cant_find():
    case = _case("unknown-ticker")
    for reply in ("Bottom line: I can't find any data for ZZZQX.", "Bottom line: I can’t find ZZZQX.",
                  "Bottom line: I cannot find that symbol."):
        assert grade(case, {"reply": reply, "tools_used": [], "grounded": True}) == [], reply
    assert grade(case, {"reply": "Bottom line: ZZZQX is up 3%.", "tools_used": [], "grounded": True})


def test_held_out_cases_are_separate_and_marked():
    from cases import HELD_OUT
    ids = [c["id"] for c in CASES + HELD_OUT]
    assert len(ids) == len(set(ids))
    assert HELD_OUT and all(c.get("held_out") for c in HELD_OUT)
    assert not any(c.get("held_out") for c in CASES)


# ── 2026-11-15 Ski fixes ────────────────────────────────────

def _app():
    import app
    return app


def _text(text, url=None, cited=""):
    cites = [SimpleNamespace(url=url, title="Source page", cited_text=cited)] if url else None
    return SimpleNamespace(type="text", text=text, citations=cites)


def test_a_cited_passage_that_repeats_its_line_is_dropped():
    # Block layout seen in the eval: a paraphrase, then the cited passage itself.
    resp = SimpleNamespace(content=[
        _text("Bottom line: low.\n- ORTEX estimates **2.6% of free float** with a **0.39%** borrow cost "),
        _text("As of Oct 27, 2026, ORTEX estimated 2.6% of free float sold short, cost to borrow 0.39%.",
              "https://ortex.example/tsla"),
        _text("\n- Chartmill reports **69.35M shares** short, down from the prior report "),
        _text("As of Oct 15, 2026, TSLA had 69.35M shares sold short, representing 2.13% of float.",
              "https://chartmill.example/tsla"),
    ])
    reply = _app()._reply_text(resp)
    assert "ORTEX estimated" not in reply and "TSLA had" not in reply
    assert reply.endswith("down from the prior report")


def test_a_cited_passage_that_completes_its_sentence_is_kept():
    resp = SimpleNamespace(content=[
        _text("Bottom line: VIX is 19.30.\n- Cboe lists it at "),
        _text("$19.30 (as of November 13, 2026)", "https://cboe.example/vix"),
        _text(", with a 52-week range of "),
        _text("13.38 Low to 35.30 High", "https://cboe.example/vix"),
        _text(".\n- "),
        _text("Volatility was elevated at 23.5 on November 9.", "https://yahoo.example/vix"),
    ])
    reply = _app()._reply_text(resp)
    assert "range of 13.38 Low to 35.30 High." in reply and "elevated at 23.5" in reply


def test_sources_are_unique_http_links_in_order():
    blocks = [_text("a", "https://a.example/1"), _text("b", "https://b.example/2"),
              _text("c", "https://a.example/1"), _text("d", "javascript:alert(1)"), _text("e")]
    assert [s["url"] for s in _app()._sources(blocks)] == ["https://a.example/1", "https://b.example/2"]


def test_cited_block_text_is_evidence_since_cited_text_is_truncated():
    texts = evidence_from_response_blocks([_text("13.38 Low to 35.30 High", "https://cboe.example/vix",
                                                 cited="# Trade Data $19.30 (as of November 13, 2026)")])
    assert check("Bottom line: a 52-week range of 13.38 to 35.30.", texts, [])["grounded"]
    # Uncited text is not evidence.
    assert not evidence_from_response_blocks([_text("13.38 Low to 35.30 High")])


def test_zero_to_hundred_scales_and_the_contract_size_on_its_line():
    assert check("Bottom line: the band position is 107 on a 0–100 scale.", ["position 107"], [])["grounded"]
    reply = "Bottom line: weak.\n- **Covered call:** Only **$644** at target. It requires owning 100 shares."
    assert check(reply, ["profit 644"], [])["grounded"]
    assert check("Bottom line: you own 100 shares of NVDA.", [], [])["ungrounded"] == ["100"]


def test_the_sample_portfolio_points_ski_at_the_what_if_tool(monkeypatch):
    # The old wording ("Risk metrics are not computed for the sample, so do not
    # mention them") kept Ski from calling portfolio_what_if for signed-out users.
    app = run_eval.install_fixtures(monkeypatch.setattr)
    ctx = " ".join(app._get_portfolio_context(None, run_eval.SAMPLE_PORTFOLIO).split())
    assert "SAMPLE PORTFOLIO" in ctx and "portfolio_what_if computes them" in ctx
    assert "do not mention them" not in ctx
    assert "never work out new weights" in " ".join(app._SKI_SYSTEM_PROMPT.split())
