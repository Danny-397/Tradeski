"""Options maths for the Options tab and Ski: Black-Scholes prices and Greeks,
implied volatility from market quotes, chain cleaning, strategy analysis and a
small put/call scanner.

Design rule (as in ski_tools): code computes every number. Everything here is
pure and testable without the network; fetching lives in price_fetcher.

Model limits, which the UI states next to the numbers:

- Black-Scholes prices European options. US equity options are American, so
  values are approximate where early exercise matters (deep in-the-money puts,
  calls just before an ex-dividend date).
- Probabilities use a lognormal distribution at the options' implied
  volatility, with risk-neutral drift. That is what the market's prices imply,
  not a forecast of where the stock will go.
- Prices use the bid/ask midpoint. Real fills are usually worse; ``analyze``
  reports how much crossing the spread would cost.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Iterable, Optional

MULTIPLIER = 100            # shares per contract (and per stock "lot" leg)
_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)
_IV_LO, _IV_HI = 1e-4, 5.0  # implied-vol search range (0.01% .. 500%)

try:  # Windows Pythons may lack the tz database; the fallback is EST (UTC-5).
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - platform dependent
    _ET = _dt.timezone(_dt.timedelta(hours=-5))


# ─────────────────────────────────────────────────────────────
# Black-Scholes
# ─────────────────────────────────────────────────────────────

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT2PI


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    vt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vt
    return d1, d1 - vt


def _forward_bounds(kind: str, S: float, K: float, T: float, r: float, q: float) -> tuple[float, float]:
    """No-arbitrage (lower, upper) price bounds for a European option."""
    s, k = S * math.exp(-q * T), K * math.exp(-r * T)
    if kind == "call":
        return max(s - k, 0.0), s
    return max(k - s, 0.0), k


def bs_price(kind: str, S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """Black-Scholes(-Merton) price per share. kind is "call" or "put"."""
    if T <= 0:
        return max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)
    if sigma <= 0:
        return _forward_bounds(kind, S, K, T, r, q)[0]
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    if kind == "call":
        return S * math.exp(-q * T) * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    return K * math.exp(-r * T) * norm_cdf(-d2) - S * math.exp(-q * T) * norm_cdf(-d1)


def greeks(kind: str, S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> dict:
    """Per-share Greeks: delta, gamma, theta per calendar day, vega per 1 vol point."""
    if T <= 0 or sigma <= 0:
        itm = (S > K) if kind == "call" else (S < K)
        return {"delta": (1.0 if itm else 0.0) * (1 if kind == "call" else -1),
                "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    eq, er = math.exp(-q * T), math.exp(-r * T)
    gamma = eq * norm_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * eq * norm_pdf(d1) * math.sqrt(T) / 100.0
    decay = -S * eq * norm_pdf(d1) * sigma / (2.0 * math.sqrt(T))
    if kind == "call":
        delta = eq * norm_cdf(d1)
        theta = decay - r * K * er * norm_cdf(d2) + q * S * eq * norm_cdf(d1)
    else:
        delta = -eq * norm_cdf(-d1)
        theta = decay + r * K * er * norm_cdf(-d2) - q * S * eq * norm_cdf(-d1)
    return {"delta": delta, "gamma": gamma, "theta": theta / 365.0, "vega": vega}


def implied_vol(price: float, kind: str, S: float, K: float, T: float, r: float,
                q: float = 0.0) -> Optional[float]:
    """Volatility at which Black-Scholes reproduces ``price``, or None.

    None when the price is outside the no-arbitrage bounds (a stale or
    crossed quote) or would need a volatility above 500%.
    """
    if not (price > 0 and S > 0 and K > 0 and T > 0):
        return None
    lo_b, hi_b = _forward_bounds(kind, S, K, T, r, q)
    if price <= lo_b + 1e-9 or price >= hi_b:
        return None
    lo, hi = _IV_LO, _IV_HI
    if bs_price(kind, S, K, T, r, hi, q) < price:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs_price(kind, S, K, T, r, mid, q) < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return 0.5 * (lo + hi)


# ─────────────────────────────────────────────────────────────
# Time and chains
# ─────────────────────────────────────────────────────────────

def year_fraction(expiry: str, now: Optional[_dt.datetime] = None) -> float:
    """Years from ``now`` until 4pm New York time on ``expiry`` (YYYY-MM-DD)."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    d = _dt.date.fromisoformat(expiry)
    close = _dt.datetime(d.year, d.month, d.day, 16, 0, tzinfo=_ET)
    return (close - now).total_seconds() / (365.0 * 86400.0)


