# tracker/price_fetcher.py
# Fetches latest stock prices via yfinance.

import math
from typing import Optional
import yfinance as yf


def _safe_info(symbol: str) -> dict:
    """Return ``yf.Ticker(symbol).info``, or {} if it is unavailable.

    Kept separate because this is by far the most failure-prone call in the
    module and the caller needs to carry on without it.
    """
    try:
        info = yf.Ticker(symbol).info
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _num(value, digits: int = 2) -> float | None:
    """Round to a JSON-safe float, or None if the value is unusable.

    Guards the output against NaN and infinity from either source: both
    serialise as bare `NaN`/`Infinity` tokens, which are not valid JSON and
    which render as "NaN" in the dashboard.
    """
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return round(out, digits) if math.isfinite(out) else None


def get_screener_data(symbol: str) -> dict | None:
    """
    Fetch fundamental screening data for a symbol.
    Returns price, P/E, market cap, sector, 52W range and performance.
    Returns None only when neither data source yields a price.

    Prefers ``.info`` (the only source for P/E, market cap and sector), but
    does not depend on it. Yahoo rate-limits the quoteSummary endpoint behind
    ``.info`` far more aggressively than the chart endpoint, and blocks it
    outright from some datacenter IPs -- on Render it returns nothing while
    ``history()`` keeps working. This used to make every one of the 29
    universe rows None, so /screener answered 200 with an empty table and no
    indication anything was wrong.

    Price and the 52-week columns are therefore derived from a year of daily
    bars whenever ``.info`` cannot supply them; P/E, market cap and sector have
    no such fallback and stay blank, which is a visibly partial row rather than
    a missing one.
    """
    info = _safe_info(symbol)

    price = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )
    pe     = info.get("trailingPE") or info.get("forwardPE")
    mcap   = info.get("marketCap")
    sector = info.get("sector") or (
        "ETF" if info.get("quoteType") in ("ETF", "INDEX") else None
    )
    high52 = info.get("fiftyTwoWeekHigh")
    low52  = info.get("fiftyTwoWeekLow")
    perf52 = info.get("52WeekChange")
    name   = info.get("shortName") or info.get("longName") or symbol

    # Fill from the chart endpoint only for what is actually missing.
    if not price or high52 is None or low52 is None or perf52 is None:
        bars = get_ohlc_history(symbol, "1y", "1d")
        if bars:
            closes = [b["close"] for b in bars]
            if not price:
                price = closes[-1]
            if high52 is None:
                high52 = max(b["high"] for b in bars)
            if low52 is None:
                low52 = min(b["low"] for b in bars)
            if perf52 is None and closes[0]:
                perf52 = closes[-1] / closes[0] - 1.0

    price = _num(price)
    if not price:
        return None

    # 52WeekChange is a decimal fraction; the dashboard shows a percentage.
    perf_frac = _num(perf52, 10)
    perf_pct = _num(perf_frac * 100) if perf_frac is not None else None

    return {
        "symbol":     symbol,
        "name":       name,
        "price":      price,
        "pe":         _num(pe),
        "market_cap": int(mcap) if mcap else None,
        "sector":     sector or "—",
        "high_52w":   _num(high52) or None,
        "low_52w":    _num(low52) or None,
        "perf_52w":   perf_pct,
    }


def get_stock_price(symbol: str) -> Optional[float]:
    """
    Return the latest closing price for a symbol, or None on failure.

    Tests expect:
        - None on error/empty
        - a positive float on success
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")

        if hist.empty:
            return None

        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def get_ohlc_history(symbol: str, period: str = "1mo", interval: str = "1d") -> list:
    """
    Return a list of OHLC + volume dicts for the requested period/interval.

    Each dict: {timestamp, open, high, low, close, volume}
    Returns [] on any failure.

    Rows whose OHLC is not fully finite are dropped. yfinance emits a
    placeholder bar for the current session with NaN prices but a real volume
    -- so it survives an `int(volume)` guard -- and NaN then propagates into
    everything downstream: a NaN close in /stats, gaps in the chart and
    sparkline endpoints, and a NaN row that poisons the whole correlation
    matrix via np.corrcoef. NaN also serialises as the bare token `NaN`, which
    is not valid JSON and which strict clients reject outright.

    Valid period/interval combos (yfinance):
      "1d"/"5m", "5d"/"15m", "1mo"/"1d", "3mo"/"1d", "6mo"/"1d", "1y"/"1d"
    """
    try:
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df.empty:
            return []

        result = []
        for idx, row in df.iterrows():
            try:
                o = float(row["Open"])
                h = float(row["High"])
                lo = float(row["Low"])
                c = float(row["Close"])
            except (TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in (o, h, lo, c)):
                continue

            try:
                vol = int(row.get("Volume", 0) or 0)
            except (TypeError, ValueError):
                vol = 0

            result.append({
                "timestamp": idx.strftime("%Y-%m-%dT%H:%M:%S"),
                "open":   round(o,  4),
                "high":   round(h,  4),
                "low":    round(lo, 4),
                "close":  round(c,  4),
                "volume": vol,
            })
        return result
    except Exception:
        return []
