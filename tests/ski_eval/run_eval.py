"""Run the Ski eval against the real Claude API, on fixed fixture data.

    ANTHROPIC_API_KEY=... python tests/ski_eval/run_eval.py [--only ID ...] [--repeat N]

Every data source (prices, fundamentals, news, FRED, option chains, portfolio pricing) is
replaced with deterministic fixtures, so a score change comes from Ski, not
the market. Requests go through the real /chat endpoint via Flask's test
client, so the prompt, tool loop and grounding check are the production code.
Web search, when Ski uses it, is real.

Cost: about 23 questions x 1 to 3 model calls on Claude Haiku 5.5, which is
roughly $0.01 to $0.05 a run plus $0.01 per web search Ski chooses to run.
Results are written to tests/ski_eval/results/ (gitignored).
"""

import argparse
import datetime
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [ROOT, os.path.join(ROOT, "Plotly dashboard"), HERE]

from cases import CASES, HELD_OUT, SAMPLE_PORTFOLIO  # noqa: E402
from graders import grade  # noqa: E402

# Symbol -> (start price, daily drift, wobble). NVDA rallies, TSLA falls.
_SHAPES = {
    "NVDA": (60.0, 0.0030, 0.012), "AAPL": (170.0, 0.0006, 0.008), "TSLA": (300.0, -0.0012, 0.020),
    "MSFT": (380.0, 0.0008, 0.007), "SPY": (480.0, 0.0005, 0.005), "QQQ": (400.0, 0.0007, 0.007),
    "GOOGL": (160.0, 0.0009, 0.009),
    "BTC-USD": (60000.0, 0.0010, 0.030), "ETH-USD": (3000.0, -0.0008, 0.035),
}
_FUNDAMENTALS = {
    "NVDA": {"name": "NVIDIA", "sector": "Technology", "pe": 48.2, "market_cap": 3.1e12},
    "AAPL": {"name": "Apple", "sector": "Technology", "pe": 31.4, "market_cap": 3.0e12},
    "TSLA": {"name": "Tesla", "sector": "Consumer Cyclical", "pe": 72.9, "market_cap": 6.4e11},
    "MSFT": {"name": "Microsoft", "sector": "Technology", "pe": 35.6, "market_cap": 3.2e12},
    "SPY": {"name": "SPDR S&P 500 ETF", "sector": "ETF", "pe": None, "market_cap": None},
    # As on Render, where Yahoo's .info is blocked: no P/E, market cap or sector.
    "GOOGL": {"name": "GOOGL", "sector": "—", "pe": None, "market_cap": None},
}
# What tracker/sec_fundamentals.py computes from filings (price-independent part).
_FILINGS = {
    "GOOGL": {"source": "SEC filings (10-Q/10-K), computed by Tradeski", "eps_trailing_4q": 9.1,
              "latest_quarter_end": "2026-09-30", "revenue_trailing_4q_usd": 402_000_000_000,
              "revenue_growth_yoy_pct": 13.2, "net_margin_trailing_pct": 28.4,
              "shares_outstanding": 12_100_000_000},
}


def fixture_filings(symbol: str, price):
    from tracker import sec_fundamentals
    base = _FILINGS.get(symbol)
    return sec_fundamentals.with_price(base, price or fixture_bars(symbol)[-1]["close"]) if base else None


def fixture_bars(symbol: str, period: str = "1y", _interval: str = "1d") -> list:
    if symbol not in _SHAPES:
        return []
    start, drift, wobble = _SHAPES[symbol]
    n = {"3mo": 63, "6mo": 126}.get(period, 252)
    # The series ends yesterday, as live data would; values don't depend on the date.
    day0 = datetime.date.today() - datetime.timedelta(days=252)
    # Each day's move = a wave every symbol shares (the market) + one of its own,
    # so symbols correlate partly, as real ones do. (Seeding the wave by ticker
    # length alone made NVDA, AAPL and TSLA move identically: correlation 1.0.)
    seed = sum(map(ord, symbol))
    own_period, own_phase = 1.7 + (seed % 7) * 0.45, seed % 11
    bars, price = [], start
    for i in range(252):
        move = 0.9 * math.sin(i / 2.7) + 0.45 * math.sin(i / own_period + own_phase)
        price *= 1 + drift + wobble * move
        bars.append({"timestamp": f"{day0 + datetime.timedelta(days=i)}T00:00:00", "open": price,
                     "high": price * 1.012, "low": price * 0.988, "close": round(price, 4), "volume": 1_000_000})
    return bars[-n:]


