"""Decide whether a user's alert has fired, from price history.

Alerts are checked against the bars since the alert was created, not against
live ticks. The backend sleeps on Render's free tier, so a tick-based checker
would miss every move that happened while it was asleep; replaying history
catches them on the next check, with the time they actually happened.

Only bars that START at or after the alert's creation count, so a high that
was printed before the user set the alert can never fire it. Price alerts use
hourly bars (so precision is about an hour); indicator alerts use daily bars,
since RSI, volume and z-score are defined on daily data here.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional
from zoneinfo import ZoneInfo

from tracker.analyzer import rsi, sma, zscore

MARKET_TZ = ZoneInfo("America/New_York")  # yfinance timestamps are exchange-local
HOURLY_MAX_AGE_DAYS = 59                  # Yahoo serves hourly bars for about 60 days

PRICE_TYPES = {"price_above", "price_below"}
INDICATOR_TYPES = {"rsi_overbought", "rsi_oversold", "volume_spike", "volatility_spike"}

RSI_HIGH, RSI_LOW = 70.0, 30.0
VOLUME_MULTIPLIER = 2.0   # as tracker/alerts.volume_spike
ZSCORE_LIMIT = 2.5        # as tracker/alerts.volatility_spike


def bar_start(bar: dict) -> float:
    """Epoch seconds at which a bar opened. Daily bars open at 09:30 New York time."""
    ts = dt.datetime.fromisoformat(bar["timestamp"][:19])
    if ts.hour == 0 and ts.minute == 0:
        ts = ts.replace(hour=9, minute=30)
    return ts.replace(tzinfo=MARKET_TZ).timestamp()


def history_request(alert_type: str, created_at: float, now: float) -> tuple[str, str]:
    """(period, interval) of the bars needed to check an alert."""
    if alert_type in PRICE_TYPES and now - created_at < HOURLY_MAX_AGE_DAYS * 86400:
        return "3mo", "60m"
    return "1y", "1d"


def _when(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, MARKET_TZ).strftime("%b %d, %H:%M ET")


def evaluate(alert_type: str, symbol: str, threshold: Optional[float], created_at: float,
             bars: list) -> Optional[dict]:
    """Return {"triggered_at", "price", "message"} for the first qualifying bar, or None."""
    if not bars:
        return None
    starts = [bar_start(b) for b in bars]
    after = [i for i, s in enumerate(starts) if s >= created_at]
    if not after:
        return None

    if alert_type in PRICE_TYPES:
        if threshold is None or threshold <= 0:
            return None
        for i in after:
            b = bars[i]
            if alert_type == "price_above" and b["high"] >= threshold:
                return _fired(starts[i], threshold, f"{symbol} traded at or above ${threshold:,.2f}")
            if alert_type == "price_below" and b["low"] <= threshold:
                return _fired(starts[i], threshold, f"{symbol} traded at or below ${threshold:,.2f}")
        return None

    closes = [b["close"] for b in bars]
    if alert_type in ("rsi_overbought", "rsi_oversold"):
        series = rsi(closes, 14)
        for i in after:
            v = series[i]
            if v is None:
                continue
            if alert_type == "rsi_overbought" and v > RSI_HIGH:
                return _fired(starts[i], closes[i], f"{symbol} RSI rose to {v:.1f}, above {RSI_HIGH:.0f}")
            if alert_type == "rsi_oversold" and v < RSI_LOW:
                return _fired(starts[i], closes[i], f"{symbol} RSI fell to {v:.1f}, below {RSI_LOW:.0f}")
        return None

    if alert_type == "volume_spike":
        volumes = [float(b.get("volume") or 0) for b in bars]
        for i in after:
            # The average is of the 20 bars BEFORE this one, so a spike can't dilute its own baseline.
            if i < 20:
                continue
            avg = sma(volumes[i - 20:i], 20)[-1]
            if avg and volumes[i] > VOLUME_MULTIPLIER * avg:
                return _fired(starts[i], closes[i],
                              f"{symbol} volume was {volumes[i] / avg:.1f}x its 20-day average")
        return None

    if alert_type == "volatility_spike":
        series = zscore(closes, 20)
        for i in after:
            z = series[i]
            if z is not None and abs(z) > ZSCORE_LIMIT:
                return _fired(starts[i], closes[i], f"{symbol} moved {z:+.1f} standard deviations from its 20-day mean")
        return None

    return None


def _fired(start: float, price: float, message: str) -> dict:
    return {"triggered_at": start, "price": round(float(price), 4), "message": f"{message} ({_when(start)})"}
