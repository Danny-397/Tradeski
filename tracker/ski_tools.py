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

from tracker import options as opt
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
    # (symbol, price) -> fundamentals computed from SEC filings, or None
    filings: Optional[Callable[[str, Optional[float]], Optional[dict]]] = None
    # (symbol, target days to expiry) -> cleaned option chain (tracker.options), or None
    options: Optional[Callable[[str, int], Optional[dict]]] = None


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


BENCHMARK = "SPY"


def vs_benchmark(summary: dict, bars: list, bench_bars: list) -> Optional[dict]:
    """The stock's returns against the S&P 500 (SPY), and its beta to it.

    Computed here so the model never has to subtract two returns itself: that
    is the question "is it the stock or the market?" answered in numbers.
    """
    bench = price_summary(BENCHMARK, bench_bars) if bench_bars else {}
    if "return_pct" not in summary or "return_pct" not in bench:
        return None
    excess = {}
    for k, mine in summary["return_pct"].items():
        theirs = bench["return_pct"].get(k)
        excess[k] = _r(mine - theirs, 1) if mine is not None and theirs is not None else None

    a, b = _daily_returns_by_date(bars), _daily_returns_by_date(bench_bars)
    common = sorted(set(a) & set(b))
    beta = corr = None
    if len(common) >= 60:
        x = np.array([b[d] for d in common])
        y = np.array([a[d] for d in common])
        var = float(np.var(x))
        if var > 0:
            beta = _r(float(np.cov(y, x, ddof=0)[0][1]) / var, 2)
            corr = _r(float(np.corrcoef(y, x)[0][1]), 2)
    return {
        "benchmark": "S&P 500 (SPY)",
        "benchmark_return_pct": bench["return_pct"],
        "excess_return_pct_points": excess,
        "beta_vs_sp500": beta,
        "correlation_with_sp500": corr,
        "days_for_beta": len(common),
    }


