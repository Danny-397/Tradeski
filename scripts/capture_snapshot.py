"""Capture a real Tradeski data snapshot for the offline demo mode.

Talks to a locally-running Tradeski backend for market data, and to FRED's
public CSV endpoint for the macro strip (the backend route needs an API key
that is not configured locally, but the underlying series are public).

Writes frontend/demo-snapshot.js, and appends today's at-the-money implied
volatility for each ticker to frontend/data/iv_history.json (see record_iv).
"""
import csv
import datetime as dt
import io
import json
import os
import sys
import urllib.request

BACKEND = os.environ.get("TRADESKI_BACKEND", "http://127.0.0.1:8811")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "demo-snapshot.js")
IV_OUT = os.path.join(os.path.dirname(OUT), "data", "iv_history.json")
IV_TARGET_DTE = 30          # the expiry nearest a month out, like most IV indices
EOD_DIR = os.path.join(os.path.dirname(OUT), "data", "options")

TICKER_SYMS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SOFI", "RDW", "GOOGL", "META", "SPY", "QQQ"]
TIMEFRAMES = ["1D", "5D", "1M", "3M", "6M", "1Y"]
DEFAULT_SYM = "AAPL"
# The ticker strip plus the scanner's default list.
EOD_SYMS = TICKER_SYMS + ["JPM"]
EOD_MAX_DTE, EOD_MAX_EXPIRIES = 75, 10

# series_id -> (label, unit, description, fred transformation or None)
FRED_SERIES = [
    ("CPIAUCSL", "CPI", "%", "Consumer Price Index YoY %", "pc1"),
    ("FEDFUNDS", "Fed Rate", "%", "Effective Federal Funds Rate", None),
    ("GDP", "GDP", "B", "Real GDP (Chained 2017 $B)", None),
    ("UNRATE", "Unemployment", "%", "Unemployment Rate", None),
    ("DGS10", "10Y Yield", "%", "10-Year Treasury Yield", None),
    ("T10Y2Y", "Yield Curve", "%", "10Y minus 2Y Treasury Spread", None),
    ("BAMLH0A0HYM2", "HY Spread", "%", "High Yield OAS Credit Spread", None),
]


def get(url, timeout=120):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def get_json(path, tries=6):
    """The backend rate-limits to 10/min, so back off and retry on 429."""
    import time
    for attempt in range(tries):
        try:
            raw = get(BACKEND + path)
            time.sleep(6.5)          # stay under the limiter for the next call
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            time.sleep(20)
    raise RuntimeError("unreachable")


def fred_latest(series_id, transformation):
    """Last two valid observations from FRED's public CSV (no API key)."""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series_id
    if transformation:
        url += "&transformation=" + transformation
    text = get(url, timeout=60).decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))[1:]
    vals = []
    for row in rows:
        if len(row) < 2:
            continue
        date, v = row[0], row[-1].strip()
        if v in ("", "."):
            continue
        try:
            vals.append((date, float(v)))
        except ValueError:
            continue
    return vals[-2:]


def build_macro():
    out = {}
    for sid, label, unit, desc, tr in FRED_SERIES:
        try:
            obs = fred_latest(sid, tr)
        except Exception as e:  # noqa: BLE001
            print("  FRED %-13s FAILED %s" % (sid, e))
            obs = []
        if not obs:
            out[sid] = {"label": label, "unit": unit, "description": desc,
                        "value": None, "prev_value": None, "date": None, "trend": "neutral"}
            continue
        date, val = obs[-1]
        prev = obs[-2][1] if len(obs) > 1 else None
        if prev is None:
            trend = "neutral"
        else:
            trend = "up" if val > prev else ("down" if val < prev else "neutral")
        out[sid] = {
            "label": label, "unit": unit, "description": desc,
            "value": round(val, 3),
            "prev_value": round(prev, 3) if prev is not None else None,
            "date": date, "trend": trend,
        }
        print("  FRED %-13s %s (%s)" % (sid, out[sid]["value"], date))
    return out


def nearest_expiry(expirations, target):
    """The expiry whose days-to-expiry is closest to ``target`` (None if there are none)."""
    return min(expirations, key=lambda e: abs(e["dte"] - target))["date"] if expirations else None


def merge_iv(history, day, readings):
    """Add one day's {symbol: {iv, expiry, dte}} to history, replacing a rerun of the same day.

    history is {"symbols": {SYM: [[date, iv, dte], ...]}} with dates ascending.
    """
    symbols = history.setdefault("symbols", {})
    for sym, r in readings.items():
        rows = [row for row in symbols.get(sym, []) if row[0] != day]
        rows.append([day, round(r["iv"], 4), r["dte"]])
        symbols[sym] = sorted(rows)
    history["updated"] = day
    return history


