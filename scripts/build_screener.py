"""Build the stock screener's data: every US-listed common stock, one row each.

    python scripts/build_screener.py --out-dir out [--prev old/fundamentals.json] [--limit N]

Writes out/screener.json (what the browser loads) and out/fundamentals.json
(the raw inputs kept between runs; only this script reads it).

Universe: Nasdaq Trader's public symbol directory (everything listed on
Nasdaq, NYSE and NYSE American), minus ETFs, test issues, warrants, units,
rights, preferreds, notes and blank-check companies.

Prices: a year of daily bars for the whole universe, downloaded in batches;
every technical column (performance, RSI, moving averages, 52-week range,
relative volume, volatility, beta, ATR) is computed here from those bars.

Fundamentals: Yahoo's per-company summary (shares, EPS, revenue, margins,
growth, analyst targets...), for the 1,000 stalest companies each run (large caps first), so the
whole universe turns over about every six trading days (they change
quarterly). If Yahoo starts refusing, the build backs off, then stops and keeps
each stock's previous values (from --prev); each row records the date its
fundamentals are from. Ratios that move with the price (market
cap, P/E, P/S, P/B, dividend yield, analyst upside) are recomputed from today's
close every day, so they are never stale even when the fundamentals are.

Runs in GitHub Actions (.github/workflows/screener.yml), not on Render: Yahoo
answers GitHub's runners but often refuses Render. The output is published to
the `screener-data` branch, replaced each run, so daily data adds no history.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

DIRECTORY = "https://www.nasdaqtrader.com/dynamic/SymDir/{}.txt"
USER_AGENT = "Tradeski-screener/1.0 (+https://tradeski.dev)"
BATCH = 200
EXCLUDE = re.compile(
    r"\b(warrants?|rights?|units?|preferred|preference|notes due|debentures?|subordinated|"
    r"acquisition corp|acquisition company|blank check|trust preferred|redeemable)\b|%", re.I)
# The columns, in order. The file is columnar: {"fields": FIELDS, "rows": [[...], ...]}.
FIELDS = [
    "symbol", "name", "exchange", "sector", "industry", "country",
    "price", "change", "volume", "avg_volume", "rel_volume", "market_cap",
    "pe", "forward_pe", "peg", "ps", "pb", "dividend_yield", "eps",
    "revenue_growth", "eps_growth", "gross_margin", "operating_margin", "profit_margin",
    "roe", "debt_equity", "current_ratio",
    "rating", "upside", "analysts", "short_float", "institutional", "earnings_date",
    "perf_1w", "perf_1m", "perf_3m", "perf_6m", "perf_ytd", "perf_1y",
    "high_52w", "low_52w", "from_high", "from_low", "rsi", "sma20", "sma50", "sma200",
    "volatility", "beta", "atr", "fundamentals_date",
]
# Yahoo summary fields kept between runs (raw inputs, not the price-based ratios).
FUND_KEYS = [
    "name", "sector", "industry", "country", "shares", "eps", "forward_eps", "revenue", "book_value",
    "dividend_rate", "peg", "revenue_growth", "eps_growth", "gross_margin", "operating_margin",
    "profit_margin", "roe", "debt_equity", "current_ratio", "rating", "target", "analysts",
    "short_float", "institutional", "earnings_date", "fundamentals_date",
]
EXCHANGES = {"Q": "NASDAQ", "N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}


# ── universe ──────────────────────────────────────────────────

def clean_name(name: str) -> str:
    """ "Agilent Technologies, Inc. Common Stock" -> "Agilent Technologies, Inc." """
    name = re.split(r"\s+-\s+|\s+(Common Stock|Ordinary Shares|Class [A-C] (Common|Ordinary)|"
                    r"American Depositary Shares?|Common Shares|Shares of Beneficial Interest)\b", name)[0]
    return name.strip(" ,")


def parse_directory(text: str, kind: str) -> list:
    """[(yahoo symbol, name, exchange)] for the common stocks in one directory file."""
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
    if not lines:
        return []
    header = lines[0].split("|")
    sym_col = "Symbol" if kind == "nasdaqlisted" else "ACT Symbol"
    out = []
    for line in lines[1:]:
        row = dict(zip(header, line.split("|")))
        sym, name = row.get(sym_col, ""), row.get("Security Name", "")
        if row.get("ETF") != "N" or row.get("Test Issue") != "N" or EXCLUDE.search(name):
            continue
        if not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", sym):
            continue
        exchange = "NASDAQ" if kind == "nasdaqlisted" else EXCHANGES.get(row.get("Exchange", ""), "Other")
        out.append((sym.replace(".", "-"), clean_name(name), exchange))
    return out


def load_universe() -> list:
    import requests
    seen, out = set(), []
    for kind in ("nasdaqlisted", "otherlisted"):
        resp = requests.get(DIRECTORY.format(kind), headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        for item in parse_directory(resp.text, kind):
            if item[0] not in seen:
                seen.add(item[0])
                out.append(item)
    return out


# ── technicals ────────────────────────────────────────────────

def _r(x, digits=2):
    return None if x is None or not math.isfinite(x) else round(float(x), digits)


def _pct(new, old):
    return None if not old or new is None else (new / old - 1) * 100


def _rsi(closes: list, n: int = 14):
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[:n], closes[1:n + 1]):
        d = b - a
        gains, losses = gains + max(d, 0), losses + max(-d, 0)
    avg_g, avg_l = gains / n, losses / n
    for a, b in zip(closes[n:], closes[n + 1:]):
        d = b - a
        avg_g = (avg_g * (n - 1) + max(d, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0)) / n
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def _returns(closes: list) -> list:
    return [b / a - 1 for a, b in zip(closes, closes[1:]) if a]


def _beta(dates: list, closes: list, bench: dict):
    """Beta to the benchmark over the shared dates (bench: date -> close)."""
    pairs = [(c, bench[d]) for d, c in zip(dates, closes) if d in bench]
    if len(pairs) < 60:
        return None
    s = _returns([p[0] for p in pairs])
    m = _returns([p[1] for p in pairs])
    ms, mm = sum(s) / len(s), sum(m) / len(m)
    var = sum((x - mm) ** 2 for x in m)
    if not var:
        return None
    return sum((a - ms) * (b - mm) for a, b in zip(s, m)) / var


def technicals(bars: list, bench: dict | None = None) -> dict | None:
    """Every price-based column from daily bars [{date, open, high, low, close, volume}], oldest first."""
    bars = [b for b in bars if b.get("close") and math.isfinite(b["close"])]
    if len(bars) < 20:
        return None
    closes = [b["close"] for b in bars]
    dates = [b["date"] for b in bars]
    vols = [b.get("volume") or 0 for b in bars]
    price = closes[-1]

    def back(n):
        return closes[-1 - n] if len(closes) > n else None

    def sma(n):
        return sum(closes[-n:]) / n if len(closes) >= n else None

    year = dates[-1][:4]
    ytd_base = next((c for d, c in zip(reversed(dates), reversed(closes)) if d[:4] < year), None)
    avg_vol = sum(vols[-63:]) / len(vols[-63:])
    trs = [max(b["high"], p) - min(b["low"], p) for b, p in zip(bars[-14:], closes[-15:-1])
           if b.get("high") and b.get("low")]
    rets = _returns(closes[-22:])
    vol_1m = (sum((x - sum(rets) / len(rets)) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5 * math.sqrt(252) \
        if len(rets) > 2 else None
    hi, lo = max(closes[-252:]), min(closes[-252:])
    return {
        "price": _r(price),
        "change": _r(_pct(price, back(1))),
        "volume": int(vols[-1]),
        "avg_volume": int(avg_vol),
        "rel_volume": _r(vols[-1] / avg_vol if avg_vol else None),
        "perf_1w": _r(_pct(price, back(5))), "perf_1m": _r(_pct(price, back(21))),
        "perf_3m": _r(_pct(price, back(63))), "perf_6m": _r(_pct(price, back(126))),
        "perf_ytd": _r(_pct(price, ytd_base)), "perf_1y": _r(_pct(price, back(251))),
        "high_52w": _r(hi), "low_52w": _r(lo),
        "from_high": _r(_pct(price, hi)), "from_low": _r(_pct(price, lo)),
        "rsi": _r(_rsi(closes[-120:]), 1),
        "sma20": _r(_pct(price, sma(20))), "sma50": _r(_pct(price, sma(50))), "sma200": _r(_pct(price, sma(200))),
        "volatility": _r(vol_1m * 100 if vol_1m is not None else None, 1),
        "beta": _r(_beta(dates, closes, bench) if bench else None),
        "atr": _r(sum(trs) / len(trs) / price * 100 if trs else None),
        "last_date": dates[-1],
    }


# ── fundamentals ──────────────────────────────────────────────

def fundamentals_from_info(info: dict, today: str) -> dict | None:
    """The raw inputs kept from Yahoo's summary (see FUND_KEYS)."""
    if not info or not (info.get("sharesOutstanding") or info.get("marketCap")):
        return None
    pct = lambda k: _r(info[k] * 100, 1) if isinstance(info.get(k), (int, float)) else None  # noqa: E731
    num = lambda k, d=4: _r(info[k], d) if isinstance(info.get(k), (int, float)) else None  # noqa: E731
    # The *next* report: earningsTimestamp is often the last one, so take the
    # earliest of Yahoo's timestamps that is not in the past.
    now = dt.datetime.now(dt.timezone.utc).timestamp() - 86400
    keys = ("earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd")
    upcoming = sorted(t for t in (info.get(k) for k in keys)
                      if isinstance(t, (int, float)) and t > now)
    ts = upcoming[0] if upcoming else None
    return {
        "name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"), "industry": info.get("industry"), "country": info.get("country"),
        "shares": info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"),
        "eps": num("trailingEps"), "forward_eps": num("forwardEps"), "revenue": num("totalRevenue", 0),
        "book_value": num("bookValue"), "dividend_rate": num("dividendRate"), "peg": num("trailingPegRatio", 2),
        "revenue_growth": pct("revenueGrowth"), "eps_growth": pct("earningsGrowth"),
        "gross_margin": pct("grossMargins"), "operating_margin": pct("operatingMargins"),
        "profit_margin": pct("profitMargins"), "roe": pct("returnOnEquity"),
        # Yahoo reports debt/equity as a percentage (84 = 0.84x).
        "debt_equity": _r(info["debtToEquity"] / 100, 2)
        if isinstance(info.get("debtToEquity"), (int, float)) else None,
        "current_ratio": num("currentRatio", 2), "rating": num("recommendationMean", 2),
        "target": num("targetMeanPrice", 2), "analysts": info.get("numberOfAnalystOpinions"),
        "short_float": pct("shortPercentOfFloat"), "institutional": pct("heldPercentInstitutions"),
        "earnings_date": dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()
        if isinstance(ts, (int, float)) and ts > 0 else None,
        "fundamentals_date": today,
    }


