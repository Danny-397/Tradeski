# tracker/screens.py
# Saved stock-screener setups. The screener runs in the browser over a file
# rebuilt after each close, so the server only stores each user's setups and
# the symbols that matched when they last looked (that is how "new matches"
# are found). Everything is validated here before it is stored.

import re
from typing import Any, List

MAX_SCREENS = 10
MAX_NAME = 60
MAX_SEEN = 3000          # a screen broader than this is not tracked for new matches
MAX_FILTERS = 40

_FIELD = re.compile(r"^[a-z0-9_]{1,30}$")
_SYMBOL = re.compile(r"^[A-Z0-9.\-^]{1,10}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EARNINGS = {"", "week", "two_weeks", "month"}


def _num(v: Any):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        raise ValueError("filter bounds must be numbers or null")
    return float(v)


def _filters(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("filters must be an object")
    ranges, selects = {}, {}
    for field, pair in (raw.get("ranges") or {}).items():
        if not _FIELD.match(str(field)) or not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"bad range filter: {field!r}")
        lo, hi = _num(pair[0]), _num(pair[1])
        if lo is not None or hi is not None:
            ranges[field] = [lo, hi]
    for field, want in (raw.get("selects") or {}).items():
        if not _FIELD.match(str(field)) or not isinstance(want, str) or len(want) > 80:
            raise ValueError(f"bad select filter: {field!r}")
        if want:
            selects[field] = want
    if len(ranges) + len(selects) > MAX_FILTERS:
        raise ValueError("too many filters")
    earnings = raw.get("earnings") or ""
    if earnings not in _EARNINGS:
        raise ValueError("bad earnings filter")
    search = raw.get("search") or ""
    if not isinstance(search, str) or len(search) > 40:
        raise ValueError("bad search")
    return {"ranges": ranges, "selects": selects, "earnings": earnings, "search": search.strip()}


def clean_screen(raw: Any) -> dict:
    """One saved screen, validated. Raises ValueError with a readable message."""
    if not isinstance(raw, dict):
        raise ValueError("each screen must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("each screen needs a name")
    sort = raw.get("sort") or {}
    col = sort.get("col") if isinstance(sort, dict) else None
    direction = sort.get("dir") if isinstance(sort, dict) else None
    if col is not None and not _FIELD.match(str(col)):
        raise ValueError("bad sort column")
    seen = raw.get("seen")
    if seen is not None:
        if not isinstance(seen, list) or len(seen) > MAX_SEEN:
            raise ValueError(f"seen must be a list of at most {MAX_SEEN} symbols")
        if not all(isinstance(s, str) and _SYMBOL.match(s) for s in seen):
            raise ValueError("seen must hold ticker symbols")
        seen = sorted(set(seen))
    seen_at = raw.get("seen_at")
    if seen_at is not None and not (isinstance(seen_at, str) and _DATE.match(seen_at)):
        raise ValueError("seen_at must be a YYYY-MM-DD date")
    view = raw.get("view") or "overview"
    if not _FIELD.match(str(view)):
        raise ValueError("bad view")
    return {
        "name": name.strip()[:MAX_NAME],
        "filters": _filters(raw.get("filters") or {}),
        "sort": {"col": col or "market_cap", "dir": 1 if direction == 1 else -1},
        "view": view,
        "seen": seen,
        "seen_at": seen_at,
    }


def clean_screens(raw: Any) -> List[dict]:
    """A user's whole list of saved screens, validated; names must be unique."""
    if not isinstance(raw, list):
        raise ValueError("screens must be a list")
    if len(raw) > MAX_SCREENS:
        raise ValueError(f"you can save up to {MAX_SCREENS} screens")
    screens = [clean_screen(s) for s in raw]
    names = [s["name"].lower() for s in screens]
    if len(set(names)) != len(names):
        raise ValueError("screen names must be different")
    return screens