def fixture_fundamentals(symbol: str):
    if symbol not in _FUNDAMENTALS:
        return None
    closes = [b["close"] for b in fixture_bars(symbol)]
    return {"symbol": symbol, **_FUNDAMENTALS[symbol], "price": round(closes[-1], 2),
            "high_52w": round(max(closes), 2), "low_52w": round(min(closes), 2),
            "perf_52w": round((closes[-1] / closes[0] - 1) * 100, 1)}


def fixture_news(symbol: str) -> list:
    headlines = {
        "TSLA": ["Tesla deliveries fall short of estimates", "Tesla cuts Model Y prices in China"],
        "NVDA": ["NVIDIA beats on data-centre revenue", "Chip export rules tightened again"],
        "AAPL": ["Apple services revenue hits record", "iPhone demand steady, analysts say"],
    }.get(symbol, [])
    return [{"title": t, "source": "Fixture Wire", "published_at": "2026-11-0%dT12:00:00Z" % (i + 1),
             "url": "", "sentiment": 0.0, "sentiment_label": "neutral"} for i, t in enumerate(headlines)]


_MACRO = {
    "UNRATE": [4.4, 4.3, 4.3, 4.2, 4.2, 4.1, 4.1, 4.0, 4.0, 3.9, 3.9, 3.9],
    "CPIAUCSL": [2.6, 2.7, 2.8, 2.9, 3.0, 3.0, 3.1, 3.2, 3.3, 3.3, 3.4, 3.5],
    "FEDFUNDS": [3.88] * 4 + [4.13] * 4 + [4.33] * 4,
    "DGS10": [4.1, 4.2, 4.2, 4.3, 4.4, 4.3, 4.2, 4.1, 4.0, 4.1, 4.2, 4.3],
    "T10Y2Y": [0.55, 0.52, 0.5, 0.48, 0.45, 0.4, 0.38, 0.35, 0.3, 0.28, 0.25, 0.2],
    "BAMLH0A0HYM2": [3.1, 3.0, 3.0, 2.9, 2.9, 2.8, 2.9, 3.0, 3.1, 3.2, 3.2, 3.3],
    "GDP": [31000 - 250 * i for i in range(12)],
    "DCOILWTICO": [89.5, 88.1, 86.0, 84.7, 82.3, 80.9, 79.2, 78.0, 77.4, 76.1, 75.0, 74.2],
    "PAYEMS": [165, 60, 120, 140, 95, 180, 150, 130, 110, 160, 175, 140],
}


def fixture_fred(series_id: str, _key: str, limit: int = 2) -> list:
    values = _MACRO.get(series_id, [])[:limit]
    # Monthly readings, newest first, ending October 2026.
    return [{"date": f"{2026 + (9 - i) // 12}-{(9 - i) % 12 + 1:02d}-01", "value": str(v)}
            for i, v in enumerate(values)]


MACRO_CONTEXT = (
    "MACRO CONTEXT (FRED, latest readings, newest first):\n"
    "  CPI YoY: 2.6% (prior 2.7%)\n  Fed funds: 3.88% (prior 3.88%)\n  Unemployment: 4.4% (prior 4.3%)\n"
    "  10Y yield: 4.1% (prior 4.2%)\n  10Y-2Y spread: 0.55 (prior 0.52)\n  HY spread: 3.1 (prior 3.0)"
)


def chart_context() -> dict:
    """The AAPL chart snapshot the dashboard would send, computed from the fixture bars."""
    from tracker.analyzer import bollinger_bands, ema, macd, rsi, sma, volatility, zscore
    closes = [b["close"] for b in fixture_bars("AAPL")]
    m, s, h = macd(closes)
    up, lo = bollinger_bands(closes)
    return {"symbol": "AAPL", "timeframe": "1Y", "close": closes[-1], "rsi": rsi(closes)[-1], "macd": m[-1],
            "macd_signal": s[-1], "macd_histogram": h[-1], "macd_histogram_prev": h[-2],
            "sma20": sma(closes, 20)[-1], "sma50": sma(closes, 50)[-1], "ema20": ema(closes, 20)[-1],
            "upper_band": up[-1], "lower_band": lo[-1], "zscore": zscore(closes)[-1],
            "volatility": volatility(closes)[-1]}


