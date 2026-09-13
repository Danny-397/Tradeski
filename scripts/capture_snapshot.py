"""Capture a real Tradeski data snapshot for the offline demo mode.

Talks to a locally-running Tradeski backend for market data, and to FRED's
public CSV endpoint for the macro strip (the backend route needs an API key
that is not configured locally, but the underlying series are public).

Writes frontend/demo-snapshot.js.
"""
import csv
import datetime as dt
import io
import json
import os
import sys
import urllib.request

BACKEND = "http://127.0.0.1:8811"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "demo-snapshot.js")

TICKER_SYMS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SOFI", "RDW", "GOOGL", "META", "SPY", "QQQ"]
TIMEFRAMES = ["1D", "5D", "1M", "3M", "6M", "1Y"]
DEFAULT_SYM = "AAPL"

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

    print("macro (FRED public CSV):")
    endpoints["/macro"] = build_macro()

    # News needs a paid key and is not captured. The dashboard renders an empty
    # feed as "No news available", which is a clean state rather than an error.
    for s in TICKER_SYMS:
        endpoints["/news?symbol=%s" % s] = {"articles": [], "aggregate": {"label": "neutral", "score": 0}}

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
