"""Capture end-of-day option chains for the symbols in data/options_symbols.txt.

Yahoo refuses option requests from Render, so the backend answers from files
saved after each close. .github/workflows/options-data.yml runs this on a
GitHub runner (which Yahoo does answer) and publishes the output to the
`options-data` branch as one commit replaced on every run, so ~90 symbols of
daily-changing quotes never pile up in the repository's history.

    python scripts/capture_options.py --out-dir out [--prev prev] [--symbols FILE]

Writes, under out/options/:

- <SYMBOL>.json: the chains, in the shape the backend reads (tracker.options.eod_raw_chain)
- index.json: which symbols are covered, and when each was captured
- iv_history.json: each symbol's at-the-money IV about 30 days out, one reading per
  trading day, carried forward from --prev (seeded from frontend/data/iv_history.json)
- scan.json: the scanner's best trade of each kind for every symbol, at its default
  filters, so the Options window can scan all of them without the backend

A symbol that fails today keeps its previous file from --prev while that file
still has an expiry in the future.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tracker import options as opt  # noqa: E402

SYMBOLS_FILE = os.path.join(ROOT, "data", "options_symbols.txt")
# The nearest 10 expiries up to 75 days out, plus each week's last expiry up to
# 45 days out; strikes within 30% of the stock price (compact_rows).
MAX_DTE, MAX_EXPIRIES, WEEKLY_DTE = 75, 10, 45
MIN_SUCCESS = 0.5          # publish nothing if fewer than half the symbols answer
IV_TARGET_DTE = 30         # IV history: the expiry nearest a month out, like most IV indices
IV_SEED = os.path.join(ROOT, "frontend", "data", "iv_history.json")
IV_NOTE = ("At-the-money implied volatility of the expiry nearest 30 days out, recorded after each "
           "US close by scripts/capture_options.py. Rows are [date, iv, days to expiry].")
# The scanner's defaults (frontend/options.html), for the precomputed all-symbol scan.
SCAN_DEFAULTS = {"min_dte": 20, "max_dte": 50, "max_delta": 0.30, "min_oi": 100, "max_spread_pct": 10.0}
DEFAULT_RATE = 0.04        # as the backend assumes when FRED is unavailable


def load_symbols(path: str = SYMBOLS_FILE) -> list:
    """Symbols from the list file: one per line, # comments and blanks ignored, no repeats."""
    with io.open(path, encoding="utf-8") as f:
        syms = [line.split("#")[0].strip().upper() for line in f]
    return list(dict.fromkeys(s for s in syms if s))


def capture_symbol(symbol: str, now: str, expirations_fn=None, chain_fn=None, exdiv_fn=None) -> dict | None:
    """One symbol's closing chains in the saved-file shape, or None if nothing came back."""
    if expirations_fn is None or chain_fn is None or exdiv_fn is None:
        from tracker.price_fetcher import get_ex_dividend, get_option_chain, get_option_expirations
        expirations_fn = expirations_fn or get_option_expirations
        chain_fn = chain_fn or get_option_chain
        exdiv_fn = exdiv_fn or get_ex_dividend
    chosen = opt.eod_expiries(expirations_fn(symbol), max_dte=MAX_DTE,
                              nearest=MAX_EXPIRIES, weekly_dte=WEEKLY_DTE)
    out = {"symbol": symbol, "captured_at": now, "chains": {}}
    for e in (e for e in chosen if opt.year_fraction(e) > 0):
        raw = chain_fn(symbol, e)
        if not raw:
            continue
        out["spot"], out["dividend_yield"] = raw["spot"], raw["dividend_yield"]
        out["earnings_ts"], out["earnings_estimated"] = raw.get("earnings_ts"), raw.get("earnings_estimated")
        out["chains"][e] = {"calls": opt.compact_rows(raw["calls"], raw["spot"]),
                            "puts": opt.compact_rows(raw["puts"], raw["spot"])}
    if not (out["chains"] and out.get("spot")):
        return None
    out["ex_dividend"] = exdiv_fn(symbol)       # {date, amount} or None (non-payers)
    return out


def merge_iv(history: dict, day: str, readings: dict) -> dict:
    """Add one day's {symbol: {iv, dte}} to history, replacing a rerun of the same day.

    history is {"symbols": {SYM: [[date, iv, dte], ...]}} with dates ascending.
    """
    symbols = history.setdefault("symbols", {})
    for sym, r in readings.items():
        rows = [row for row in symbols.get(sym, []) if row[0] != day]
        rows.append([day, round(r["iv"], 4), r["dte"]])
        symbols[sym] = sorted(rows)
    history["updated"] = day
    return history


def treasury_rate() -> tuple:
    """(3-month Treasury yield, source) from FRED's public CSV, as the backend prices options."""
    try:
        import requests
        text = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO", timeout=20).text
        for line in reversed(text.strip().splitlines()):
            value = line.split(",")[-1]
            if value not in ("", "."):
                return float(value) / 100.0, "the 3-month Treasury yield, from FRED"
    except Exception:
        pass
    return DEFAULT_RATE, "an assumed rate: FRED was unavailable"