def derive(tech: dict, fund: dict | None) -> dict:
    """Ratios that move with the price, from today's close and the kept fundamentals."""
    f = fund or {}
    price = tech["price"]
    shares, eps, feps = f.get("shares"), f.get("eps"), f.get("forward_eps")
    mcap = price * shares if price and shares else None
    return {
        "market_cap": int(mcap) if mcap else None,
        "pe": _r(price / eps) if price and eps and eps > 0 else None,
        "forward_pe": _r(price / feps) if price and feps and feps > 0 else None,
        "ps": _r(mcap / f["revenue"]) if mcap and f.get("revenue") and f["revenue"] > 0 else None,
        "pb": _r(price / f["book_value"]) if price and f.get("book_value") and f["book_value"] > 0 else None,
        "dividend_yield": _r(f["dividend_rate"] / price * 100) if price and f.get("dividend_rate") else None,
        "upside": _r(_pct(f["target"], price)) if price and f.get("target") else None,
    }


def build_row(sym: str, name: str, exchange: str, tech: dict, fund: dict | None) -> list:
    f = fund or {}
    row = {"symbol": sym, "name": f.get("name") or name, "exchange": exchange, **tech, **derive(tech, fund),
           **{k: f.get(k) for k in ("sector", "industry", "country", "peg", "eps", "revenue_growth", "eps_growth",
                                    "gross_margin", "operating_margin", "profit_margin", "roe", "debt_equity",
                                    "current_ratio", "rating", "analysts", "short_float", "institutional",
                                    "earnings_date", "fundamentals_date")}}
    return [row.get(k) for k in FIELDS]


