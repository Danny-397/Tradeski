"""Check that the numbers in Ski's reply came from data it was actually given.

Ski is told to quote only figures from its context, tool results or a web
search it just ran. This checks the claim mechanically: every figure in the
reply must match, within the reply's own rounding, some number in the
evidence (the system prompt, the tool outputs and any cited search text).

It is a heuristic, deliberately biased towards silence. Counts, years, dates
and indicator lengths ("14-day RSI", "52-week") are not checked, and a
reply's "55%" matches evidence of 55.3. A reply's "37%" also matches a
probability stored as a fraction (0.3684), and "about 8,800" matches 8,806.

Arithmetic the model shows its work for passes: a figure equal to the sum or
difference of two other figures in the same reply that are themselves in the
data ("$470.65 high, $465.07 close, a gap of $5.58"). A derived figure whose
inputs are not quoted still counts as a miss. A miss means "this number is
not in the data": an invented figure, or arithmetic the reader can't check.
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
# Index names carry numbers that are not figures: "Nasdaq-100", "Russell 2000".
_INDEX_NAMES = re.compile(
    r"\b(?:Nasdaq[- ]?100|S&P\s?(?:500|400|600)|Russell\s?(?:1000|2000|3000)|FTSE\s?100|"
    r"Nikkei\s?225|Stoxx\s?600|Euro\s?Stoxx\s?50|Dow(?: Jones)?\s?30)\b",
    re.IGNORECASE,
)
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
    # US equity options: one contract is 100 shares.
    (re.compile(r"contract|covered call|\boptions?\b|\bstrike\b", re.I), {100}),
]

# "about 8,800", "roughly $1,200": the trailing zeros are rounding, not digits.
_APPROX = re.compile(r"(?:about|roughly|around|approximately|nearly|almost|~)\s*\$?$", re.I)


_OPTIONS_WORDS = re.compile(r"contract|covered call|\boptions?\b|\bstrike\b|\bcalls?\b|\bputs?\b", re.I)


def _is_scale_or_contract(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 3):start]
    if before.endswith("/") or re.search(r"\b0\s?[-\u2013]\s?$", before):
        return True  # "96/100", "0-100 scale"
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start:line_end if line_end != -1 else len(text)]
    return text[end:end + 7].lower().startswith(" shares") and bool(_OPTIONS_WORDS.search(line))


def _is_reference_level(text: str, start: int, end: int, value: float) -> bool:
    window = text[max(0, start - 60):end + 30]
    return any(value in levels and pattern.search(window) for pattern, levels in _REFERENCE_LEVELS)


def _figures(text: str, *, for_reply: bool) -> list[tuple[float, float, str]]:
    """Return (absolute value, rounding tolerance, raw text) for each figure.

    The tolerance is half a unit in the last digit shown, times any scale
    word, so "55%" covers 54.5 to 55.5 and "$3.4 trillion" covers 3.35e12 to
    3.45e12. In a reply, a whole number after "about"/"roughly" also treats
    its trailing zeros as rounding: "about 8,800" covers 8,750 to 8,850.
    """
    text = _INDEX_NAMES.sub(" ", _DATE.sub(" ", text))
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
            if value == 100 and _is_scale_or_contract(text, m.start(), m.end()):
                continue  # "96/100", "a 0-100 scale", "a covered call needs 100 shares"
        decimals = len(frac) - 1 if frac else 0
        tol = 0.5 * 10 ** -decimals * scale
        if for_reply and not frac and _APPROX.search(text[max(0, m.start() - 14):m.start()]):
            digits = whole.replace(",", "")
            zeros = len(digits) - len(digits.rstrip("0"))
            if 0 < zeros < len(digits):
                tol = 0.5 * 10 ** zeros * scale
        out.append((abs(value), tol + 1e-9, raw))
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

    # A probability stored as a fraction (0.3684) is written as a percent (37%).
    as_percent = [e * 100 for e in evidence if e <= 1]

    figures = _figures(reply or "", for_reply=True)

    def found(value: float, tol: float, raw: str) -> bool:
        pool = evidence + as_percent if raw.endswith("%") else evidence
        return any(abs(value - e) <= tol for e in pool)

    direct = [found(*f) for f in figures]
    # Shown arithmetic: inputs are figures from this reply that are in the data.
    inputs = [f for f, ok in zip(figures, direct) if ok]
    missing = [raw for (value, tol, raw), ok in zip(figures, direct)
               if not ok and not _derived(value, tol, raw, inputs)]
    return {"grounded": not missing, "checked": len(figures), "ungrounded": missing}


def restates(line: str, cited: str) -> bool:
    """Does a cited passage repeat the sentence just written on the same line?

    True when the passage starts a new sentence and at least half of its figures
    (one at least) are already on the line. A passage that completes the
    sentence ("a range of " + "13.38 to 35.30") starts lower-case or with a
    figure, and a bare quoted bullet has nothing on its line, so both are kept.
    """
    head = cited.lstrip()[:1]
    if not head.isupper():
        return False
    # Reply rules, so dates, years and counts ("Oct 15, 2026") don't count as figures.
    figures = _figures(cited, for_reply=True)
    shown = _figures(line, for_reply=True)
    if not figures or not shown:
        return False
    repeated = sum(any(abs(v - s) <= max(t, ts) for s, ts, _ in shown) for v, t, _ in figures)
    return repeated * 2 >= len(figures)


def _kind(raw: str) -> str:
    return "$" if "$" in raw else "%" if raw.endswith("%") else ""


def _decimals(raw: str) -> int:
    m = re.search(r"\.(\d+)", raw)
    return len(m.group(1)) if m else 0


def _derived(value: float, tol: float, raw: str, inputs: list[tuple[float, float, str]]) -> bool:
    """Is value the sum or difference of two grounded figures from the same reply?

    Only precise figures of one kind qualify: all three in dollars, or all in
    percent, each with at least two decimals ($470.65 - $465.07 = $5.58).
    Looser rules let invented figures through: on the 72 replies of the
    2026-11-15 eval, perturbing each figure by 2-20% passed 39% of the fakes
    with any two figures allowed, 15% with matching units, 0.4% with this
    rule, which still passed all 9 real derived figures. Tolerances add, since
    each input was itself rounded for display.
    """
    if _decimals(raw) < 2:
        return False
    usable = [(v, t) for v, t, r in inputs if _kind(r) == _kind(raw) and _decimals(r) >= 2]
    for i, (a, ta) in enumerate(usable):
        for b, tb in usable[i + 1:]:
            slack = tol + ta + tb
            if abs(value - (a + b)) <= slack or abs(value - abs(a - b)) <= slack:
                return True
    return False


def evidence_from_response_blocks(blocks) -> list[str]:
    """Search-result text Ski was shown: cited passages and result titles.

    The text of a block that carries a citation counts too. The API cuts each
    cited_text to about 150 characters, so "a 52-week range of 13.38 to 35.30"
    cited from further into a page could never be matched. The page itself is
    encrypted, so such a figure is checked only as far as "Ski attributed it to
    a source the user can open", not against the source's words.
    """
    texts = []
    for b in blocks or []:
        if getattr(b, "citations", None):
            texts.append(getattr(b, "text", "") or "")
        for c in getattr(b, "citations", None) or []:
            texts.append(getattr(c, "cited_text", "") or "")
        if getattr(b, "type", None) == "web_search_tool_result":
            content = getattr(b, "content", None)
            if isinstance(content, list):
                texts.extend(getattr(r, "title", "") or "" for r in content)
    return texts