def days_to_expiry(expiry: str, today: Optional[_dt.date] = None) -> int:
    today = today or _dt.datetime.now(_ET).date()
    return (_dt.date.fromisoformat(expiry) - today).days


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r(x, digits: int = 4):
    return None if x is None else round(x, digits)


def clean_contract(row: dict, kind: str, S: float, T: float, r: float, q: float) -> dict:
    """One contract from the data source, with its own IV and Greeks.

    IV is solved from the bid/ask midpoint when both sides are quoted; the
    data source's IV is used only as a fallback (it is often stale out of
    hours) and the row says which one it is.
    """
    K = _num(row.get("strike")) or 0.0
    bid, ask = _num(row.get("bid")) or 0.0, _num(row.get("ask")) or 0.0
    mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 and ask >= bid else None
    iv, source = None, None
    if mid is not None:
        iv = implied_vol(mid, kind, S, K, T, r, q)
        source = "mid" if iv is not None else None
    if iv is None:
        theirs = _num(row.get("impliedVolatility"))
        if theirs is not None and 0.01 < theirs < _IV_HI:
            iv, source = theirs, "data source"
    g = greeks(kind, S, K, T, r, iv, q) if iv else {}
    last_trade = row.get("lastTradeDate")
    return {
        "contract": row.get("contractSymbol"),
        "type": kind,
        "strike": K,
        "bid": bid or None,
        "ask": ask or None,
        "mid": _r(mid, 3),
        "last": _num(row.get("lastPrice")),
        "volume": int(_num(row.get("volume")) or 0),
        "open_interest": int(_num(row.get("openInterest")) or 0),
        "spread_pct": _r((ask - bid) / mid * 100.0, 1) if mid else None,
        "iv": _r(iv),
        "iv_source": source,
        "delta": _r(g.get("delta")),
        "gamma": _r(g.get("gamma"), 5),
        "theta": _r(g.get("theta")),
        "vega": _r(g.get("vega")),
        "itm": (S > K) if kind == "call" else (S < K),
        "last_trade": str(last_trade)[:19] if last_trade is not None else None,
    }


def clean_chain(raw: dict, expiry: str, r: float, now: Optional[_dt.datetime] = None) -> dict:
    """Turn a raw chain (see price_fetcher.get_option_chain) into the API shape."""
    S = float(raw["spot"])
    q = float(raw.get("dividend_yield") or 0.0)
    T = max(year_fraction(expiry, now), 1.0 / (365 * 24))   # at least an hour
    calls = sorted((clean_contract(c, "call", S, T, r, q) for c in raw.get("calls", [])),
                   key=lambda c: c["strike"])
    puts = sorted((clean_contract(p, "put", S, T, r, q) for p in raw.get("puts", [])),
                  key=lambda c: c["strike"])
    atm = atm_iv(calls, puts, S)
    return {
        "symbol": raw.get("symbol"),
        "expiry": expiry,
        "spot": S,
        "dividend_yield": q,
        "rate": r,
        "years": T,
        "dte": days_to_expiry(expiry),
        "market_state": raw.get("market_state"),
        "atm_iv": _r(atm),
        "expected_move": _r(S * atm * math.sqrt(T), 2) if atm else None,
        "calls": calls,
        "puts": puts,
        "put_call_volume": _ratio(sum(p["volume"] for p in puts), sum(c["volume"] for c in calls)),
        "put_call_oi": _ratio(sum(p["open_interest"] for p in puts), sum(c["open_interest"] for c in calls)),
    }