def record_iv(endpoints):
    """Today's ATM implied vol at about 30 days, per ticker, into iv_history.json.

    Tradeski has no source for IV history, so it keeps its own: one reading a
    trading day from the day this started. The Options window shows where
    today's IV sits in that history once there are enough days to mean
    anything. Also stores the default symbol's chain in the snapshot, so the
    offline demo can show it.
    """
    print("options (ATM IV at ~%d days):" % IV_TARGET_DTE)
    readings = {}
    for s in TICKER_SYMS:
        try:
            exp = get_json("/options/expirations?symbol=%s" % s)
            expiry = nearest_expiry(exp.get("expirations") or [], IV_TARGET_DTE)
            if not expiry:
                print("  %-6s no listed options" % s)
                continue
            path = "/options/chain?symbol=%s&expiry=%s" % (s, expiry)
            chain = get_json(path)
            if s == DEFAULT_SYM:
                # The offline Options window opens on the backend's default expiry.
                endpoints["/options/expirations?symbol=%s" % s] = exp
                endpoints[path] = chain
                if exp.get("default") and exp["default"] != expiry:
                    key = "/options/chain?symbol=%s&expiry=%s" % (s, exp["default"])
                    endpoints[key] = get_json(key)
            if chain.get("atm_iv"):
                readings[s] = {"iv": chain["atm_iv"], "dte": chain["dte"]}
                print("  %-6s %s  IV %.1f%%" % (s, expiry, chain["atm_iv"] * 100))
        except Exception as e:  # noqa: BLE001
            print("  %-6s FAILED %s" % (s, e))
    if not readings:
        return
    try:
        with io.open(IV_OUT, encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, ValueError):
        history = {"note": "At-the-money implied volatility of the expiry nearest 30 days out, recorded by "
                           "scripts/capture_snapshot.py after each US close. Rows are [date, iv, days to expiry]."}
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    merge_iv(history, day, readings)
    os.makedirs(os.path.dirname(IV_OUT), exist_ok=True)
    with io.open(IV_OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(history, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    print("  wrote %s (%d symbols)" % (IV_OUT, len(readings)))


def capture_eod_chains():
    """Save each symbol's closing option chains (expiries up to 75 days out,
    strikes within 30% of the spot) for the backend to fall back on: Yahoo
    serves option chains to this runner but refuses them to Render."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tracker import options as opt
    from tracker.price_fetcher import get_option_chain, get_option_expirations
    print("end-of-day option chains:")
    os.makedirs(EOD_DIR, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for s in EOD_SYMS:
        expiries = [e for e in get_option_expirations(s)
                    if opt.year_fraction(e) > 0 and opt.days_to_expiry(e) <= EOD_MAX_DTE][:EOD_MAX_EXPIRIES]
        out = {"symbol": s, "captured_at": now, "chains": {}}
        for e in expiries:
            raw = get_option_chain(s, e)
            if not raw:
                continue
            out["spot"], out["dividend_yield"] = raw["spot"], raw["dividend_yield"]
            out["chains"][e] = {"calls": opt.compact_rows(raw["calls"], raw["spot"]),
                                "puts": opt.compact_rows(raw["puts"], raw["spot"])}
        if not out["chains"]:
            print("  %-6s FAILED (no chains; previous file kept)" % s)
            continue
        with io.open(os.path.join(EOD_DIR, s + ".json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, separators=(",", ":"), sort_keys=True)
            f.write("\n")
        print("  %-6s %d expiries" % (s, len(out["chains"])))


def main():
    endpoints = {}

    print("stats:")
    for s in TICKER_SYMS:
        try:
            endpoints["/stats?symbol=%s" % s] = get_json("/stats?symbol=%s" % s)
            print("  %-6s ok" % s)
        except Exception as e:  # noqa: BLE001
            print("  %-6s FAILED %s" % (s, e))

    print("price_history:")
    # every symbol at the default timeframe, plus every timeframe for the default symbol
    wanted = [(s, "1D") for s in TICKER_SYMS] + [(DEFAULT_SYM, tf) for tf in TIMEFRAMES if tf != "1D"]
    for sym, tf in wanted:
        key = "/price_history?symbol=%s&tf=%s" % (sym, tf)
        try:
            endpoints[key] = get_json(key)
            print("  %-6s %-3s ok" % (sym, tf))
        except Exception as e:  # noqa: BLE001
            print("  %-6s %-3s FAILED %s" % (sym, tf, e))

    print("screener / correlation:")
    for path in ("/screener", "/correlation"):
        try:
            endpoints[path] = get_json(path)
            print("  %s ok" % path)
        except Exception as e:  # noqa: BLE001
            print("  %s FAILED %s" % (path, e))

    record_iv(endpoints)
    capture_eod_chains()

    print("macro (FRED public CSV):")
    endpoints["/macro"] = build_macro()

    # News needs a paid key and is not captured. The dashboard renders an empty
    # feed as "No news available", which is a clean state rather than an error.
    for s in TICKER_SYMS:
        endpoints["/news?symbol=%s" % s] = {"articles": [], "aggregate": {"label": "neutral", "score": 0}}

    # A wrong port or a dead backend fails every market call; writing then would
    # replace a good snapshot with one that only has the macro strip.
    missing = [s for s in TICKER_SYMS if "/stats?symbol=%s" % s not in endpoints]
    if missing:
        print("\nnot writing: no stats for %s (is the backend at %s?)" % (", ".join(missing), BACKEND))
        return 1

    payload = {
        "capturedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "defaultSymbol": DEFAULT_SYM,
        "note": "Captured from the Tradeski backend running locally against live market data. "
                "Macro series come from FRED's public CSV endpoint. News is not included.",
        "endpoints": endpoints,
    }

    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    js = (
        "/* Tradeski offline demo snapshot — generated, do not edit by hand.\n"
        "   Regenerate with scripts/capture_snapshot.py while the backend runs locally.\n"
        "   Captured: %s */\n"
        "window.TRADESKI_SNAPSHOT = %s;\n" % (payload["capturedAt"], body)
    )
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(js)
    print("\nwrote %s  (%.1f KB, %d endpoints)" % (OUT, len(js) / 1024, len(endpoints)))


if __name__ == "__main__":
    sys.exit(main())