def fixture_expirations(symbol: str) -> list:
    """Five expiries, one week to two months out, for any symbol with fixture prices."""
    if symbol not in _SHAPES:
        return []
    from tracker import options as opt
    today = datetime.datetime.now(opt._ET).date()   # expiries count in New York time
    return [(today + datetime.timedelta(days=d)).isoformat() for d in (7, 14, 28, 35, 63)]


def fixture_option_chain(symbol: str, expiry: str):
    """A chain priced with Black-Scholes at a skewed volatility (puts dearer, as in
    real markets), with put volume and open interest about 1.3x the calls'."""
    from tracker import options as opt
    if symbol not in _SHAPES:
        return None
    spot = fixture_bars(symbol)[-1]["close"]
    base_vol = _SHAPES[symbol][2] * math.sqrt(252) + 0.05
    T = max(opt.year_fraction(expiry), 1 / 365)
    step = max(round(spot * 0.025, 0), 1.0)
    rows = {"calls": [], "puts": []}
    for i in range(-12, 13):
        K = round(spot / step) * step + i * step
        sigma = base_vol * (1 + 0.8 * max(0.0, 1 - K / spot))
        weight = math.exp(-((K / spot - 1) / 0.06) ** 2)
        for kind, mult in (("call", 1.0), ("put", 1.3)):
            p = opt.bs_price(kind, spot, K, T, 0.04, sigma)
            half = max(0.02, p * 0.02)
            rows[kind + "s"].append({
                "contractSymbol": f"{symbol}{expiry}{kind[0].upper()}{K:g}", "strike": K,
                "bid": round(max(p - half, 0.0), 2), "ask": round(p + half, 2), "lastPrice": round(p, 2),
                "volume": int(2000 * weight * mult), "openInterest": int(9000 * weight * mult) + 50,
                "impliedVolatility": sigma,
            })
    return {"symbol": symbol, "spot": spot, "dividend_yield": 0.0, "market_state": "REGULAR", **rows}


def install_fixtures(set_attr=setattr):
    """Point every data source in app.py at the fixtures.

    ``set_attr`` lets a test pass pytest's monkeypatch.setattr so the
    originals come back afterwards.
    """
    import app
    from cache import SimpleCache
    os.environ.setdefault("FRED_API_KEY", "fixture")
    set_attr(app, "_cache", SimpleCache())
    set_attr(app.limiter, "enabled", False)
    set_attr(app, "get_ohlc_history", fixture_bars)
    set_attr(app, "get_stock_price", lambda s: fixture_bars(s)[-1]["close"] if fixture_bars(s) else None)
    set_attr(app, "_fetch_screener_row", fixture_fundamentals)
    set_attr(app, "_cached_filings", fixture_filings)
    set_attr(app, "_fetch_cached_news", fixture_news)
    set_attr(app, "fetch_fred_observations", fixture_fred)
    set_attr(app, "get_option_expirations", fixture_expirations)
    set_attr(app, "get_option_chain", fixture_option_chain)
    set_attr(app, "get_eod_options", lambda s, base: None)
    set_attr(app, "get_eod_index", lambda base: None)
    set_attr(app, "get_ex_dividend", lambda s: None)
    set_attr(app, "_get_macro_context", lambda: MACRO_CONTEXT)
    _record_evidence(app, set_attr)
    return app


# What the last /chat call checked its numbers against, and the raw text blocks of
# its answer, so a results file can be re-graded (--regrade) and diagnosed later.
CAPTURE: dict = {}


