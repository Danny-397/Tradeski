"""Fundamentals computed from SEC filings, for when Yahoo's ``.info`` is blocked.

On Render, Yahoo's quoteSummary endpoint (behind ``yfinance.Ticker.info``)
returns nothing, so P/E and market cap were always blank. SEC EDGAR's XBRL
API is free, has no key and is not blocked, but it requires a User-Agent that
names the app and gives a contact email. That comes from the SEC_USER_AGENT
environment variable (for example "Tradeski you@example.com"); without it
this module is disabled and returns None.

Every number here is computed from reported figures:
  trailing EPS     = sum of the last four quarters of diluted EPS
  P/E (trailing)   = price / trailing EPS
  market cap       = price * shares outstanding (cover page, all classes)
  revenue growth   = trailing four quarters vs the four before
  net margin       = trailing net income / trailing revenue

10-Q filings report quarters, but 10-K filings report only the full year,
so the fourth quarter is derived as the year minus its first three quarters.
ETFs and foreign filers have no such facts; they come back as None.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import time
from typing import Optional

import requests

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{taxonomy}/{tag}.json"
_TIMEOUT = 10
_MAP_TTL = 24 * 3600

_REVENUE_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")

_map_lock = threading.Lock()
_ticker_map: dict = {}
_map_loaded_at = 0.0


def user_agent() -> Optional[str]:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    return ua if "@" in ua else None


def _get(url: str) -> Optional[dict]:
    ua = user_agent()
    if not ua:
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"}, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def cik_for(symbol: str) -> Optional[int]:
    """SEC company number for a ticker (the map is fetched once a day)."""
    global _ticker_map, _map_loaded_at
    with _map_lock:
        if not _ticker_map or time.time() - _map_loaded_at > _MAP_TTL:
            raw = _get(_TICKERS_URL)
            if raw:
                _ticker_map = {str(r["ticker"]).upper(): int(r["cik_str"]) for r in raw.values()}
                _map_loaded_at = time.time()
        sym = symbol.upper()
        return _ticker_map.get(sym) or _ticker_map.get(sym.replace("-", "."))


def _facts(cik: int, taxonomy: str, tag: str, unit: str) -> list:
    raw = _get(_CONCEPT_URL.format(cik=cik, taxonomy=taxonomy, tag=tag))
    return ((raw or {}).get("units") or {}).get(unit) or []


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


# ─────────────────────────────────────────────────────────────
# Pure calculations (tested without the network)
# ─────────────────────────────────────────────────────────────

def quarters(facts: list) -> list[tuple[dt.date, float]]:
    """Quarterly values as [(period end, value)], oldest first, Q4s derived.

    ``facts`` are SEC XBRL facts with start, end, val and filed. The latest
    filing wins when a period is reported more than once (restatements).
    """
    periods: dict = {}
    for f in facts:
        if "start" not in f or "end" not in f or not isinstance(f.get("val"), (int, float)):
            continue
        key = (_date(f["start"]), _date(f["end"]))
        if key not in periods or f.get("filed", "") >= periods[key][0]:
            periods[key] = (f.get("filed", ""), float(f["val"]))

    quarterly = {e: (s, v) for (s, e), (_f, v) in periods.items() if 80 <= (e - s).days <= 100}
    for (s, e), (_f, total) in periods.items():
        if 350 <= (e - s).days <= 380 and e not in quarterly:
            inside = [(qe, qv) for qe, (qs, qv) in quarterly.items() if qs >= s - dt.timedelta(days=7) and qe < e]
            if len(inside) == 3:
                last_end = max(qe for qe, _v in inside)
                quarterly[e] = (last_end + dt.timedelta(days=1), total - sum(v for _e, v in inside))
    return sorted((e, v) for e, (_s, v) in quarterly.items())


def trailing(qs: list, n: int = 4, skip: int = 0) -> Optional[tuple[dt.date, float]]:
    """Sum of n consecutive quarters ending ``skip`` quarters before the latest."""
    window = qs[len(qs) - n - skip: len(qs) - skip] if len(qs) >= n + skip else []
    if len(window) < n:
        return None
    for (a, _), (b, _) in zip(window, window[1:]):
        if not 75 <= (b - a).days <= 105:
            return None  # a gap: a quarter is missing, so this is not a full year
    return window[-1][0], sum(v for _e, v in window)


def latest_shares(facts: list) -> Optional[tuple[dt.date, float]]:
    """Shares outstanding from the cover of the latest filing, summed over share classes."""
    dated = [f for f in facts if isinstance(f.get("val"), (int, float)) and "end" in f]
    if not dated:
        return None
    newest = max(f.get("filed", "") for f in dated)
    latest = [f for f in dated if f.get("filed", "") == newest]
    end = max(_date(f["end"]) for f in latest)
    total = sum(float(f["val"]) for f in latest if _date(f["end"]) == end)
    return (end, total) if total > 0 else None


def compute(eps: list, revenue: list, net_income: list, shares: list) -> dict:
    """Price-independent fundamentals from raw fact lists (cacheable for hours)."""
    out: dict = {"source": "SEC filings (10-Q/10-K), computed by Tradeski"}
    ttm_eps = trailing(quarters(eps))
    if ttm_eps:
        out["eps_trailing_4q"] = round(ttm_eps[1], 2)
        out["latest_quarter_end"] = ttm_eps[0].isoformat()

    rev_q = quarters(revenue)
    rev_now, rev_prev = trailing(rev_q), trailing(rev_q, skip=4)
    if rev_now:
        out["revenue_trailing_4q_usd"] = round(rev_now[1])
        if rev_prev and rev_prev[1] > 0:
            out["revenue_growth_yoy_pct"] = round((rev_now[1] / rev_prev[1] - 1) * 100, 1)
        ni = trailing(quarters(net_income))
        if ni and ni[0] == rev_now[0] and rev_now[1] > 0:
            out["net_margin_trailing_pct"] = round(ni[1] / rev_now[1] * 100, 1)

    sh = latest_shares(shares)
    if sh:
        out["shares_outstanding"] = round(sh[1])
    return out


def with_price(base: dict, price: Optional[float]) -> dict:
    """Add P/E and market cap, which move with the price, to ``compute``'s output."""
    out = dict(base)
    if not price:
        return out
    out["price_used"] = round(price, 2)
    eps = out.get("eps_trailing_4q")
    if eps is not None:
        if eps > 0:
            out["pe_trailing"] = round(price / eps, 1)
        else:
            out["pe_note"] = "trailing earnings are zero or negative, so P/E is not meaningful"
    if out.get("shares_outstanding"):
        out["market_cap_usd"] = round(price * out["shares_outstanding"])
    return out


def fundamentals(symbol: str) -> Optional[dict]:
    """Price-independent fundamentals for a US-listed company from its filings, or None."""
    if not user_agent():
        return None
    cik = cik_for(symbol)
    if not cik:
        return None
    eps = _facts(cik, "us-gaap", "EarningsPerShareDiluted", "USD/shares") or \
        _facts(cik, "us-gaap", "EarningsPerShareBasic", "USD/shares")
    revenue: list = []
    for tag in _REVENUE_TAGS:
        facts = _facts(cik, "us-gaap", tag, "USD")
        # Companies switch tags over the years; use the one reported most recently.
        if facts and (not revenue or max(f["end"] for f in facts) > max(f["end"] for f in revenue)):
            revenue = facts
    net_income = _facts(cik, "us-gaap", "NetIncomeLoss", "USD")
    shares = _facts(cik, "dei", "EntityCommonStockSharesOutstanding", "shares")
    if not (eps or revenue or shares):
        return None
    return compute(eps, revenue, net_income, shares)
