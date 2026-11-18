"""Capture end-of-day option chains for the symbols in data/options_symbols.txt.

Yahoo refuses option requests from Render, so the backend answers from files
saved after each close. .github/workflows/options-data.yml runs this on a
GitHub runner (which Yahoo does answer) and publishes the output to the
`options-data` branch as one commit replaced on every run, so ~90 symbols of
daily-changing quotes never pile up in the repository's history.

    python scripts/capture_options.py --out-dir out [--prev prev] [--symbols FILE]

Writes out/options/<SYMBOL>.json (the shape the backend reads, see
tracker.options.eod_raw_chain) and out/options/index.json (which symbols are
covered, and when each was captured). A symbol that fails today keeps its
previous file from --prev while that file still has an expiry in the future.
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


def load_symbols(path: str = SYMBOLS_FILE) -> list:
    """Symbols from the list file: one per line, # comments and blanks ignored, no repeats."""
    with io.open(path, encoding="utf-8") as f:
        syms = [line.split("#")[0].strip().upper() for line in f]
    return list(dict.fromkeys(s for s in syms if s))


def capture_symbol(symbol: str, now: str, expirations_fn=None, chain_fn=None) -> dict | None:
    """One symbol's closing chains in the saved-file shape, or None if nothing came back."""
    if expirations_fn is None or chain_fn is None:
        from tracker.price_fetcher import get_option_chain, get_option_expirations
        expirations_fn = expirations_fn or get_option_expirations
        chain_fn = chain_fn or get_option_chain
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
    return out if out["chains"] and out.get("spot") else None


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
    index, fresh = {}, 0
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
            else:
                print("  %-6s FAILED (no file)" % s)
        time.sleep(args.pause)

    write_json(os.path.join(out_dir, "index.json"), {"updated": now, "symbols": index})
    print("captured %d of %d symbols fresh, %d covered" % (fresh, len(symbols), len(index)))
    if fresh < MIN_SUCCESS * len(symbols):
        print("too few symbols answered; not publishing")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