def _record_evidence(app, set_attr) -> None:
    real_check, real_reply_text = app.ski_grounding.check, app._reply_text

    def check(reply, texts, objects):
        CAPTURE["evidence"] = [list(texts), list(objects)]
        return real_check(reply, texts, objects)

    def reply_text(response):
        CAPTURE["blocks"] = [{"text": getattr(b, "text", ""), "citations": len(getattr(b, "citations", None) or [])}
                             for b in response.content if getattr(b, "type", None) == "text"]
        return real_reply_text(response)

    set_attr(app.ski_grounding, "check", check)
    set_attr(app, "_reply_text", reply_text)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", help="case ids to run")
    parser.add_argument("--repeat", type=int, default=1, help="runs per case (answers vary run to run)")
    parser.add_argument("--set", choices=["main", "held-out", "all"], default="all",
                        help="which cases: the main set, the held-out set (see cases.py), or both")
    parser.add_argument("--regrade", metavar="RESULTS_JSON",
                        help="re-grade a saved results file with the current graders; no API calls")
    args = parser.parse_args()

    if args.regrade:
        return regrade(args.regrade)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY to run the eval (it calls the real Claude API).")

    app = install_fixtures()
    client = app.app.test_client()
    pool = {"main": CASES, "held-out": HELD_OUT, "all": CASES + HELD_OUT}[args.set]
    cases = [c for c in pool if not args.only or c["id"] in args.only]
    ctx = chart_context()

    results = []
    for case in cases:
        for run in range(args.repeat):
            started = time.time()
            CAPTURE.clear()
            r = client.post("/chat", json={"message": case["q"], "history": [], "symbol": "AAPL",
                                           "chart_context": ctx, "sample_portfolio": SAMPLE_PORTFOLIO})
            body = r.get_json(silent=True) or {"error": f"HTTP {r.status_code}"}
            failures = grade(case, body)
            results.append({"id": case["id"], "group": case["group"], "held_out": bool(case.get("held_out")),
                            "run": run, "question": case["q"],
                            "seconds": round(time.time() - started, 1), "passed": not failures,
                            "failures": failures, **{k: body.get(k) for k in
                                                     ("reply", "tools_used", "grounded", "ungrounded_figures",
                                                      "error")},
                            "evidence": CAPTURE.get("evidence"), "blocks": CAPTURE.get("blocks")})
            mark = "PASS" if not failures else "FAIL"
            print(f"{mark}  {case['id']:<22} {results[-1]['seconds']:>5}s  tools={body.get('tools_used')}")
            for f in failures:
                print(f"        - {f}")

    passed = sum(r["passed"] for r in results)
    print(f"\n{passed}/{len(results)} passed")
    for group in dict.fromkeys(c["group"] for c in cases):
        rows = [r for r in results if r["group"] == group]
        print(f"  {group:<8} {sum(r['passed'] for r in rows)}/{len(rows)}")
    grounded = [r for r in results if r["grounded"] is not None]
    if grounded:
        print(f"  grounded replies: {sum(r['grounded'] for r in grounded)}/{len(grounded)}")

    out_dir = os.path.join(HERE, "results")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"model": app.SKI_MODEL, "results": results}, f, indent=2)
    print(f"\nwrote {path}")


def summarize(results: list) -> None:
    """Print pass rates, with the held-out cases reported on their own."""
    for label, rows in (("main set", [r for r in results if not r.get("held_out")]),
                        ("held-out set", [r for r in results if r.get("held_out")])):
        if not rows:
            continue
        print(f"\n{label}: {sum(r['passed'] for r in rows)}/{len(rows)} passed")
        for group in dict.fromkeys(r["group"] for r in rows):
            g = [r for r in rows if r["group"] == group]
            print(f"  {group:<8} {sum(r['passed'] for r in g)}/{len(g)}")
        grounded = [r for r in rows if r["grounded"] is not None]
        if grounded:
            print(f"  grounded replies: {sum(r['grounded'] for r in grounded)}/{len(grounded)}")


def regrade(path: str) -> None:
    """Re-grade saved replies with today's graders and grounding check.

    The grounding verdict is recomputed only when the file kept the evidence;
    otherwise the saved verdict is re-checked against the saved figures alone.
    """
    from tracker import ski_grounding
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    by_id = {c["id"]: c for c in CASES + HELD_OUT}
    results = []
    for r in saved["results"]:
        body = {k: r.get(k) for k in ("reply", "tools_used", "grounded", "ungrounded_figures", "error")}
        if r.get("evidence"):
            texts, objects = r["evidence"]
            # Results saved before cited block text counted as evidence (2026-11-15).
            texts = texts + [b["text"] for b in r.get("blocks") or [] if b.get("citations")]
            g = ski_grounding.check(r["reply"] or "", texts, objects)
            body["grounded"], body["ungrounded_figures"] = g["grounded"], g["ungrounded"]
        failures = grade(by_id[r["id"]], body)
        results.append({**r, "grounded": body["grounded"], "passed": not failures, "failures": failures})
        if failures:
            print(f"FAIL  {r['id']:<22} run {r['run']}")
            for fail in failures:
                print(f"        - {fail}")
    print(f"model: {saved.get('model')}")
    summarize(results)


if __name__ == "__main__":
    main()
