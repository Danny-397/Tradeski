"""Tools Ski can call to look things up, instead of relying on pasted context.

Design rule: code computes every number; the model only decides what to look
up and explains the result. Each tool returns a small JSON-serialisable dict.

Data access is injected through a ``SkiData`` object (built in app.py from
its cached fetchers), so everything here is testable without the network.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from tracker.analyzer import atr, bollinger_bands, macd, rsi, sma, stochastic

MAX_CORR_SYMBOLS = 10
MAX_WHAT_IF_CHANGES = 10
MAX_MACRO_POINTS = 24

# FRED series Ski may ask for history on, with a plain-language label.
MACRO_SERIES = {
    "CPIAUCSL": "CPI, % change from a year earlier",
    "FEDFUNDS": "Effective federal funds rate, %",
    "UNRATE": "Unemployment rate, %",
    "DGS10": "10-year Treasury yield, %",
    "T10Y2Y": "10-year minus 2-year Treasury spread, percentage points",
    "BAMLH0A0HYM2": "High-yield corporate bond spread (OAS), percentage points",
    "GDP": "Nominal GDP, $ billions (annualised, quarterly)",
}


@dataclass
class SkiData:
    """Data sources the tools read from. Every callable must be cached upstream."""

    bars: Callable[[str, str], list]               # (symbol, period) -> daily OHLC bars
    fundamentals: Callable[[str], Optional[dict]]  # symbol -> screener row
    news: Callable[[str], list]                    # symbol -> scored articles
    macro_history: Callable[[str, int], list]      # (series_id, n) -> FRED observations
    holdings: Callable[[], list]                   # the user's (or sample) raw holdings
    risk: Callable[[list], tuple]                  # raw holdings -> (metrics | None, reason)


def clean_symbol(raw) -> str:
    return re.sub(r"[^A-Z0-9.\-]", "", str(raw or "").upper())[:10]


def _r(value, digits: int = 2):
    """Round a finite number; None for anything else (keeps output valid JSON)."""
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if math.isfinite(value) else None


def _pct(new, old):
    if new is None or old in (None, 0):
        return None
    return _r((new / old - 1) * 100, 1)


# ─────────────────────────────────────────────────────────────
# Pure calculations
# ─────────────────────────────────────────────────────────────

def price_summary(symbol: str, bars: list) -> dict:
    """Returns, range position, realised volatility and indicator trends.

    ``bars`` are about a year of daily bars, oldest first. Indicators are given
    now and 5 trading days ago, so the model can say "RSI rose from 48 to 64"
    instead of reading one isolated value.
    """
    if len(bars) < 30:
        return {"symbol": symbol, "error": "not enough price history"}

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    last = closes[-1]

    def back(n):
        return closes[-1 - n] if len(closes) > n else None

    daily = np.diff(closes) / np.array(closes[:-1])

    def realised_vol(n):
        window = daily[-n:]
        return _r(float(np.std(window)) * math.sqrt(252) * 100, 1) if len(window) >= 10 else None

    high_52w, low_52w = max(highs), min(lows)
    rsi_vals = rsi(closes, 14)
    macd_line, signal_line, hist = macd(closes)
    upper, lower = bollinger_bands(closes, 20)
    sma20, sma50, sma200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    atr_vals = atr(highs, lows, closes, 14)
    k_vals, _d = stochastic(highs, lows, closes)

    def now_and_5d(series, digits=2):
        return {"now": _r(series[-1], digits), "5_days_ago": _r(series[-6], digits) if len(series) > 5 else None}

    crossed = None
    if len(hist) > 1 and hist[-1] != 0 and (hist[-1] > 0) != (hist[-2] > 0):
        crossed = "bullish" if hist[-1] > 0 else "bearish"

    band_pos = None
    if upper[-1] is not None and lower[-1] is not None and upper[-1] != lower[-1]:
        # 0 = on the lower band, 100 = on the upper band.
        band_pos = _r((last - lower[-1]) / (upper[-1] - lower[-1]) * 100, 0)

    def vs(avg):
        return _pct(last, avg[-1]) if avg and avg[-1] is not None else None

    return {
        "symbol": symbol,
        "as_of": bars[-1]["timestamp"][:10],
        "close": _r(last),
        "return_pct": {
            "1_week": _pct(last, back(5)),
            "1_month": _pct(last, back(21)),
            "3_months": _pct(last, back(63)),
            "full_period": _pct(last, closes[0]),
        },
        "full_period_days": len(closes),
        "high_52w": _r(high_52w),
        "low_52w": _r(low_52w),
        "pct_below_52w_high": _r((1 - last / high_52w) * 100, 1),
        "pct_above_52w_low": _r((last / low_52w - 1) * 100, 1),
        "realised_volatility_annualised_pct": {"1_month": realised_vol(21), "3_months": realised_vol(63)},
        "rsi_14": now_and_5d(rsi_vals, 1),
        "macd": {
            "macd": _r(macd_line[-1], 3),
            "signal": _r(signal_line[-1], 3),
            "histogram": now_and_5d(hist, 3),
            "crossover_on_latest_bar": crossed,
        },
        "pct_vs_moving_average": {"sma_20": vs(sma20), "sma_50": vs(sma50), "sma_200": vs(sma200)},
        "bollinger_position_0_to_100": band_pos,
        "atr_14": _r(atr_vals[-1]),
        "stochastic_k_14": _r(k_vals[-1], 1),
    }


def _daily_returns_by_date(bars: list) -> dict:
    closes = {b["timestamp"][:10]: b["close"] for b in bars}
    dates = sorted(closes)
    return {d: closes[d] / closes[p] - 1 for p, d in zip(dates, dates[1:]) if closes[p]}


def correlation(series: dict) -> dict:
    """Correlation of daily returns, aligned on the dates every symbol traded."""
    returns = {s: _daily_returns_by_date(b) for s, b in series.items() if b}
    symbols = [s for s in returns if len(returns[s]) > 15]
    if len(symbols) < 2:
        return {"error": "need price history for at least two of the symbols",
                "missing": sorted(set(series) - set(symbols))}
    common = sorted(set.intersection(*(set(returns[s]) for s in symbols)))
    if len(common) < 15:
        return {"error": "too few common trading days"}
    matrix = np.corrcoef([[returns[s][d] for d in common] for s in symbols])
    pairs = []
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            pairs.append({"a": symbols[i], "b": symbols[j], "correlation": _r(matrix[i][j], 2)})
    pairs.sort(key=lambda p: -(p["correlation"] or 0))
    return {
        "window": f"{len(common)} common trading days of daily returns",
        "pairs_most_correlated_first": pairs,
        "missing": sorted(set(series) - set(symbols)),
    }


def apply_changes(holdings: list, changes: list) -> tuple[list, list]:
    """Apply share deltas to raw holdings. Returns (new_holdings, notes)."""
    book = {h["symbol"]: dict(h) for h in holdings}
    notes = []
    for ch in changes[:MAX_WHAT_IF_CHANGES]:
        sym = clean_symbol(ch.get("symbol"))
        delta = ch.get("shares_change")
        if not sym or not isinstance(delta, (int, float)) or not math.isfinite(delta):
            notes.append(f"ignored invalid change {ch!r}")
            continue
        current = book.get(sym, {"symbol": sym, "shares": 0.0, "avg_cost": None})
        new_shares = current["shares"] + delta
        if new_shares < -1e-9:
            notes.append(f"{sym}: cannot sell {-delta:g} shares, only {current['shares']:g} held; sold all")
            new_shares = 0.0
        if new_shares <= 1e-9:
            book.pop(sym, None)
        else:
            book[sym] = {**current, "shares": new_shares}
    return list(book.values()), notes


# ─────────────────────────────────────────────────────────────
# Tool definitions (sent to the model) and dispatch
# ─────────────────────────────────────────────────────────────

def _schema(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_SYMBOL = {"type": "string", "description": "Ticker symbol, e.g. AAPL, BRK-B, SPY"}

TOOLS = [
    {
        "name": "get_price_summary",
        "description": (
            "One year of daily prices for any ticker, summarised: latest close, 1-week / 1-month / 3-month / "
            "1-year returns, distance from the 52-week high and low, realised volatility, and RSI, MACD, "
            "moving averages, Bollinger position, ATR and stochastic (several given now and 5 days ago). "
            "Use for any question about how a stock is doing or what its chart looks like."
        ),
        "input_schema": _schema({"symbol": _SYMBOL}),
    },
    {
        "name": "get_fundamentals",
        "description": "Company name, sector, P/E, market cap, 52-week range and 52-week performance for a ticker. "
                       "Some fields can be null when the data source is rate-limited.",
        "input_schema": _schema({"symbol": _SYMBOL}),
    },
    {
        "name": "get_news",
        "description": "Recent headlines (title, source, date) for a ticker, newest first.",
        "input_schema": _schema({"symbol": _SYMBOL}),
    },
    {
        "name": "get_correlation",
        "description": f"Correlation of daily returns over about 3 months between 2 to {MAX_CORR_SYMBOLS} tickers. "
                       "Use for diversification questions (e.g. how related the user's holdings are).",
        "input_schema": _schema({"symbols": {"type": "array", "items": {"type": "string"}}}),
    },
    {
        "name": "portfolio_what_if",
        "description": (
            "Recompute the user's portfolio weights and risk (Sharpe, beta vs S&P 500, annualised volatility, "
            "1-year daily returns) before and after hypothetical trades. shares_change is positive to buy and "
            "negative to sell. Nothing is traded; this is a calculation."
        ),
        "input_schema": _schema({
            "changes": {
                "type": "array",
                "items": _schema({"symbol": _SYMBOL, "shares_change": {"type": "number"}}),
            }
        }),
    },
    {
        "name": "get_macro_history",
        "description": "Recent readings of one US macro series from FRED, newest first, to see a trend. "
                       + "; ".join(f"{k} = {v}" for k, v in MACRO_SERIES.items()),
        "input_schema": _schema({
            "series_id": {"type": "string", "enum": list(MACRO_SERIES)},
            "count": {"type": "integer", "description": f"How many readings, 2 to {MAX_MACRO_POINTS}"},
        }),
    },
]
for _tool in TOOLS:
    _tool["strict"] = True
TOOL_NAMES = [t["name"] for t in TOOLS]


def _book_view(holdings: list, priced: dict) -> dict:
    values = {h["symbol"]: h["shares"] * priced[h["symbol"]] for h in holdings if priced.get(h["symbol"])}
    total = sum(values.values())
    weights = {s: _r(v / total * 100, 1) for s, v in sorted(values.items(), key=lambda kv: -kv[1])} if total else {}
    return {"total_value": _r(total), "weights_pct": weights}


def run_tool(name: str, args: dict, data: SkiData) -> dict:
    """Execute one tool call. Raises ValueError for bad input (reported to the model)."""
    if name in ("get_price_summary", "get_fundamentals", "get_news"):
        sym = clean_symbol(args.get("symbol"))
        if not sym:
            raise ValueError("symbol is required")
        if name == "get_price_summary":
            bars = data.bars(sym, "1y")
            return price_summary(sym, bars) if bars else {"symbol": sym, "error": "no price data for this symbol"}
        if name == "get_fundamentals":
            row = data.fundamentals(sym)
            return row or {"symbol": sym, "error": "no fundamental data for this symbol"}
        articles = data.news(sym)
        return {
            "symbol": sym,
            "headlines": [
                {"title": a["title"], "source": a.get("source"), "date": (a.get("published_at") or "")[:10]}
                for a in articles[:8]
            ],
        } if articles else {"symbol": sym, "headlines": [], "note": "no recent headlines found"}

    if name == "get_correlation":
        syms = list(dict.fromkeys(clean_symbol(s) for s in args.get("symbols") or []))
        syms = [s for s in syms if s][:MAX_CORR_SYMBOLS]
        if len(syms) < 2:
            raise ValueError("give at least two symbols")
        return correlation({s: data.bars(s, "3mo") for s in syms})

    if name == "portfolio_what_if":
        before = data.holdings()
        if not before:
            return {"error": "the user has no portfolio to modify"}
        after, notes = apply_changes(before, args.get("changes") or [])
        symbols = {h["symbol"] for h in before} | {h["symbol"] for h in after}
        priced = {}
        for s in symbols:
            bars = data.bars(s, "1y")
            priced[s] = bars[-1]["close"] if bars else None
        unpriced = sorted(s for s in symbols if not priced[s])

        def side(book):
            metrics, reason = data.risk(book) if book else (None, "empty portfolio")
            return {**_book_view(book, priced), "risk": metrics, "risk_unavailable_reason": None if metrics else reason}

        return {"before": side(before), "after": side(after), "notes": notes, "unpriced_symbols": unpriced}

    if name == "get_macro_history":
        sid = args.get("series_id")
        if sid not in MACRO_SERIES:
            raise ValueError(f"series_id must be one of {list(MACRO_SERIES)}")
        count = args.get("count")
        count = max(2, min(MAX_MACRO_POINTS, int(count))) if isinstance(count, (int, float)) else 12
        obs = data.macro_history(sid, count)
        return {
            "series_id": sid,
            "meaning": MACRO_SERIES[sid],
            "readings_newest_first": [{"date": o["date"], "value": _r(float(o["value"]), 3)} for o in obs],
        } if obs else {"series_id": sid, "error": "FRED returned no data"}

    raise ValueError(f"unknown tool {name}")


def tool_result_block(tool_use_id: str, name: str, args: dict, data: SkiData) -> tuple[dict, Optional[dict]]:
    """Run a tool and wrap it as a tool_result content block.

    Returns (block, output) where output is the parsed result for later
    grounding checks, or None when the tool failed.
    """
    try:
        output = run_tool(name, args or {}, data)
        return {"type": "tool_result", "tool_use_id": tool_use_id,
                "content": json.dumps(output, default=str)}, output
    except Exception as exc:  # reported to the model so it can recover or say so
        message = str(exc) if isinstance(exc, ValueError) else "the data source failed; try again later"
        return {"type": "tool_result", "tool_use_id": tool_use_id, "is_error": True, "content": message}, None
