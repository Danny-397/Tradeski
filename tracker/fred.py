"""FRED (Federal Reserve Economic Data) API client."""

import datetime
import requests
from typing import Optional

FRED_BASE = "https://api.stlouisfed.org/fred"

# (label, unit, description, higher-is-inflationary-for-Ski-context)
_SERIES: dict[str, tuple[str, str, str]] = {
    "CPIAUCSL":     ("CPI",          "%",   "Consumer Price Index YoY %"),
    "FEDFUNDS":     ("Fed Rate",     "%",   "Effective Federal Funds Rate"),
    "GDP":          ("GDP",          "B",   "Real GDP (Chained 2017 $B)"),
    "UNRATE":       ("Unemployment", "%",   "Unemployment Rate"),
    "DGS10":        ("10Y Yield",    "%",   "10-Year Treasury Yield"),
    "T10Y2Y":       ("Yield Curve",  "%",   "10Y minus 2Y Treasury Spread"),
    "BAMLH0A0HYM2": ("HY Spread",   "%",   "High Yield OAS Credit Spread"),
}


def _fetch_observations(series_id: str, api_key: str, limit: int = 2) -> list:
    """Fetch the most recent N valid observations for a FRED series."""
    try:
        resp = requests.get(
            f"{FRED_BASE}/series/observations",
            params={
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
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
            "value": round(val, 3) if val is not None else None,
            "prev_value": round(prev, 3) if prev is not None else None,
            "date": obs[0].get("date"),
            "trend": trend,
        }

    return result


def format_macro_context(snapshot: dict) -> str:
    """Format a macro snapshot into a concise text block for Ski's context."""
    arrows = {"up": "↑", "down": "↓", "neutral": "→"}
    lines = [f"LIVE FRED MACRO DATA — {datetime.date.today()}:"]
    for info in snapshot.values():
        val = info.get("value")
        if val is not None:
            lines.append(
                f"  {info['label']} ({info['description']}): "
                f"{val}{info['unit']} {arrows.get(info['trend'], '')} "
                f"[prev: {info['prev_value']}{info['unit']}, as of {info['date']}]"
            )
        else:
            lines.append(f"  {info['label']}: data unavailable")
    return "\n".join(lines)
