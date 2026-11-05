"""Check that the numbers in Ski's reply came from data it was actually given.

Ski is told to quote only figures from its context, tool results or a web
search it just ran. This checks the claim mechanically: every figure in the
reply must match, within the reply's own rounding, some number in the
evidence (the system prompt, the tool outputs and any cited search text).

It is a heuristic, deliberately biased towards silence. Counts, years, dates
and indicator lengths ("14-day RSI", "52-week") are not checked, and a
reply's "55%" matches evidence of 55.3. A miss means "this number is not in
the data", which is either an invented figure or a derived one (a sum the
model did itself); both are worth knowing about.
"""

from __future__ import annotations

import re
from typing import Iterable

_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
          "b": 1e9, "bn": 1e9, "billion": 1e9, "t": 1e12, "tn": 1e12, "trillion": 1e12}

# A figure: optional sign/$, digits with optional commas and decimals, then
# an optional %, x or scale word. Lookarounds keep it out of words (2s10s,
# Q3, H1) and ranges like "52-week".
_FIGURE = re.compile(
    r"(?<![\w.])([-+−]?)\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
    r"(?:\s?(%|x\b|[kmbt]n?\b|thousand\b|million\b|billion\b|trillion\b))?"
    r"(?![\w-]*[a-z]-?\w)",
    re.IGNORECASE,
)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")
_LENGTH_WORDS = re.compile(r"^\s*-?\s?(?:day|week|month|year|period|bar)s?\b", re.IGNORECASE)


# Textbook reference levels: "overbought above 70" is a rule of thumb, not a
# market figure, so it is not looked for in the data. A figure is skipped
# only when it equals one of these levels exactly AND the indicator is named
# close by, so a real reading ("RSI 70.2") or an unrelated "up 30%" is still
# checked. The cost: an invented reading that happens to equal a level
# ("RSI is 70") passes.
_REFERENCE_LEVELS = [
    (re.compile(r"\brsi\b|overbought|oversold|relative strength", re.I), {20, 30, 50, 70, 80}),
    (re.compile(r"stochastic|%k\b", re.I), {20, 50, 80}),
    (re.compile(r"\bvix\b|volatility index", re.I), {20, 30, 40}),
    (re.compile(r"\bbeta\b", re.I), {1}),
    (re.compile(r"\bsharpe\b", re.I), {0, 1, 2}),
    (re.compile(r"bollinger|standard deviations?", re.I), {2}),
    (re.compile(r"\bz-?score\b", re.I), {1, 2, 3}),
    (re.compile(r"\bmacd\b|histogram|signal line|zero line", re.I), {0}),
]


def _is_reference_level(text: str, start: int, end: int, value: float) -> bool:
    window = text[max(0, start - 60):end + 30]
    return any(value in levels and pattern.search(window) for pattern, levels in _REFERENCE_LEVELS)


def _figures(text: str, *, for_reply: bool) -> list[tuple[float, float, str]]:
    """Return (absolute value, rounding tolerance, raw text) for each figure.

    The tolerance is half a unit in the last digit shown, times any scale
    word, so "55%" covers 54.5 to 55.5 and "$3.4 trillion" covers 3.35e12 to
    3.45e12.
    """
    text = _DATE.sub(" ", text)
    out = []
    for m in _FIGURE.finditer(text):
        whole, frac, unit = m.group(2), m.group(3) or "", (m.group(4) or "").lower()
        raw = m.group(0).strip()
        scale = _SCALE.get(unit, 1.0)
        value = float(whole.replace(",", "") + frac) * scale
        if for_reply:
            after = text[m.end():m.end() + 12]
            is_plain_int = not frac and not unit and "$" not in raw
            if is_plain_int and (value <= 31 or 1900 <= value <= 2100):
                continue  # counts, list sizes, days, years
            if _LENGTH_WORDS.match(after) or after.startswith("-"):
                continue  # "14-day", "50 day", "52-week", "10-year"
            if _is_reference_level(text, m.start(), m.end(), value):
                continue  # "RSI above 70", "beta of 1", "VIX over 30"
        decimals = len(frac) - 1 if frac else 0
        out.append((abs(value), 0.5 * 10 ** -decimals * scale + 1e-9, raw))
    return out


def _numbers_in(obj) -> Iterable[float]:
    """Every number in a JSON-like structure, plus numbers inside its strings."""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        yield abs(float(obj))
    elif isinstance(obj, str):
        for value, _tol, _raw in _figures(obj, for_reply=False):
            yield value
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _numbers_in(v)


def check(reply: str, evidence_texts: list[str], evidence_objects: list) -> dict:
    """Return {"grounded": bool, "checked": n, "ungrounded": [raw figures]}."""
    evidence: list[float] = []
    for text in evidence_texts:
        evidence.extend(v for v, _tol, _raw in _figures(text or "", for_reply=False))
    for obj in evidence_objects:
        evidence.extend(_numbers_in(obj))

    figures = _figures(reply or "", for_reply=True)
    missing = [raw for value, tol, raw in figures if not any(abs(value - e) <= tol for e in evidence)]
    return {"grounded": not missing, "checked": len(figures), "ungrounded": missing}


def evidence_from_response_blocks(blocks) -> list[str]:
    """Search-result text Ski was shown: cited passages and result titles."""
    texts = []
    for b in blocks or []:
        for c in getattr(b, "citations", None) or []:
            texts.append(getattr(c, "cited_text", "") or "")
        if getattr(b, "type", None) == "web_search_tool_result":
            content = getattr(b, "content", None)
            if isinstance(content, list):
                texts.extend(getattr(r, "title", "") or "" for r in content)
    return texts