def clean_fundamentals(row: Optional[dict]) -> dict:
    """Drop blank fields ("—" placeholders, nulls) so the model is not shown empty data."""
    return {k: v for k, v in (row or {}).items() if v not in (None, "", "—", "-")}


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
            "moving averages, Bollinger position, ATR and stochastic (several given now and 5 days ago), plus "
            "the same returns for the S&P 500, the stock's excess return over it, and its beta to it. "
            "Use for any question about how a stock is doing, what its chart looks like, or whether a move "
            "is the stock or the whole market."
        ),
        "input_schema": _schema({"symbol": _SYMBOL}),
    },
    {
        "name": "get_fundamentals",
        "description": "Company name, sector, P/E, market cap, 52-week range and 52-week performance for a ticker. "
                       "When the market-data source lacks P/E or market cap, a from_filings section gives trailing "
                       "EPS, P/E, market cap, revenue growth and net margin computed from the company's SEC "
                       "filings. Missing fields are omitted, never guessed.",
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
            "1-year daily returns) before and after hypothetical trades, and the change in each. "
            "shares_change is positive to buy and negative to sell. Nothing is traded; this is a calculation."
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
    {
        "name": "get_options_overview",
        "description": (
            "What a ticker's listed options imply, for the expiry nearest days_to_expiry days out: at-the-money "
            "implied volatility next to the stock's 30-day realised volatility, the market-implied expected move "
            "by expiry (plus or minus), put/call ratios by volume and open interest, and the strikes with the "
            "most open interest. Use for questions about options sentiment, whether options look expensive, "
            "or how big a move the market is pricing (e.g. into earnings)."
        ),
        "input_schema": _schema({"symbol": _SYMBOL, "days_to_expiry": {"type": "integer"}}),
    },
    {
        "name": "analyze_option_strategy",
        "description": (
            "Build a standard options strategy on a ticker from its live chain, at the expiry nearest "
            "days_to_expiry days, and analyse it: the legs and strikes chosen, net cost or credit, max profit, "
            "max loss, break-evens, the market-implied probability of profit, and net Greeks. Strikes follow "
            "fixed rules (at the money, or short strikes near 0.30 delta, 0.20 for the condor). Prices are "
            "bid/ask midpoints from delayed quotes. The user can adjust it in the Options tab."
        ),
        "input_schema": _schema({
            "symbol": _SYMBOL,
            "strategy": {"type": "string", "enum": list(opt.PRESETS)},
            "days_to_expiry": {"type": "integer"},
        }),
    },
    {
        "name": "rank_option_strategies",
        "description": (
            "Rank the standard options strategies for a view: the user thinks the ticker will be at target_price "
            "around days_to_expiry days out. Returns the best five for that view (profit if the stock is exactly "
            "at the target at expiry, that profit per dollar the strategy can lose, cost, worst case, break-evens, "
            "chance of profit) and what option prices imply about the target (chance of ending beyond it, and "
            "roughly of trading there at some point). Use for 'what's the best way to bet X reaches Y'. "
            "The user can see and adjust the full ranking in the Options page's Compare & choose tab."
        ),
        "input_schema": _schema({
            "symbol": _SYMBOL,
            "target_price": {"type": "number"},
            "days_to_expiry": {"type": "integer"},
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


def _fundamentals(sym: str, data: SkiData) -> dict:
    row = clean_fundamentals(data.fundamentals(sym))
    if data.filings and ("pe" not in row or "market_cap" not in row):
        try:
            filed = data.filings(sym, row.get("price"))
        except Exception:
            filed = None
        if filed:
            row = {"symbol": sym, **row, "from_filings": clean_fundamentals(filed)}
    if not row:
        return {"symbol": sym, "error": "no fundamental data for this symbol"}
    row.setdefault("symbol", sym)
    if "pe" not in row and "pe_trailing" not in row.get("from_filings", {}):
        row["note"] = ("P/E and market cap are not available from Tradeski's data sources right now. "
                       "Say so, or use web_search if the user needs them.")
    return row


def run_tool(name: str, args: dict, data: SkiData) -> dict:
    """Execute one tool call. Raises ValueError for bad input (reported to the model)."""
    if name in ("get_price_summary", "get_fundamentals", "get_news"):
        sym = clean_symbol(args.get("symbol"))
        if not sym:
            raise ValueError("symbol is required")
        if name == "get_price_summary":
            bars = data.bars(sym, "1y")
            if not bars:
                return {"symbol": sym, "error": "no price data for this symbol"}
            out = price_summary(sym, bars)
            if sym != BENCHMARK and "error" not in out:
                rel = vs_benchmark(out, bars, data.bars(BENCHMARK, "1y"))
                if rel:
                    out["vs_sp500"] = rel
            return out
        if name == "get_fundamentals":
            return _fundamentals(sym, data)
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

        b, a = side(before), side(after)
        change = {}
        if b["risk"] and a["risk"]:
            for k in ("beta", "volatility", "sharpe"):
                if b["risk"].get(k) is not None and a["risk"].get(k) is not None:
                    change[k] = _r(a["risk"][k] - b["risk"][k], 2)
        if b["total_value"] is not None and a["total_value"] is not None:
            change["total_value"] = _r(a["total_value"] - b["total_value"])
        return {"before": b, "after": a, "change_after_minus_before": change,
                "notes": notes, "unpriced_symbols": unpriced}

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

    if name in ("get_options_overview", "analyze_option_strategy", "rank_option_strategies"):
        return _options_tool(name, args, data)

    raise ValueError(f"unknown tool {name}")


def _options_tool(name: str, args: dict, data: SkiData) -> dict:
    sym = clean_symbol(args.get("symbol"))
    if not sym:
        raise ValueError("symbol is required")
    if data.options is None:
        return {"symbol": sym, "error": "options data is not available here"}
    dte = args.get("days_to_expiry")
    dte = max(1, min(730, int(dte))) if isinstance(dte, (int, float)) else 30
    chain = data.options(sym, dte)
    if not chain:
        return {"symbol": sym, "error": "no option data came back: the symbol may have no listed options, or the "
                                        "data source may be refusing requests right now. Say which is unknown."}
    base = {"symbol": sym, "expiry": chain["expiry"], "days_to_expiry": chain["dte"], "spot": _r(chain["spot"])}
    if name == "rank_option_strategies":
        target = args.get("target_price")
        if not isinstance(target, (int, float)) or target <= 0:
            raise ValueError("target_price must be a positive number")
        rows = opt.compare_strategies(chain, target=float(target), symbol=sym)
        odds = opt.price_odds(float(target), chain["spot"], chain["years"], chain["rate"],
                              chain["dividend_yield"], chain["atm_iv"])
        return {**base, "target_price": _r(float(target)),
                "move_to_target_pct": _r((float(target) / chain["spot"] - 1) * 100, 1),
                "chance_ends_beyond_target":
                    (odds["above"] if target >= chain["spot"] else odds["below"]) if odds else None,
                "chance_trades_at_target_before_expiry": odds["touch"] if odds else None,
                "ranked": [{"strategy": r["name"],
                            "legs": [{"action": "buy" if leg["qty"] > 0 else "sell", "type": leg["type"],
                                      "strike": leg["strike"]} for leg in r["legs"]],
                            "pnl_if_at_target": r["pnl_at_target"],
                            "profit_per_dollar_at_risk": r["reward_risk_at_target"],
                            "net_debit": r["net_debit"], "max_loss": r["max_loss"],
                            "unlimited_loss": r["unlimited_loss"],
                            "max_profit": r["max_profit"], "unlimited_profit": r["unlimited_profit"],
                            "breakevens": r["breakevens"], "prob_profit": r["prob_profit"]} for r in rows[:5]],
                "notes": "Ranked: money-makers at the target first, by profit at the target per dollar they can lose. "
                         "If the stock doesn't get there, the worst case applies. Prices are delayed midpoints."}
    if name == "get_options_overview":
        iv, hv = chain.get("atm_iv"), chain.get("realized_vol_30d")
        move = chain.get("expected_move")

        def top(side):
            return [{"strike": c["strike"], "open_interest": c["open_interest"]}
                    for c in sorted(side, key=lambda c: -c["open_interest"])[:3] if c["open_interest"]]

        return {**base,
                "atm_implied_vol_pct": _r(iv * 100, 1) if iv else None,
                "realized_vol_30d_pct": _r(hv * 100, 1) if hv else None,
                "implied_minus_realized_pct_points": _r((iv - hv) * 100, 1) if iv and hv else None,
                "expected_move": _r(move) if move else None,
                "expected_move_pct": _r(move / chain["spot"] * 100, 1) if move else None,
                "put_call_volume_ratio": chain.get("put_call_volume"),
                "put_call_open_interest_ratio": chain.get("put_call_oi"),
                "most_open_interest_calls": top(chain["calls"]),
                "most_open_interest_puts": top(chain["puts"]),
                "quotes": (f"end-of-day quotes saved at {chain.get('quotes_as_of')}"
                           if chain.get("source") == "end_of_day"
                           else "delayed; outside market hours they are the last session's")}
    strategy = args.get("strategy")
    if strategy not in opt.PRESETS:
        raise ValueError(f"strategy must be one of {list(opt.PRESETS)}")
    legs = opt.build_preset(strategy, chain)
    res = opt.analyze(legs, chain["spot"], chain["years"], chain["rate"], chain["dividend_yield"],
                      sigma=chain["atm_iv"], symbol=sym, expiry=chain["expiry"], points=3)
    return {**base, "strategy": opt.PRESETS[strategy],
            "legs": [{"action": "buy" if leg["qty"] > 0 else "sell", "quantity": abs(leg["qty"]),
                      "type": leg["type"], "strike": leg["strike"], "price_per_share": _r(leg["price"])}
                     for leg in legs],
            **{k: res[k] for k in ("net_debit", "max_profit", "max_loss", "unlimited_profit", "unlimited_loss",
                                   "breakevens", "prob_profit", "spread_cost", "greeks", "summary")},
            "notes": "net_debit > 0 is paid, < 0 is collected; dollar amounts are per position (100 shares a "
                     "contract); spread_cost is the extra paid by crossing the bid/ask spread."}


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


_CALL_LABELS = {
    "get_price_summary": "{symbol} price and chart",
    "get_fundamentals": "{symbol} fundamentals",
    "get_news": "{symbol} news",
}


def describe_call(name: str, args: dict) -> str:
    """A short label for what a tool call looked up, shown under Ski's reply."""
    args = args or {}
    if name in _CALL_LABELS:
        return _CALL_LABELS[name].format(symbol=clean_symbol(args.get("symbol")) or "?")
    if name == "get_correlation":
        syms = [clean_symbol(s) for s in (args.get("symbols") or [])][:4]
        return "correlation of " + ", ".join(s for s in syms if s)
    if name == "portfolio_what_if":
        return "portfolio what-if"
    if name == "get_macro_history":
        return f"{args.get('series_id', 'macro')} history"
    if name == "get_options_overview":
        return f"{clean_symbol(args.get('symbol')) or '?'} options"
    if name == "rank_option_strategies":
        target = args.get("target_price")
        return f"{clean_symbol(args.get('symbol')) or '?'} strategies for ${target:g}" \
            if isinstance(target, (int, float)) else "ranking option strategies"
    if name == "analyze_option_strategy":
        label = opt.PRESETS.get(args.get("strategy"), "options strategy").lower()
        return f"{clean_symbol(args.get('symbol')) or '?'} {label}"
    if name == "web_search":
        return "web search"
    return name