def analyse_symbol(data: dict, rate: float) -> tuple:
    """(IV reading or None, {scan kind: result}) for one saved file, priced as of its capture."""
    when = dt.datetime.fromisoformat(data["captured_at"])
    today = when.astimezone(opt._ET).date()
    expiries = [e for e in data["chains"] if opt.year_fraction(e, when) > 0]

    def chain_for(expiry):
        raw = opt.eod_raw_chain(data, expiry)
        return opt.clean_chain(raw, expiry, rate, now=when) if raw else None

    reading = None
    if expiries:
        e = min(expiries, key=lambda x: abs(opt.days_to_expiry(x, today) - IV_TARGET_DTE))
        c = chain_for(e)
        if c and c.get("atm_iv"):
            reading = {"iv": c["atm_iv"], "dte": opt.days_to_expiry(e, today)}

    scans = {}
    d = SCAN_DEFAULTS
    expiry = opt.scan_expiry(expiries, d["min_dte"], d["max_dte"], (d["min_dte"] + d["max_dte"]) // 2, today)
    chain = chain_for(expiry) if expiry else None
    for kind in opt.SCAN_KINDS:
        if not chain:
            scans[kind] = {"skipped": f"no expiry between {d['min_dte']} and {d['max_dte']} days"}
            continue
        row = opt.scan_candidate(kind, chain, max_delta=d["max_delta"], min_oi=d["min_oi"],
                                 max_spread_pct=d["max_spread_pct"])
        if row:
            row["dte"] = opt.days_to_expiry(expiry, today)
            row["earnings"] = (chain.get("earnings") or {}).get("date")
        scans[kind] = row or {"skipped": "nothing passes the filters"}
    return reading, scans


def build_scan(per_symbol: dict, updated: str, rate_source: str) -> dict:
    """scan.json: for each kind, every symbol's best trade (ranked by annualized return) and the skips."""
    kinds = {}
    for kind in opt.SCAN_KINDS:
        found, skipped = [], []
        for sym, scans in per_symbol.items():
            r = scans.get(kind) or {"skipped": "not analysed"}
            if "skipped" in r:
                skipped.append({"symbol": sym, "skipped": r["skipped"]})
            else:
                found.append({**r, "symbol": sym})
        found.sort(key=opt.scan_rank_key(kind))
        kinds[kind] = {"results": found, "skipped": skipped}
    return {"updated": updated, "filters": {**SCAN_DEFAULTS}, "rate_source": rate_source, "kinds": kinds}


def load_history(prev_dir) -> dict:
    """Yesterday's iv_history.json from --prev, else the snapshot job's file in the repo."""
    for path in ([os.path.join(prev_dir, "options", "iv_history.json")] if prev_dir else []) + [IV_SEED]:
        try:
            with io.open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("symbols"), dict):
                return data
        except (OSError, ValueError):
            continue
    return {}


def write_json(path: str, data: dict) -> None:
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")


def still_useful(path: str) -> dict | None:
    """A previous file worth keeping: readable, with an expiry still ahead."""
    try:
        with io.open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    chains = data.get("chains") or {}
    return data if any(opt.year_fraction(e) > 0 for e in chains) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--prev", default=None, help="previous run's output directory, if any")
    ap.add_argument("--symbols", default=SYMBOLS_FILE)
    ap.add_argument("--pause", type=float, default=0.3, help="seconds between symbols, to be gentle with Yahoo")
    args = ap.parse_args(argv)

    symbols = load_symbols(args.symbols)
    out_dir = os.path.join(args.out_dir, "options")
    os.makedirs(out_dir, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    rate, rate_source = treasury_rate()
    print("rate: %.4f (%s)" % (rate, rate_source))
    index, fresh, readings, scans = {}, 0, {}, {}
    for s in symbols:
        data = None
        for attempt in range(2):
            try:
                data = capture_symbol(s, now)
            except Exception as exc:  # a bad symbol must not stop the run
                print("  %-6s error: %s" % (s, exc))
            if data:
                break
            time.sleep(2.0)
        if data:
            write_json(os.path.join(out_dir, s + ".json"), data)
            index[s] = {"captured_at": now, "expiries": len(data["chains"])}
            fresh += 1
            print("  %-6s %d expiries" % (s, len(data["chains"])))
        else:
            prev = still_useful(os.path.join(args.prev, "options", s + ".json")) if args.prev else None
            if prev:
                shutil.copy(os.path.join(args.prev, "options", s + ".json"), os.path.join(out_dir, s + ".json"))
                index[s] = {"captured_at": prev.get("captured_at"), "expiries": len(prev["chains"]), "stale": True}
                print("  %-6s FAILED (yesterday's file kept)" % s)
                data = prev
            else:
                print("  %-6s FAILED (no file)" % s)
        if data:
            try:
                reading, scans[s] = analyse_symbol(data, rate)
                if reading and data["captured_at"] == now:      # only today's quotes go into the history
                    readings[s] = reading
            except Exception as exc:  # analysis must never cost the data itself
                print("  %-6s analysis error: %s" % (s, exc))
        time.sleep(args.pause)

    write_json(os.path.join(out_dir, "index.json"), {"updated": now, "symbols": index})
    history = load_history(args.prev)
    history["note"] = IV_NOTE
    day = dt.datetime.fromisoformat(now).astimezone(opt._ET).date().isoformat()
    write_json(os.path.join(out_dir, "iv_history.json"), merge_iv(history, day, readings))
    write_json(os.path.join(out_dir, "scan.json"), build_scan(scans, now, rate_source))
    print("IV recorded for %d symbols; scan built for %d" % (len(readings), len(scans)))
    print("captured %d of %d symbols fresh, %d covered" % (fresh, len(symbols), len(index)))
    if fresh < MIN_SUCCESS * len(symbols):
        print("too few symbols answered; not publishing")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