def _ratio(a: float, b: float) -> Optional[float]:
    return round(a / b, 2) if b else None


def atm_iv(calls: list, puts: list, S: float) -> Optional[float]:
    """Average IV of the call and put at the strike nearest the spot."""
    ivs = []
    for side in (calls, puts):
        quoted = [c for c in side if c.get("iv")]
        if quoted:
            ivs.append(min(quoted, key=lambda c: abs(c["strike"] - S))["iv"])
    return sum(ivs) / len(ivs) if ivs else None


def realized_vol(closes: Iterable[float], window: int = 30) -> Optional[float]:
    """Annualised close-to-close volatility over the last ``window`` returns."""
    c = [float(x) for x in closes if x]
    if len(c) < window + 1:
        return None
    rets = [math.log(c[i] / c[i - 1]) for i in range(len(c) - window, len(c))]
    m = sum(rets) / len(rets)
    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252.0)


# ─────────────────────────────────────────────────────────────
# End-of-day chains (the fallback when the live source refuses the server)
# ─────────────────────────────────────────────────────────────
# Yahoo serves option chains to GitHub's runners but not to Render, so the
# snapshot workflow saves each day's closing chains as static files and the
# backend falls back to them. Rows keep the data source's column names, so
# clean_contract reads them unchanged.

_EOD_FIELDS = ("strike", "bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility")


def compact_rows(rows: list, spot: float, band: float = 0.30) -> list:
    """Rows within ``band`` of the spot, keeping only the fields the maths uses."""
    out = []
    for row in rows:
        k = _num(row.get("strike"))
        if k is None or abs(k / spot - 1) > band + 1e-9:
            continue
        out.append({f: _num(row.get(f)) for f in _EOD_FIELDS})
    return out


def eod_raw_chain(eod: dict, expiry: str) -> Optional[dict]:
    """One expiry from a saved end-of-day file, in get_option_chain's raw shape."""
    chain = (eod.get("chains") or {}).get(expiry)
    if not chain or not eod.get("spot"):
        return None
    return {"symbol": eod.get("symbol"), "spot": float(eod["spot"]),
            "dividend_yield": float(eod.get("dividend_yield") or 0.0), "market_state": "CLOSED",
            "calls": chain.get("calls", []), "puts": chain.get("puts", [])}


# ─────────────────────────────────────────────────────────────
# Strategies
# ─────────────────────────────────────────────────────────────
# A leg is {"type": "call"|"put"|"stock", "qty": int, "strike": float,
#           "price": float per share, "iv": float, "bid": .., "ask": ..}.
# qty > 0 is long, < 0 short. One unit is one contract, or 100 shares for stock.

PRESETS = {
    "long_call": "Long call",
    "long_put": "Long put",
    "covered_call": "Covered call",
    "cash_secured_put": "Cash-secured put",
    "bull_call_spread": "Bull call spread",
    "bear_put_spread": "Bear put spread",
    "long_straddle": "Long straddle",
    "long_strangle": "Long strangle",
    "iron_condor": "Iron condor",
}


def _leg_value(leg: dict, x: float, T: float, r: float, q: float) -> float:
    if leg["type"] == "stock":
        return x
    if T <= 0 or not leg.get("iv"):
        return bs_price(leg["type"], x, leg["strike"], 0.0, r, 0.0, q)
    return bs_price(leg["type"], x, leg["strike"], T, r, leg["iv"], q)


def position_pnl(legs: list, x: float, T: float = 0.0, r: float = 0.0, q: float = 0.0) -> float:
    """P/L in dollars if the stock is at ``x`` with ``T`` years left (0 = expiry)."""
    return sum(leg["qty"] * MULTIPLIER * (_leg_value(leg, x, T, r, q) - leg["price"]) for leg in legs)


