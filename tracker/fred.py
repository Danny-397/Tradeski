"""FRED (Federal Reserve Economic Data) API client."""

import datetime
import requests
from typing import Optional

FRED_BASE = "https://api.stlouisfed.org/fred"

# (label, unit, description). Units: "%", "B" ($ billions), "$" (dollar price),
# "K" (thousands, signed change). Order is the dashboard ribbon's order.
_SERIES: dict[str, tuple[str, str, str]] = {
    "CPIAUCSL":      ("CPI",          "%",   "Consumer Price Index YoY %"),
    "CPILFESL":      ("Core CPI",     "%",   "CPI excluding food and energy, YoY %"),
    "FEDFUNDS":      ("Fed Rate",     "%",   "Effective Federal Funds Rate"),
    "GDP":           ("GDP",          "B",   "Real GDP (Chained 2017 $B)"),
    "UNRATE":        ("Unemployment", "%",   "Unemployment Rate"),
    "PAYEMS":        ("Payrolls",     "K",   "Nonfarm payrolls, monthly change (thousands of jobs)"),
    "CES0500000003": ("Wages",        "%",   "Average hourly earnings, private sector, YoY %"),
    "DGS10":         ("10Y Yield",    "%",   "10-Year Treasury Yield"),
    "T10Y2Y":        ("Yield Curve",  "%",   "10Y minus 2Y Treasury Spread"),
    "BAMLH0A0HYM2":  ("HY Spread",    "%",   "High Yield OAS Credit Spread"),
    "DCOILWTICO":    ("WTI Oil",      "$",   "WTI crude oil spot price, $ per barrel"),
    "GASREGW":       ("Gasoline",     "$",   "US regular gasoline retail price, $ per gallon (weekly)"),
    "DHHNGSP":       ("Natural Gas",  "$",   "Henry Hub natural gas spot price, $ per million Btu"),
}

# Series that need a FRED units transform before returning values.
# "pc1" = percent change from a year ago (YoY %); "chg" = change from the prior reading.
_SERIES_UNITS: dict[str, str] = {
    "CPIAUCSL": "pc1",
    "CPILFESL": "pc1",
    "CES0500000003": "pc1",
    "PAYEMS": "chg",
}

# The agency that publishes each series (FRED republishes them).
SOURCES: dict[str, str] = {
    "CPIAUCSL": "BLS", "CPILFESL": "BLS", "UNRATE": "BLS", "PAYEMS": "BLS",
    "CES0500000003": "BLS",
    "FEDFUNDS": "Federal Reserve", "DGS10": "Federal Reserve", "T10Y2Y": "Federal Reserve",
    "GDP": "BEA", "BAMLH0A0HYM2": "ICE BofA",
    "DCOILWTICO": "EIA", "GASREGW": "EIA", "DHHNGSP": "EIA",
}

# How each reading usually moves stocks: the textbook channel, not a forecast.
IMPACT: dict[str, str] = {
    "CPIAUCSL": "Hotter inflation raises odds of Fed hikes, which weighs most on growth and tech stocks.",
    "CPILFESL": "The Fed watches core inflation most; a hot reading pushes rate expectations and yields up.",
    "FEDFUNDS": "Higher rates raise borrowing costs and discount future earnings, hitting growth stocks hardest.",
    "GDP": "Faster growth lifts earnings, helping cyclicals such as industrials, materials and banks.",
    "UNRATE": "Rising unemployment signals a slowdown but can bring rate cuts; falling unemployment can mean tighter policy.",
    "PAYEMS": "Strong job gains support consumer spending but can keep rates higher; weak gains raise recession fears.",
    "CES0500000003": "Fast wage growth feeds inflation and squeezes margins in labour-heavy businesses such as retail and restaurants.",
    "DGS10": "A higher 10-year yield lowers the value of future profits, pressuring growth stocks, REITs and utilities.",
    "T10Y2Y": "A negative spread (inverted curve) has often come before recessions and squeezes bank lending margins.",
    "BAMLH0A0HYM2": "A widening spread means lenders see more default risk: a risk-off signal for stocks.",
    "DCOILWTICO": "Higher oil helps energy producers and hurts airlines, shippers and consumers; it also feeds inflation.",
    "GASREGW": "Pricier gasoline leaves consumers less to spend elsewhere, weighing on retail and discretionary stocks.",
    "DHHNGSP": "Higher natural gas helps gas producers and raises costs for utilities, chemicals and fertiliser makers.",
}


def _fetch_observations(series_id: str, api_key: str, limit: int = 2) -> list:
    """Fetch the most recent N valid observations for a FRED series."""
    try:
        params: dict = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        if series_id in _SERIES_UNITS:
            params["units"] = _SERIES_UNITS[series_id]
        resp = requests.get(
            f"{FRED_BASE}/series/observations",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return [
            o for o in resp.json().get("observations", [])
            if o.get("value") not in (".", None, "")
        ]
    except Exception:
        return []


def get_macro_snapshot(api_key: str) -> dict:
    """Return latest value + trend direction for each tracked FRED series."""
    result: dict = {}
    for series_id, (label, unit, description) in _SERIES.items():
        obs = _fetch_observations(series_id, api_key, limit=2)

        if not obs:
            result[series_id] = {
                "label": label, "unit": unit, "description": description,
                "source": SOURCES.get(series_id), "impact": IMPACT.get(series_id),
                "value": None, "prev_value": None, "date": None, "trend": "neutral",
            }
            continue

        def _safe_float(o: Optional[dict]) -> Optional[float]:
            if o is None:
                return None
            try:
                return float(o["value"])
            except (ValueError, TypeError, KeyError):
                return None

        val = _safe_float(obs[0])
        prev = _safe_float(obs[1]) if len(obs) > 1 else None

        if val is not None and prev is not None:
            trend = "up" if val > prev else ("down" if val < prev else "neutral")
        else:
            trend = "neutral"

        result[series_id] = {
            "label": label,
            "unit": unit,
            "description": description,
            "source": SOURCES.get(series_id),
            "impact": IMPACT.get(series_id),
            "value": round(val, 3) if val is not None else None,
            "prev_value": round(prev, 3) if prev is not None else None,
            "date": obs[0].get("date"),
            "trend": trend,
        }

    return result


def format_value(value, unit: str) -> str:
    """A reading with its unit, e.g. 3.2%, $89.53, +165K."""
    if unit == "$":
        return f"${value}"
    if unit == "K":
        return f"{value:+g}K"
    return f"{value}{unit}"


def format_macro_context(snapshot: dict) -> str:
    """Format a macro snapshot into a concise text block for Ski's context."""
    arrows = {"up": "↑", "down": "↓", "neutral": "→"}
    lines = [f"LIVE FRED MACRO DATA (incl. BLS jobs and prices, EIA energy) — {datetime.date.today()}:"]
    for info in snapshot.values():
        val = info.get("value")
        if val is not None:
            unit = info["unit"]
            prev = info.get("prev_value")
            source = f", {info['source']}" if info.get("source") else ""
            lines.append(
                f"  {info['label']} ({info['description']}): "
                f"{format_value(val, unit)} {arrows.get(info['trend'], '')} "
                f"[prev: {format_value(prev, unit) if prev is not None else '?'}, as of {info['date']}{source}]"
            )
        else:
            lines.append(f"  {info['label']}: data unavailable")
    return "\n".join(lines)