# ── fetching ──────────────────────────────────────────────────

def download_bars(symbols: list) -> dict:
    """symbol -> daily bars for the last year, in batches."""
    import yfinance as yf
    out = {}
    for i in range(0, len(symbols), BATCH):
        chunk = symbols[i:i + BATCH]
        for attempt in range(3):
            try:
                df = yf.download(chunk, period="1y", interval="1d", auto_adjust=True, group_by="ticker",
                                 threads=True, progress=False)
                break
            except Exception:
                time.sleep(10 * (attempt + 1))
        else:
            continue
        for sym in chunk:
            try:
                sub = df[sym] if len(chunk) > 1 else df
            except KeyError:
                continue
            bars = [{"date": idx.strftime("%Y-%m-%d"), "open": r.Open, "high": r.High, "low": r.Low,
                     "close": r.Close, "volume": r.Volume} for idx, r in sub.dropna(subset=["Close"]).iterrows()]
            if bars:
                out[sym] = bars
        print(f"  prices {min(i + BATCH, len(symbols))}/{len(symbols)}", flush=True)
    return out


def _yahoo_info(sym: str) -> dict:
    import yfinance as yf
    return yf.Ticker(sym).info


def fetch_fundamentals(symbols: list, today: str, info_fn=None, chunk: int = 60, workers: int = 3,
                       pause: float = 90.0) -> dict:
    """symbol -> fundamentals for as many of ``symbols`` as Yahoo will answer.

    Works in chunks. A chunk that is mostly refused (errors, not companies that
    simply lack data) means Yahoo is rate-limiting: wait ``pause`` seconds and
    carry on; refused again, and stop, keeping the previous values for the rest.
    """
    info_fn = info_fn or _yahoo_info
    out, strikes = {}, 0

    def one(sym):
        try:
            return sym, fundamentals_from_info(info_fn(sym), today), False
        except Exception:
            return sym, None, True

    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, part))
        for sym, fund, _ in results:
            if fund:
                out[sym] = fund
        refused = sum(1 for _, _, err in results if err)
        if refused > 0.8 * len(part):
            strikes += 1
            if strikes >= 2:
                print(f"  fundamentals: refused again at {i + len(part)}; keeping previous values for the rest")
                break
            print(f"  fundamentals: refused at {i + len(part)}; waiting {pause:.0f}s")
            time.sleep(pause)
        else:
            strikes = 0
        if (i // chunk) % 10 == 9:
            print(f"  fundamentals {i + len(part)}/{len(symbols)}", flush=True)
    return out


def refresh_order(symbols: list, previous: dict, priority: frozenset = frozenset()) -> list:
    """Stalest first (never fetched counts as stalest); among equals, ``priority``
    symbols (the large companies people look up) before the rest."""
    return sorted(symbols, key=lambda s: ((previous.get(s) or {}).get("fundamentals_date") or "",
                                          s not in priority))


def priority_symbols() -> frozenset:
    """The dashboard's ticker index (S&P 500 plus popular names): fetched first when new."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "symbols.js")
    try:
        pairs = json.loads(re.search(r"=\s*(\[.*\]);", io.open(path, encoding="utf-8").read(), re.S).group(1))
        return frozenset(sym for sym, _ in pairs)
    except (OSError, AttributeError, ValueError):
        return frozenset()


def previous_fundamentals(path: str | None) -> dict:
    if not path:
        return {}
    try:
        data = json.load(io.open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# ── main ──────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--prev", help="the previous fundamentals.json, for stocks Yahoo doesn't answer this run")
    ap.add_argument("--limit", type=int, help="only the first N symbols (for testing)")
    ap.add_argument("--max-fundamentals", type=int, default=1000,
                    help="refresh at most this many companies' fundamentals (stalest first); the rest keep theirs")
    args = ap.parse_args(argv)

    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    universe = load_universe()[:args.limit] if args.limit else load_universe()
    print(f"universe: {len(universe)} common stocks")
    symbols = [u[0] for u in universe]

    # Fundamentals before prices: a fresh session, before thousands of price
    # requests have used up Yahoo's patience (doing it after got "Invalid Crumb").
    funds = previous_fundamentals(args.prev)
    todo = refresh_order(symbols, funds, priority_symbols())[:args.max_fundamentals]
    fresh = fetch_fundamentals(todo, today)
    funds.update(fresh)
    print(f"fundamentals: {len(fresh)} of {len(todo)} refreshed, {len(funds)} available")

    bars = download_bars(symbols + ["SPY"])
    bench = {b["date"]: b["close"] for b in bars.pop("SPY", [])}
    print(f"prices: {len(bars)} with data")

    rows, latest = [], max((b[-1]["date"] for b in bars.values()), default=today)
    for sym, name, exchange in universe:
        tech = technicals(bars.get(sym, []), bench)
        # Drop symbols that stopped trading (no bar in the last week of the data).
        if not tech or tech["last_date"] < (dt.date.fromisoformat(latest) - dt.timedelta(days=7)).isoformat():
            continue
        tech.pop("last_date")
        rows.append(build_row(sym, name, exchange, tech, funds.get(sym)))
    out = {
        "generated": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "prices_as_of": latest,
        "source": "Nasdaq Trader symbol directory; Yahoo Finance prices and fundamentals; computed by Tradeski",
        "fields": FIELDS,
        "rows": rows,
    }
    os.makedirs(args.out_dir, exist_ok=True)
    with io.open(os.path.join(args.out_dir, "screener.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, separators=(",", ":"))
    kept = {s: {k: f.get(k) for k in FUND_KEYS} for s, f in funds.items() if s in bars}
    with io.open(os.path.join(args.out_dir, "fundamentals.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(kept, fh, separators=(",", ":"))
    print(f"wrote {args.out_dir}: {len(rows)} stocks")
    return 0 if len(rows) > 1000 or args.limit else 1


if __name__ == "__main__":
    sys.exit(main())