def _kinks(legs: list) -> list:
    return sorted({0.0} | {float(leg["strike"]) for leg in legs if leg["type"] != "stock"})


def _upside_slope(legs: list) -> float:
    """dP/L / dprice far above every strike, at expiry."""
    return sum(leg["qty"] * MULTIPLIER for leg in legs if leg["type"] in ("call", "stock"))


def breakevens(legs: list) -> list:
    """Stock prices at expiry where P/L is exactly zero (the payoff is piecewise linear)."""
    pts = _kinks(legs)
    vals = [position_pnl(legs, p) for p in pts]
    out = []
    for (a, va), (b, vb) in zip(zip(pts, vals), zip(pts[1:], vals[1:])):
        if va == 0 and a > 0:
            out.append(a)
        elif va * vb < 0:
            out.append(a + (b - a) * va / (va - vb))
    last, vlast = pts[-1], vals[-1]
    slope = _upside_slope(legs)
    if vlast == 0 and last > 0:
        out.append(last)
    elif slope and vlast * slope < 0:
        out.append(last - vlast / slope)
    return sorted({round(b, 2) for b in out})


def _prob_below(x: float, S: float, T: float, r: float, q: float, sigma: float) -> float:
    if x <= 0:
        return 0.0
    if math.isinf(x):
        return 1.0
    z = (math.log(x / S) - (r - q - 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return norm_cdf(z)


def profit_zones(legs: list) -> list:
    """Price intervals [(lo, hi), ...] where P/L at expiry is positive (hi may be inf)."""
    edges = sorted(set(_kinks(legs)) | set(breakevens(legs)))
    edges.append(math.inf)
    zones = []
    for a, b in zip(edges, edges[1:]):
        probe = a + 1.0 if math.isinf(b) else (a + b) / 2.0
        if position_pnl(legs, probe) > 1e-9:
            if zones and abs(zones[-1][1] - a) < 1e-9:
                zones[-1] = (zones[-1][0], b)
            else:
                zones.append((a, b))
    return zones


def prob_of_profit(legs: list, S: float, T: float, r: float, q: float, sigma: Optional[float]) -> Optional[float]:
    """Chance the position is profitable at expiry, under the market-implied lognormal."""
    if not sigma or T <= 0:
        return None
    return sum(_prob_below(b, S, T, r, q, sigma) - _prob_below(a, S, T, r, q, sigma)
               for a, b in profit_zones(legs))


def _money(x: float) -> str:
    # Half-up rounding, as the browser's number formatting does, so the
    # summary sentence and the stat tiles show the same whole-dollar figure.
    return f"${math.floor(abs(x) + 0.5):,}" if abs(x) >= 100 else f"${abs(x):,.2f}"


def _describe_zones(zones: list, symbol: str) -> str:
    parts = []
    for a, b in zones:
        if a <= 0 and math.isinf(b):
            parts.append("at any price")
        elif a <= 0:
            parts.append(f"below ${b:,.2f}")
        elif math.isinf(b):
            parts.append(f"above ${a:,.2f}")
        else:
            parts.append(f"between ${a:,.2f} and ${b:,.2f}")
    return f"{symbol} closes " + " or ".join(parts) if parts else ""


def analyze(legs: list, S: float, T: float, r: float, q: float = 0.0, sigma: Optional[float] = None,
            symbol: str = "the stock", expiry: str = "", days_forward: Optional[float] = None,
            points: int = 121) -> dict:
    """Everything the strategy builder shows for one set of legs."""
    if not legs:
        raise ValueError("add at least one leg")
    debit = sum(leg["qty"] * MULTIPLIER * leg["price"] for leg in legs)
    pts = _kinks(legs)
    vals = [position_pnl(legs, p) for p in pts]
    slope = _upside_slope(legs)
    max_profit = None if slope > 1e-9 else max(vals)
    max_loss = None if slope < -1e-9 else min(vals)
    bes = breakevens(legs)
    zones = profit_zones(legs)
    pop = prob_of_profit(legs, S, T, r, q, sigma)
    spread_cost = sum(abs(leg["qty"]) * MULTIPLIER * (leg["ask"] - leg["bid"]) / 2.0
                      for leg in legs if leg["type"] != "stock" and leg.get("bid") and leg.get("ask"))

    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        if leg["type"] == "stock":
            net["delta"] += leg["qty"] * MULTIPLIER
        elif leg.get("iv"):
            g = greeks(leg["type"], S, leg["strike"], T, r, leg["iv"], q)
            for k in net:
                net[k] += leg["qty"] * MULTIPLIER * g[k]

    strikes = [leg["strike"] for leg in legs if leg["type"] != "stock"] or [S]
    width = max(3.0 * (sigma or 0.3) * math.sqrt(max(T, 1 / 365)), 0.15)
    lo = max(0.0, min(S * (1 - width), min(strikes) * 0.9))
    hi = max(S * (1 + width), max(strikes) * 1.1)
    grid = [lo + (hi - lo) * i / (points - 1) for i in range(points)]
    curves = {
        "prices": [round(x, 2) for x in grid],
        "expiry": [round(position_pnl(legs, x), 2) for x in grid],
        "today": [round(position_pnl(legs, x, T, r, q), 2) for x in grid],
    }
    if days_forward is not None and 0 < days_forward < T * 365:
        t_left = T - days_forward / 365.0
        curves["at_date"] = [round(position_pnl(legs, x, t_left, r, q), 2) for x in grid]
        curves["at_date_days"] = days_forward

    when = f" on {expiry}" if expiry else " at expiry"
    lines = [f"{'Costs' if debit > 0 else 'Collects'} {_money(debit)} up front (at mid prices)."]
    if zones:
        lines.append(f"Makes money if {_describe_zones(zones, symbol)}{when}.")
    else:
        lines.append(f"Does not make money at any price{when}.")
    lines.append("Best case: unlimited." if max_profit is None else
                 f"Best case: {'+' if max_profit >= 0 else '-'}{_money(max_profit)}.")
    lines.append("Worst case: unlimited loss." if max_loss is None else
                 f"Worst case: {'lose ' if max_loss < 0 else '+'}{_money(max_loss)}.")
    if pop is not None:
        lines.append(f"Market-implied chance of profit: {pop * 100:.0f}%.")

    return {
        "legs": legs,
        "net_debit": round(debit, 2),
        "max_profit": None if max_profit is None else round(max_profit, 2),
        "max_loss": None if max_loss is None else round(max_loss, 2),
        "unlimited_profit": max_profit is None,
        "unlimited_loss": max_loss is None,
        "breakevens": bes,
        "profit_zones": [[round(a, 2), None if math.isinf(b) else round(b, 2)] for a, b in zones],
        "prob_profit": None if pop is None else round(pop, 4),
        "return_on_risk": (round(max_profit / -max_loss, 4)
                           if max_profit is not None and max_loss is not None and max_loss < 0 else None),
        "spread_cost": round(spread_cost, 2),
        "greeks": {k: round(v, 4) for k, v in net.items()},
        "curves": curves,
        "summary": " ".join(lines),
    }


# ─────────────────────────────────────────────────────────────
# Building legs from a chain
# ─────────────────────────────────────────────────────────────

def _quoted(contracts: list) -> list:
    return [c for c in contracts if c.get("mid") and c.get("iv")]


def _pick(contracts: list, key, cond=lambda c: True) -> Optional[dict]:
    pool = [c for c in contracts if cond(c)]
    return min(pool, key=key) if pool else None


def _by_delta(contracts: list, target: float, cond=lambda c: True) -> Optional[dict]:
    return _pick(contracts, lambda c: abs((c.get("delta") or 0) - target),
                 lambda c: c.get("delta") is not None and cond(c))


def _leg(contract: dict, qty: int) -> dict:
    return {"type": contract["type"], "qty": qty, "strike": contract["strike"], "price": contract["mid"],
            "iv": contract["iv"], "bid": contract.get("bid"), "ask": contract.get("ask")}


def stock_leg(S: float, qty: int = 1) -> dict:
    return {"type": "stock", "qty": qty, "strike": None, "price": S, "iv": None}


def build_preset(name: str, chain: dict) -> list:
    """Legs for a named strategy, with strikes chosen from the chain.

    Rules of thumb: "at the money" is the strike nearest the spot; sold
    options target delta 0.30 (0.20 for the condor's short strikes, 0.25 for
    the strangle); spreads and wings are about 5% / 2.5% of the spot wide.
    """
    S = chain["spot"]
    calls, puts = _quoted(chain["calls"]), _quoted(chain["puts"])
    if not calls or not puts:
        raise ValueError("no quoted options at this expiry")
    near = lambda c: abs(c["strike"] - S)  # noqa: E731
    atm_c, atm_p = _pick(calls, near), _pick(puts, near)
    legs: list = []
    if name == "long_call":
        legs = [_leg(atm_c, 1)]
    elif name == "long_put":
        legs = [_leg(atm_p, 1)]
    elif name == "covered_call":
        c = _by_delta(calls, 0.30, lambda c: c["strike"] > S)
        legs = [stock_leg(S), _leg(c, -1)] if c else []
    elif name == "cash_secured_put":
        p = _by_delta(puts, -0.30, lambda c: c["strike"] < S)
        legs = [_leg(p, -1)] if p else []
    elif name == "bull_call_spread":
        hi = _pick(calls, lambda c: abs(c["strike"] - S * 1.05), lambda c: c["strike"] > atm_c["strike"])
        legs = [_leg(atm_c, 1), _leg(hi, -1)] if hi else []
    elif name == "bear_put_spread":
        lo = _pick(puts, lambda c: abs(c["strike"] - S * 0.95), lambda c: c["strike"] < atm_p["strike"])
        legs = [_leg(atm_p, 1), _leg(lo, -1)] if lo else []
    elif name == "long_straddle":
        p = _pick(puts, lambda c: abs(c["strike"] - atm_c["strike"]))
        legs = [_leg(atm_c, 1), _leg(p, 1)]
    elif name == "long_strangle":
        c = _by_delta(calls, 0.25, lambda c: c["strike"] > S)
        p = _by_delta(puts, -0.25, lambda c: c["strike"] < S)
        legs = [_leg(c, 1), _leg(p, 1)] if c and p else []
    elif name == "iron_condor":
        w = S * 0.025
        sp = _by_delta(puts, -0.20, lambda c: c["strike"] < S)
        sc = _by_delta(calls, 0.20, lambda c: c["strike"] > S)
        lp = sp and _pick(puts, lambda c: abs(c["strike"] - (sp["strike"] - w)), lambda c: c["strike"] < sp["strike"])
        lc = sc and _pick(calls, lambda c: abs(c["strike"] - (sc["strike"] + w)), lambda c: c["strike"] > sc["strike"])
        legs = [_leg(lp, 1), _leg(sp, -1), _leg(sc, -1), _leg(lc, 1)] if lp and lc else []
    else:
        raise ValueError(f"unknown strategy {name}; choose one of {', '.join(PRESETS)}")
    if not legs:
        raise ValueError("this expiry has no strikes that fit that strategy")
    return legs


def legs_from_request(specs: list, chain: dict, max_legs: int = 6) -> list:
    """Price user-chosen legs [{type, qty, strike}] from the chain."""
    if not isinstance(specs, list) or not specs:
        raise ValueError("legs must be a non-empty list")
    if len(specs) > max_legs:
        raise ValueError(f"at most {max_legs} legs")
    book = {("call", c["strike"]): c for c in chain["calls"]}
    book.update({("put", p["strike"]): p for p in chain["puts"]})
    legs = []
    for s in specs:
        kind = (s or {}).get("type")
        try:
            qty = int(s.get("qty"))
        except (TypeError, ValueError):
            raise ValueError("each leg needs an integer qty")
        if qty == 0 or abs(qty) > 100:
            raise ValueError("qty must be between -100 and 100, and not 0")
        if kind == "stock":
            legs.append(stock_leg(chain["spot"], qty))
            continue
        if kind not in ("call", "put"):
            raise ValueError("leg type must be call, put or stock")
        strike = _num(s.get("strike"))
        c = book.get((kind, strike))
        if c is None:
            raise ValueError(f"no {kind} at strike {strike} for {chain['expiry']}")
        if not c.get("mid") or not c.get("iv"):
            raise ValueError(f"the {strike:g} {kind} has no usable quote right now")
        legs.append(_leg(c, qty))
    return legs


# ─────────────────────────────────────────────────────────────
# Scanner: cash-secured puts and covered calls across symbols
# ─────────────────────────────────────────────────────────────

SCAN_KINDS = ("cash_secured_put", "covered_call")


def pick_expiry(expiries: list, min_dte: int, max_dte: int, target: int = 30,
                today: Optional[_dt.date] = None) -> Optional[str]:
    """The expiry inside [min_dte, max_dte] closest to ``target`` days."""
    ok = [(abs(days_to_expiry(e, today) - target), e) for e in expiries
          if min_dte <= days_to_expiry(e, today) <= max_dte]
    return min(ok)[1] if ok else None


def scan_candidate(kind: str, chain: dict, max_delta: float = 0.30, min_oi: int = 100,
                   max_spread_pct: float = 10.0) -> Optional[dict]:
    """The best short put (or covered call) in one chain that passes the filters.

    "Best" is the strike whose |delta| is closest to ``max_delta`` from
    below: the most premium the filters allow. Returns None if none pass.
    """
    if kind not in SCAN_KINDS:
        raise ValueError(f"kind must be one of {SCAN_KINDS}")
    S, T, r, q = chain["spot"], chain["years"], chain["rate"], chain["dividend_yield"]
    side = chain["puts"] if kind == "cash_secured_put" else chain["calls"]
    pool = [c for c in _quoted(side)
            if c.get("delta") is not None and abs(c["delta"]) <= max_delta
            and c["open_interest"] >= min_oi
            and c["spread_pct"] is not None and c["spread_pct"] <= max_spread_pct
            and (c["strike"] < S if kind == "cash_secured_put" else c["strike"] > S)]
    if not pool:
        return None
    best = max(pool, key=lambda c: abs(c["delta"]))
    legs = [_leg(best, -1)] if kind == "cash_secured_put" else [stock_leg(S), _leg(best, -1)]
    # The ATM IV, as the strategy builder uses, so both show the same chance of profit.
    res = analyze(legs, S, T, r, q, sigma=chain.get("atm_iv") or best["iv"], points=3)
    capital = best["strike"] * MULTIPLIER if kind == "cash_secured_put" else S * MULTIPLIER
    premium = best["mid"] * MULTIPLIER
    dte = max(chain.get("dte") or 1, 1)
    return {
        "symbol": chain.get("symbol"),
        "kind": kind,
        "expiry": chain["expiry"],
        "dte": dte,
        "spot": S,
        "strike": best["strike"],
        "delta": best["delta"],
        "iv": best["iv"],
        "premium": round(premium, 2),
        "capital": round(capital, 2),
        "return_pct": round(premium / capital * 100.0, 2),
        "annualized_pct": round(premium / capital * 100.0 * 365.0 / dte, 1),
        "breakeven": res["breakevens"][0] if res["breakevens"] else None,
        "prob_profit": res["prob_profit"],
        "open_interest": best["open_interest"],
        "spread_pct": best["spread_pct"],
    }
