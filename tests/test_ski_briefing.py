"""Tests for prompt caching in Ski's requests and for /briefing using the tool loop."""

import json
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "Plotly dashboard"), os.path.join(ROOT, "tests", "ski_eval")]

import app  # noqa: E402
import run_eval  # noqa: E402
from tracker import ski_tools  # noqa: E402


class Recorder:
    """Fake Claude: one round of get_price_summary, then an answer quoting the close."""

    def __init__(self, answer="Bottom line: ok. close {close}"):
        self.answer = answer
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        last = kwargs["messages"][-1]["content"]
        if isinstance(last, str):
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id="t1", name="get_price_summary", input={"symbol": "NVDA"})])
        close = json.loads(last[0]["content"])["close"]
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=self.answer.format(close=close))])


def _data():
    return ski_tools.SkiData(bars=lambda s, p: run_eval.fixture_bars("NVDA"), fundamentals=lambda s: None,
                             news=lambda s: [], macro_history=lambda s, n: [], holdings=lambda: [],
                             risk=lambda raw: (None, "none"))


# ── caching ─────────────────────────────────────────────────

def test_fixed_prompt_is_cached_and_context_is_not():
    blocks = app._system_blocks(["FIXED PROMPT", "CURRENT DATE: today", "", "PORTFOLIO"])
    assert blocks[0] == {"type": "text", "text": "FIXED PROMPT", "cache_control": {"type": "ephemeral"}}
    assert blocks[1] == {"type": "text", "text": "CURRENT DATE: today\n\nPORTFOLIO"}
    assert "cache_control" not in blocks[1]


def test_every_round_sends_the_same_cached_prefix():
    client = Recorder()
    app._run_ski(client, ["FIXED", "context"], [{"role": "user", "content": "q"}], _data())
    assert len(client.calls) == 2
    first, second = client.calls
    assert first["system"] == second["system"] and first["tools"] == second["tools"]
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Top-level cache_control caches the conversation between tool rounds.
    assert all(c["cache_control"] == {"type": "ephemeral"} for c in client.calls)


def test_chat_puts_the_fixed_prompt_first_so_it_caches_across_users():
    import inspect
    src = inspect.getsource(app.chat)
    assert "system_parts = [_SKI_SYSTEM_PROMPT]" in src
    assert "_run_ski(client, system_parts," in src


def test_web_search_can_be_left_out():
    client = Recorder()
    app._run_ski(client, "sys", [{"role": "user", "content": "q"}], _data(), web_search=False)
    assert all("web_search" not in [t["name"] for t in c["tools"]] for c in client.calls)


# ── /briefing ───────────────────────────────────────────────

def _briefing(monkeypatch, client):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("FRED_API_KEY", "fixture")
    run_eval.install_fixtures(monkeypatch.setattr)
    holdings = [{"id": 1, **h} for h in run_eval.SAMPLE_PORTFOLIO]
    monkeypatch.setattr(app, "_resolve_user", lambda: 7)
    monkeypatch.setattr(app.database, "get_portfolio", lambda uid: holdings)
    monkeypatch.setattr(app.database, "get_watchlist", lambda uid: [])
    monkeypatch.setattr(app.anthropic, "Anthropic", lambda api_key: client)
    r = app.app.test_client().post("/briefing?refresh=1")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_briefing_runs_the_tool_loop_without_web_search(monkeypatch):
    client = Recorder("• NVDA closed at ${close}.\nWatch: CPI")
    body = _briefing(monkeypatch, client)
    assert body["briefing"].startswith("• NVDA closed at $")
    assert body["cached"] is False
    assert all("web_search" not in [t["name"] for t in c["tools"]] for c in client.calls)
    assert "RISK METRICS" in client.calls[0]["system"][1]["text"]  # the user's real context is there


def test_briefing_reports_a_refusal(monkeypatch):
    class Refuses(Recorder):
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", content=[])
    assert _briefing(monkeypatch, Refuses())["reason"] == "refusal"
