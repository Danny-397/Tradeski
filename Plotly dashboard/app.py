"""Plotly dashboard backend using Flask + Socket.IO for Tradeski."""

import sys
import os

# When run via gunicorn --chdir, the repo root is the parent of this file's directory.
# Insert it so `tracker` can always be found regardless of working directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import threading
import time
import datetime
from functools import wraps
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import anthropic

from cache import SimpleCache
from tracker import database
from tracker import auth
from tracker.fred import get_macro_snapshot, format_macro_context
from tracker.fred import _fetch_observations as fetch_fred_observations
from tracker import ski_tools, ski_grounding, sec_fundamentals, alert_eval
from tracker import options as opt
from tracker.news import fetch_news, aggregate_sentiment, format_news_context
from tracker.price_fetcher import get_stock_price, get_ohlc_history, get_screener_data
from tracker.price_fetcher import get_option_expirations, get_option_chain
from tracker.analyzer import (
    sma,
    ema,
    rsi,
    macd,
    bollinger_bands,
    zscore,
    volatility,
)

app = Flask(__name__)

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "https://tradeski.dev,https://www.tradeski.dev")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()] if _raw_origins != "*" else "*"

CORS(app, origins=_allowed_origins)

socketio = SocketIO(
    app,
    cors_allowed_origins=_allowed_origins,
    async_mode="gevent",
)


def _client_ip() -> str:
    """The visitor's address, for rate limiting.

    On Render every request reaches Flask from Render's proxy, so
    request.remote_addr is the same for every visitor and they would all share
    one bucket: one person retrying a login could lock everyone out, and Ask
    Ski's hourly quota would be the whole site's. Render serves through
    Cloudflare, which sets CF-Connecting-IP and overwrites any value a client
    sends, so it can't be spoofed there. Run locally, the header is absent and
    this falls back to the socket address, as before.
    """
    return request.headers.get("CF-Connecting-IP") or get_remote_address()


# The default guards the cheap, cached read endpoints only -- /auth/register
# and /auth/login carry their own, much tighter limits and are untouched by it.
#
# It used to be 10/minute, which is below what the dashboard needs to paint
# itself once: the ticker strip alone requests /stats for all 11 watchlist
# symbols, so every one of them came back 429 and the panels rendered empty.
# First paint is ~30 requests and the dashboard refreshes every 10s, so steady
# state is ~120/minute; 180 leaves headroom without being a blank cheque. These
# responses are cached (see _CHART_TTL and friends), so repeat traffic is served
# from memory rather than hitting the upstream providers.
limiter = Limiter(
    key_func=_client_ip,
    app=app,
    default_limits=["180 per minute"],
    storage_uri="memory://",
)

_cache = SimpleCache()
_FRED_TTL     = 3600   # refresh FRED data at most once per hour
_CHART_TTL    = 300    # price history / stats cache: 5 minutes
_NEWS_TTL     = 1800   # news + sentiment cache: 30 minutes
_SCREENER_TTL = 600    # screener fundamentals cache: 10 minutes
_CORR_TTL     = 3600  # correlation matrix cache: 1 hour
_OPTIONS_TTL  = 300   # option chains: 5 minutes (quotes are delayed anyway)

_CORR_SYMS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SOFI", "RDW", "GOOGL", "META", "SPY", "QQQ"]

_SCREENER_UNIVERSE = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD", "INTC", "ORCL",
    # Financials
    "JPM", "BAC", "GS", "V", "MA",
    # Healthcare
    "JNJ", "UNH", "LLY", "ABBV", "MRK",
    # Energy
    "XOM", "CVX", "COP",
    # Consumer
    "WMT", "COST", "HD", "MCD",
    # Broad-market ETFs
    "SPY", "QQQ",
]

# Timeframe → (yfinance period, interval)
_TF_MAP: dict[str, tuple[str, str]] = {
    "1D":  ("1d",  "5m"),
    "5D":  ("5d",  "15m"),
    "1M":  ("1mo", "1d"),
    "3M":  ("3mo", "1d"),
    "6M":  ("6mo", "1d"),
    "1Y":  ("1y",  "1d"),
}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def rows_to_dict(
    rows: List[Tuple[str, float, float]],
    limit: Optional[int],
) -> Tuple[List[str], List[float], List[float]]:
    """Convert (timestamp, price, volume) rows into labeled lists."""
    if limit:
        rows = rows[-limit:]

    timestamps = [row[0] for row in rows]
    prices = [row[1] for row in rows]
    volume = [row[2] for row in rows]
    return timestamps, prices, volume


# ─────────────────────────────────────────────────────────────
# Authentication
# ─────────────────────────────────────────────────────────────

def _bearer_token() -> str:
    """Extract the bearer token from the Authorization header."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return ""


def _resolve_user() -> Optional[int]:
    """Return the authenticated user id for this request, or None."""
    return auth.verify_token(_bearer_token())


def require_auth(fn):
    """Reject the request with 401 unless it carries a valid token."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = _resolve_user()
        if user_id is None:
            return jsonify({"error": "Sign in to use this feature."}), 401
        g.user_id = user_id
        return fn(*args, **kwargs)
    return wrapper


def optional_auth(fn):
    """Set g.user_id if a valid token is present; otherwise leave it None."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        g.user_id = _resolve_user()
        return fn(*args, **kwargs)
    return wrapper


@app.route("/auth/register", methods=["POST"])
@limiter.limit("10 per hour")
def register() -> tuple:
    data = request.json or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not auth.is_valid_email(email):
        return jsonify({"error": "Enter a valid email address."}), 400
    problem = auth.password_problem(password)
    if problem:
        return jsonify({"error": problem}), 400

    user_id = database.create_user(email, auth.hash_password(password))
    if user_id is None:
        return jsonify({"error": "An account with that email already exists."}), 409

    token = auth.generate_token(user_id)
    return jsonify({"token": token, "user": {"id": user_id, "email": email.lower()}})


@app.route("/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def login() -> tuple:
    data = request.json or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    user = database.get_user_by_email(email)
    if not user or not auth.verify_password(password, user["password_hash"]):
        return jsonify({"error": "Incorrect email or password."}), 401

    token = auth.generate_token(user["id"])
    return jsonify({"token": token, "user": {"id": user["id"], "email": user["email"]}})


@app.route("/auth/me")
@require_auth
def me() -> tuple:
    user = database.get_user_by_id(g.user_id)
    if not user:
        return jsonify({"error": "Account not found."}), 404
    return jsonify({"user": user})


# ─────────────────────────────────────────────────────────────
# REST Endpoints
# ─────────────────────────────────────────────────────────────

@app.route("/health")
def health() -> tuple:
    return jsonify({
        "status": "ok",
        "db": database.db_backend(),
        "services": {
            "fred":      "configured" if os.environ.get("FRED_API_KEY")      else "missing",
            "news":      "configured" if os.environ.get("NEWS_API_KEY")       else "missing",
            "anthropic": "configured" if os.environ.get("ANTHROPIC_API_KEY")  else "missing",
        },
    })


@app.route("/stats")
def stats() -> tuple:
    """Return OHLC + real 52-week range for a symbol (yfinance, cached 5 min)."""
    symbol = request.args.get("symbol", "AAPL").upper()
    cache_key = f"stats:{symbol}"

    cached = _cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)

    bars = get_ohlc_history(symbol, "1y", "1d")
    if not bars:
        return jsonify({"error": "No data"}), 404

    latest     = bars[-1]
    all_highs  = [b["high"] for b in bars]
    all_lows   = [b["low"]  for b in bars]
    change_pct = (
        (latest["close"] - latest["open"]) / latest["open"] * 100
        if latest["open"] else 0.0
    )

    result = {
        "symbol":     symbol,
        "open":       round(latest["open"],  4),
        "high":       round(latest["high"],  4),
        "low":        round(latest["low"],   4),
        "close":      round(latest["close"], 4),
        "high_52w":   round(max(all_highs),  4),
        "low_52w":    round(min(all_lows),   4),
        "change_pct": round(change_pct,      4),
    }

    _cache.set(cache_key, result, ttl=_CHART_TTL)
    return jsonify(result)


@app.route("/price_history")
def price_history() -> tuple:
    """Return real OHLC history + computed indicators (yfinance, cached 5 min)."""
    symbol = request.args.get("symbol", "AAPL").upper()
    # Accept either ?tf=1M (new) or ?limit=300 (legacy — map to nearest tf)
    tf = (request.args.get("tf") or request.args.get("timeframe") or "1M").upper()
    if tf not in _TF_MAP:
        tf = "1M"

    cache_key = f"ph:{symbol}:{tf}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)

    period, interval = _TF_MAP[tf]
    bars = get_ohlc_history(symbol, period, interval)
    if not bars:
        return jsonify({"error": "No data"}), 404

    timestamps = [b["timestamp"] for b in bars]
    opens      = [b["open"]      for b in bars]
    highs      = [b["high"]      for b in bars]
    lows       = [b["low"]       for b in bars]
    closes     = [b["close"]     for b in bars]
    volume     = [b["volume"]    for b in bars]

    sma20_vals             = sma(closes, 20)
    sma50_vals             = sma(closes, 50)
    ema20_vals             = ema(closes, 20)
    rsi_vals               = rsi(closes, 14)
    macd_line, sig, hist_v = macd(closes)
    upper_band, lower_band = bollinger_bands(closes, 20)
    z_vals                 = zscore(closes, 20)
    vol_vals               = volatility(closes, 20)

    result = {
        "timestamps": timestamps,
        "open":       opens,
        "high":       highs,
        "low":        lows,
        "close":      closes,
        "prices":     closes,     # keep for any legacy callers
        "volume":     volume,
        "sma20":      sma20_vals,
        "sma50":      sma50_vals,
        "ema20":      ema20_vals,
        "rsi":        rsi_vals,
        "macd":       macd_line,
        "signal":     sig,
        "histogram":  hist_v,
        "upper_band": upper_band,
        "lower_band": lower_band,
        "zscore":     z_vals,
        "volatility": vol_vals,
    }

    _cache.set(cache_key, result, ttl=_CHART_TTL)
    return jsonify(result)


@app.route("/sparkline")
def sparkline() -> tuple:
    """Return 30-day close prices for a symbol (used by watchlist sparklines)."""
    symbol = request.args.get("symbol", "AAPL").upper()
    cache_key = f"sparkline:{symbol}"

    cached = _cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)

    bars = get_ohlc_history(symbol, "1mo", "1d")
    result = {
        "timestamps": [b["timestamp"] for b in bars],
        "close":      [b["close"]     for b in bars],
    }
    _cache.set(cache_key, result, ttl=_CHART_TTL)
    return jsonify(result)


@app.route("/watchlist")
def watchlist() -> tuple:
    """Return latest price + pct_change for a comma‑separated list of symbols."""
    raw = request.args.get("symbols", "AAPL,MSFT,TSLA,NVDA,AMZN")
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]

    result = {}

    for sym in symbols:
        rows = database.get_recent_prices(sym, limit=2)
        if not rows:
            result[sym] = None
            continue

        prices = [row[1] for row in rows]
        open_price = prices[0]
        close_price = prices[-1]

        pct_change = (
            (close_price - open_price) / open_price * 100
            if open_price else 0.0
        )

        result[sym] = {
            "price": round(close_price, 4),
            "change_pct": round(pct_change, 4),
        }

    return jsonify(result)


@app.route("/watchlist/saved", methods=["GET"])
@require_auth
def get_saved_watchlist() -> tuple:
    """Return the signed-in user's persistent watchlist symbols."""
    return jsonify({"symbols": database.get_watchlist(g.user_id)})


def _clean_symbol(raw) -> str:
    """Normalise a user-supplied ticker before it is stored or looked up.

    Keeps letters, digits, '.' and '-': class shares are spelled BRK-B by the
    price API, and stripping the hyphen stored an unpriceable BRKB. Anything else
    is dropped, so the value is safe to render back into the dashboard.
    """
    return re.sub(r"[^A-Z0-9.\-]", "", str(raw or "").upper())[:10]


@app.route("/watchlist/saved", methods=["POST"])
@require_auth
def add_saved_watchlist() -> tuple:
    """Add a symbol to the signed-in user's persistent watchlist."""
    data = request.json or {}
    symbol = _clean_symbol(data.get("symbol"))
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    database.add_to_watchlist(g.user_id, symbol)
    return jsonify({"status": "ok", "symbols": database.get_watchlist(g.user_id)})


@app.route("/watchlist/saved/<symbol>", methods=["DELETE"])
@require_auth
def delete_saved_watchlist(symbol: str) -> tuple:
    """Remove a symbol from the signed-in user's persistent watchlist."""
    clean = _clean_symbol(symbol)
    database.remove_from_watchlist(g.user_id, clean)
    return jsonify({"status": "deleted", "symbols": database.get_watchlist(g.user_id)})


@app.route("/market_status")
def market_status() -> tuple:
    """Return simple market‑open heuristic based on server UTC time."""
    now = datetime.datetime.utcnow()
    day = now.weekday()
    hour = now.hour + now.minute / 60

    if day >= 5:
        status = "closed"
    elif 13.5 <= hour < 20:
        status = "open"
    elif 8 <= hour < 13.5 or 20 <= hour < 24:
        status = "extended"
    else:
        status = "closed"

    return jsonify({"status": status, "utc": now.isoformat()})


@app.route("/alerts", methods=["GET"])
@require_auth
def get_alerts() -> tuple:
    """Return the signed-in user's active alerts, after checking them, and the ones that fired."""
    try:
        _check_alerts(database.get_active_alerts_for_eval(g.user_id))
    except Exception:
        app.logger.exception("alert check failed")  # still list the alerts
    return jsonify({
        "active": database.get_alerts(g.user_id),
        "triggered": database.get_triggered_alerts(g.user_id, 10),
    })


# The options the alert form offers; anything else is rejected rather than stored.
_ALERT_TYPES = alert_eval.PRICE_TYPES | alert_eval.INDICATOR_TYPES
MAX_ACTIVE_ALERTS = 20


def _alert_bars(symbol: str, period: str, interval: str) -> list:
    key = f"alert_bars:{symbol}:{period}:{interval}"
    bars = _cache.get(key)
    if bars is None:
        bars = get_ohlc_history(symbol, period, interval)
        _cache.set(key, bars, ttl=_CHART_TTL)
    return bars or []


def _check_alerts(rows) -> int:
    """Evaluate active alerts against price history and record the ones that fired.

    ``rows`` are (id, user_id, symbol, alert_type, threshold, created_at). Each
    distinct (symbol, bar size) is fetched once, through the cache. Returns how
    many alerts fired.
    """
    now = time.time()
    plans = [(r, alert_eval.history_request(r[3], r[5], now)) for r in rows]
    needed = {(r[2], *req) for r, req in plans}
    if not needed:
        return 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        bars = dict(zip(needed, pool.map(lambda k: _alert_bars(*k), needed)))
    fired = 0
    for (alert_id, user_id, symbol, alert_type, threshold, created_at), req in plans:
        hit = alert_eval.evaluate(alert_type, symbol, threshold, created_at, bars[(symbol, *req)])
        if hit and database.mark_alert_triggered(alert_id, user_id, hit["triggered_at"], hit["price"],
                                                 hit["message"]):
            fired += 1
    return fired


@app.route("/alerts", methods=["POST"])
@require_auth
def create_alert() -> tuple:
    """Create a new alert owned by the signed-in user."""
    data = request.json or {}

    symbol = _clean_symbol(data.get("symbol"))
    alert_type = data.get("alert_type")
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    if alert_type not in _ALERT_TYPES:
        return jsonify({"error": "unknown alert type"}), 400
    try:
        threshold, multiplier, zscore_val = (
            None if data.get(k) is None else float(data[k])
            for k in ("threshold", "multiplier", "zscore"))
    except (TypeError, ValueError):
        return jsonify({"error": "threshold, multiplier and zscore must be numbers"}), 400
    if alert_type in alert_eval.PRICE_TYPES and not (threshold and np.isfinite(threshold) and threshold > 0):
        return jsonify({"error": "a price alert needs a price above zero"}), 400
    if database.count_active_alerts(g.user_id) >= MAX_ACTIVE_ALERTS:
        return jsonify({"error": f"you can have up to {MAX_ACTIVE_ALERTS} active alerts"}), 400

    alert_id = database.create_alert(
        symbol,
        alert_type,
        threshold,
        multiplier,
        zscore_val,
        user_id=g.user_id,
    )

    return jsonify({"status": "ok", "alert_id": alert_id})


@app.route("/alerts/<int:alert_id>", methods=["DELETE"])
@require_auth
def delete_alert(alert_id: int) -> tuple:
    """Delete one of the signed-in user's alerts."""
    database.delete_alert(alert_id, g.user_id)
    return jsonify({"status": "deleted"})


@app.route("/macro")
def macro() -> tuple:
    """Return latest FRED macro indicator snapshot (cached 1 h)."""
    fred_key = os.environ.get("FRED_API_KEY", "")
    if not fred_key:
        return jsonify({"error": "FRED_API_KEY not configured — add it in the Render dashboard Environment tab"}), 503

    cached = _cache.get("macro_snapshot")
    if cached is not None:
        return jsonify(cached)

    snapshot = get_macro_snapshot(fred_key)

    # If every series returned None the key is almost certainly invalid
    if all(v.get("value") is None for v in snapshot.values()):
        return jsonify({"error": "FRED returned no data — API key is likely invalid or FRED is down. Get a free key at fred.stlouisfed.org/docs/api/api_key.html"}), 502

    _cache.set("macro_snapshot", snapshot, ttl=_FRED_TTL)
    return jsonify(snapshot)


def _get_macro_context() -> str:
    """Return a formatted macro context string for Ski, using the cache."""
    fred_key = os.environ.get("FRED_API_KEY", "")
    if not fred_key:
        return ""
    cached = _cache.get("macro_snapshot")
    if cached is None:
        cached = get_macro_snapshot(fred_key)
        _cache.set("macro_snapshot", cached, ttl=_FRED_TTL)
    return format_macro_context(cached)


# ─────────────────────────────────────────────────────────────
# Portfolio Endpoints
# ─────────────────────────────────────────────────────────────

def _enrich_holding(h: dict) -> dict:
    """Add current price, market value, and P&L to a raw holding dict."""
    symbol = h["symbol"]
    shares = h["shares"]
    avg_cost = h.get("avg_cost")

    rows = database.get_recent_prices(symbol, limit=1)
    if rows:
        current_price = rows[0][1]
    else:
        current_price = get_stock_price(symbol)

    market_value = round(shares * current_price, 2) if current_price else None

    pnl_pct = None
    pnl_abs = None
    if current_price and avg_cost:
        pnl_pct = round((current_price - avg_cost) / avg_cost * 100, 2)
        pnl_abs = round((current_price - avg_cost) * shares, 2)

    return {
        **h,
        "current_price": round(current_price, 4) if current_price else None,
        "market_value": market_value,
        "pnl_pct": pnl_pct,
        "pnl_abs": pnl_abs,
    }


@app.route("/portfolio", methods=["GET"])
@require_auth
def get_portfolio_route() -> tuple:
    """Return the signed-in user's holdings enriched with current prices and P&L."""
    holdings = [_enrich_holding(h) for h in database.get_portfolio(g.user_id)]

    total_value = sum(h["market_value"] for h in holdings if h["market_value"])
    cost_basis = sum(
        h["shares"] * h["avg_cost"]
        for h in holdings
        if h["avg_cost"]
    )
    total_pnl_pct = (
        round((total_value - cost_basis) / cost_basis * 100, 2)
        if cost_basis else None
    )
    total_pnl_abs = round(total_value - cost_basis, 2) if cost_basis else None

    return jsonify({
        "holdings": holdings,
        "total_value": round(total_value, 2),
        "total_pnl_pct": total_pnl_pct,
        "total_pnl_abs": total_pnl_abs,
    })


@app.route("/portfolio", methods=["POST"])
@require_auth
def add_holding_route() -> tuple:
    """Add or update one of the signed-in user's holdings."""
    data = request.json or {}
    symbol = _clean_symbol(data.get("symbol"))
    shares = data.get("shares")
    avg_cost = data.get("avg_cost")

    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    try:
        shares = float(shares)
        if shares <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "shares must be a positive number"}), 400
    if avg_cost is not None:
        try:
            avg_cost = float(avg_cost)
            if avg_cost < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "avg_cost must be a non-negative number"}), 400

    holding_id = database.upsert_holding(g.user_id, symbol, shares, avg_cost)
    return jsonify({"status": "ok", "id": holding_id})


@app.route("/portfolio/<int:holding_id>", methods=["DELETE"])
@require_auth
def delete_holding_route(holding_id: int) -> tuple:
    """Remove one of the signed-in user's holdings."""
    database.delete_holding(holding_id, g.user_id)
    return jsonify({"status": "deleted"})


_SAMPLE_MAX_HOLDINGS = 10


def _parse_sample_portfolio(raw) -> list:
    """Validate the example portfolio a signed-out visitor is trying.

    It comes from the browser, so it is treated as untrusted: real-looking
    symbols, positive share counts and a hard cap on size. Anything else is
    dropped rather than rejected, so a bad row never blocks the chat.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw[:_SAMPLE_MAX_HOLDINGS]:
        if not isinstance(row, dict):
            continue
        symbol = re.sub(r"[^A-Z0-9.-]", "", str(row.get("symbol") or "").upper())[:10]
        try:
            shares = float(row.get("shares"))
            avg_cost = float(row["avg_cost"]) if row.get("avg_cost") is not None else None
        except (TypeError, ValueError):
            continue
        if not symbol or not 0 < shares < 1e7 or (avg_cost is not None and not 0 < avg_cost < 1e7):
            continue
        out.append({"symbol": symbol, "shares": shares, "avg_cost": avg_cost})
    return out


def _get_portfolio_context(user_id: Optional[int], sample: Optional[list] = None) -> str:
    """Format a user's portfolio for injection into Ski's context.

    Beyond raw holdings, this surfaces each position's weight (concentration),
    the portfolio's computed risk metrics (Sharpe, beta, volatility), and the
    user's watchlist — so Ski can reason about diversification and risk, not
    just list positions.

    A signed-out visitor can instead pass ``sample``, the example portfolio
    the dashboard offers; it is labelled as such and has no risk metrics or
    watchlist.
    """
    if user_id is None and not sample:
        return ""
    raw = database.get_portfolio(user_id) if user_id is not None else sample
    holdings = [_enrich_holding(h) for h in raw]
    if not holdings:
        return ""

    total_value = sum(h["market_value"] for h in holdings if h.get("market_value"))
    total_cost = sum(
        h["shares"] * h["avg_cost"] for h in holdings if h.get("avg_cost")
    )

    if user_id is None:
        lines = [f"SAMPLE PORTFOLIO — {datetime.date.today()} (the user is not signed in and is "
                 "trying Tradeski with this example portfolio; treat it as theirs for the "
                 "conversation, and mention it is a sample if they ask about saving it. Risk "
                 "metrics are not computed for the sample, so do not mention them or "
                 "point to a risk panel):"]
    else:
        lines = [f"USER'S PORTFOLIO — {datetime.date.today()}:"]

    # Largest positions first so Ski leads with what matters most.
    ordered = sorted(
        holdings, key=lambda h: h.get("market_value") or 0, reverse=True
    )
    for h in ordered:
        symbol = h["symbol"]
        shares = h["shares"]
        avg_cost = h.get("avg_cost")
        current = h.get("current_price")
        mv = h.get("market_value")

        line = f"  {symbol}: {shares} shares"
        if avg_cost:
            line += f" @ ${avg_cost:.2f} avg cost"
        if current:
            line += f" | price ${current:.2f}"
        if mv:
            line += f" | value ${mv:,.2f}"
            if total_value:
                line += f" | {mv / total_value * 100:.0f}% of portfolio"
        if h.get("pnl_pct") is not None:
            sign = "+" if h["pnl_pct"] >= 0 else ""
            line += f" | P&L {sign}{h['pnl_pct']:.1f}% (${h['pnl_abs']:+,.2f})"
        lines.append(line)

    if total_value:
        lines.append(f"  TOTAL VALUE: ${total_value:,.2f}")
    if total_cost and total_value:
        pnl = (total_value - total_cost) / total_cost * 100
        sign = "+" if pnl >= 0 else ""
        lines.append(f"  TOTAL P&L: {sign}{pnl:.1f}%")

    # Concentration note — the single biggest position by weight.
    if total_value and len(ordered) > 1 and ordered[0].get("market_value"):
        top = ordered[0]
        top_wt = top["market_value"] / total_value * 100
        if top_wt >= 40:
            lines.append(
                f"  CONCENTRATION: {top['symbol']} is {top_wt:.0f}% of the portfolio "
                f"— flag single-name concentration risk when relevant."
            )

    if user_id is None:
        return "\n".join(lines)

    risk = _portfolio_risk_cached(user_id)
    if risk:
        lines.append(
            "  RISK METRICS (1Y daily returns, value-weighted): "
            f"Sharpe {risk['sharpe']} (risk-free rate {risk.get('risk_free_pct', 4.5)}%), "
            f"beta vs S&P 500 {risk['beta']}, "
            f"annualized volatility {risk['volatility']}%."
        )

    watch = database.get_watchlist(user_id)
    if watch:
        lines.append(f"  WATCHLIST (not held): {', '.join(watch[:15])}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# News + Sentiment Endpoints
# ─────────────────────────────────────────────────────────────

def _fetch_cached_news(symbol: str) -> list:
    """Return cached article list for symbol, fetching if stale."""
    news_key = os.environ.get("NEWS_API_KEY", "")
    if not news_key:
        return []
    cache_key = f"news:{symbol}"
    articles = _cache.get(cache_key)
    if articles is None:
        articles = fetch_news(symbol, news_key)
        _cache.set(cache_key, articles, ttl=_NEWS_TTL)
    return articles


@app.route("/news")
def news_endpoint() -> tuple:
    """Return scored headlines + aggregate sentiment for a symbol."""
    symbol   = request.args.get("symbol", "AAPL").upper()
    news_key = os.environ.get("NEWS_API_KEY", "")

    if not news_key:
        return jsonify({"error": "NEWS_API_KEY not configured"}), 503

    articles = _fetch_cached_news(symbol)
    agg      = aggregate_sentiment(articles)

    return jsonify({
        "symbol":    symbol,
        "articles":  articles,
        "aggregate": agg,
    })


def _get_news_context(symbol: str) -> str:
    """Format recent news sentiment as a context string for Ski."""
    if not symbol:
        return ""
    articles = _fetch_cached_news(symbol)
    if not articles:
        return ""
    return format_news_context(symbol, articles, aggregate_sentiment(articles))


def _format_chart_context(ctx: dict) -> str:
    """Format the user's current chart indicator snapshot for Ski."""
    if not isinstance(ctx, dict):
        return ""
    # The snapshot comes from the browser: keep only finite numbers, so a
    # malformed value is dropped instead of crashing the format strings below.
    ctx = {
        k: (_finite(v) if k not in ("symbol", "timeframe") else v)
        for k, v in ctx.items()
    }
    symbol = _clean_symbol(ctx.get("symbol")) or ""
    tf = re.sub(r"[^A-Za-z0-9]", "", str(ctx.get("timeframe") or ""))[:4]
    lines = [f"CURRENT CHART — {symbol} ({tf} timeframe):"]

    close = ctx.get("close")
    if close is not None:
        lines.append(f"  Latest close: ${close:.2f}")

    rsi = ctx.get("rsi")
    if rsi is not None:
        sig = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
        lines.append(f"  RSI (14): {rsi:.1f} — {sig}")

    macd = ctx.get("macd")
    signal = ctx.get("macd_signal")
    hist = ctx.get("macd_histogram")
    if macd is not None and signal is not None:
        lines.append(f"  MACD: {macd:.3f}, Signal: {signal:.3f} ({_macd_state(macd, signal, hist, ctx.get('macd_histogram_prev'))})")

    sma20 = ctx.get("sma20")
    sma50 = ctx.get("sma50")
    ema20 = ctx.get("ema20")
    if sma20 is not None:
        lines.append(f"  SMA 20: ${sma20:.2f}")
    if sma50 is not None:
        lines.append(f"  SMA 50: ${sma50:.2f}")
    if ema20 is not None:
        lines.append(f"  EMA 20: ${ema20:.2f}")

    upper = ctx.get("upper_band")
    lower = ctx.get("lower_band")
    if upper is not None and lower is not None and sma20 is not None:
        lines.append(f"  Bollinger Bands: Upper ${upper:.2f} / Mid ${sma20:.2f} / Lower ${lower:.2f}")

    zscore = ctx.get("zscore")
    if zscore is not None:
        lines.append(f"  Z-Score: {zscore:.2f}")

    vol = ctx.get("volatility")
    if vol is not None:
        lines.append(f"  Volatility (standard deviation of the last 20 closes, in dollars): ${vol:.2f}")

    return "\n".join(lines)


def _finite(value) -> Optional[float]:
    """Return value as a finite float, or None (bools, strings, NaN and inf included)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:  # a JSON integer too large for a float, e.g. 10**400
        return None
    return value if np.isfinite(value) else None


def _macd_state(macd: float, signal: float, hist, hist_prev) -> str:
    """Describe MACD vs its signal line without calling every bar a crossover.

    A crossover is the bar where the histogram changes sign. Otherwise MACD is
    simply above or below its signal line, which is a weaker statement.
    """
    if hist is None:
        hist = macd - signal
    side = "above" if hist > 0 else "below" if hist < 0 else "on"
    text = f"histogram {hist:+.3f}; MACD {side} its signal line"
    if hist_prev is not None and hist != 0 and (hist > 0) != (hist_prev > 0):
        text += ", bullish crossover on the latest bar" if hist > 0 else ", bearish crossover on the latest bar"
    return text


# ─────────────────────────────────────────────────────────────
# Screener Endpoint
# ─────────────────────────────────────────────────────────────

def _fetch_screener_row(symbol: str) -> dict | None:
    """Return cached screener row for symbol, fetching from yfinance if stale."""
    cache_key = f"screener:{symbol}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    row = get_screener_data(symbol)
    if row:
        _cache.set(cache_key, row, ttl=_SCREENER_TTL)
    return row


@app.route("/screener")
def screener() -> tuple:
    """Return fundamental data for the built-in stock universe (parallel fetch, cached)."""
    stocks: list = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_screener_row, sym): sym for sym in _SCREENER_UNIVERSE}
        for future in as_completed(futures):
            row = future.result()
            if row:
                stocks.append(row)
    stocks.sort(key=lambda r: r["symbol"])
    stocks = _fill_from_filings(stocks)
    return jsonify({"stocks": stocks, "universe_size": len(_SCREENER_UNIVERSE)})


_filings_warm_lock = threading.Lock()


def _fill_from_filings(rows: list) -> list:
    """Fill blank P/E and market cap from SEC filings (when SEC_USER_AGENT is set).

    Only filings already in the cache are used, so the screener never waits on
    EDGAR. Missing ones are fetched by one background warm-up (throttled to
    SEC's rate limit), and appear on a later load.
    """
    if not sec_fundamentals.user_agent():
        return rows
    out, missing = [], []
    for row in rows:
        if row.get("pe") is not None and row.get("market_cap") is not None:
            out.append(row)
            continue
        base = _cache.get(f"ski_filings:{row['symbol']}")
        if base is None:
            missing.append(row["symbol"])
            out.append(row)
            continue
        filed = sec_fundamentals.with_price(base, row.get("price")) if base else {}
        row = dict(row)  # the cached screener row is shared; never mutate it
        if row.get("pe") is None and filed.get("pe_trailing") is not None:
            row["pe"], row["pe_source"] = filed["pe_trailing"], "sec_filings"
        if row.get("market_cap") is None and filed.get("market_cap_usd"):
            row["market_cap"] = int(filed["market_cap_usd"])
        out.append(row)
    if missing and _filings_warm_lock.acquire(blocking=False):
        def warm():
            try:
                for sym in missing:
                    _cached_filings(sym, None)
            finally:
                _filings_warm_lock.release()
        threading.Thread(target=warm, daemon=True).start()
    return out


# ─────────────────────────────────────────────────────────────
# Options: chain, strategy builder, scanner
# ─────────────────────────────────────────────────────────────

_OPTIONS_SCAN_MAX = 10
_DEFAULT_RATE = 0.04


def _risk_free_rate() -> tuple:
    """(annual rate, where it came from): the 3-month Treasury yield from FRED."""
    obs = _cached_macro_history("DGS3MO", 1)
    try:
        return float(obs[0]["value"]) / 100.0, "the 3-month Treasury yield, from FRED"
    except (IndexError, KeyError, TypeError, ValueError):
        return _DEFAULT_RATE, "an assumed rate: FRED was unavailable"


def _cached_expiries(symbol: str) -> list:
    """Future expiries only: one that closed today can no longer be priced."""
    key = f"opt_exp:{symbol}"
    exp = _cache.get(key)
    if exp is None:
        exp = get_option_expirations(symbol)
        _cache.set(key, exp, ttl=_OPTIONS_TTL)
    return [e for e in exp if opt.year_fraction(e) > 0]


def _cached_chain(symbol: str, expiry: str) -> Optional[dict]:
    """A cleaned chain (IV and Greeks computed here), cached for five minutes."""
    key = f"opt_chain:{symbol}:{expiry}"
    chain = _cache.get(key)
    if chain is None:
        raw = get_option_chain(symbol, expiry)
        if not raw:
            return None
        rate, rate_source = _risk_free_rate()
        chain = opt.clean_chain(raw, expiry, rate)
        chain["rate_source"] = rate_source
        closes = [b["close"] for b in _cached_bars(symbol, "3mo")]
        hv = opt.realized_vol(closes, 30)
        chain["realized_vol_30d"] = round(hv, 4) if hv else None
        chain["as_of"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        _cache.set(key, chain, ttl=_OPTIONS_TTL)
    return chain


def _chain_for_dte(symbol: str, target_dte: int) -> Optional[dict]:
    """The chain whose expiry is nearest ``target_dte`` days out (for Ski)."""
    expiries = _cached_expiries(symbol)
    if not expiries:
        return None
    expiry = min(expiries, key=lambda e: abs(opt.days_to_expiry(e) - target_dte))
    return _cached_chain(symbol, expiry)


def _option_args(body: dict) -> tuple:
    """(symbol, expiry, error response) from the JSON body or query string.

    An unknown or missing expiry falls back to the one nearest 20-60 days out.
    """
    sym = _clean_symbol(body.get("symbol") or request.args.get("symbol"))
    if not sym:
        return None, None, (jsonify({"error": "symbol is required"}), 400)
    expiries = _cached_expiries(sym)
    if not expiries:
        return sym, None, (jsonify({"error": f"no listed options found for {sym}"}), 404)
    expiry = body.get("expiry") or request.args.get("expiry") or ""
    if expiry not in expiries:
        expiry = opt.pick_expiry(expiries, 20, 60) or expiries[0]
    return sym, expiry, None


def _chain_error(sym: str, expiry: str) -> tuple:
    return jsonify({"error": f"could not load the {sym} {expiry} chain; try again shortly"}), 502


@app.route("/options/expirations")
def options_expirations() -> tuple:
    sym = _clean_symbol(request.args.get("symbol"))
    if not sym:
        return jsonify({"error": "symbol is required"}), 400
    expiries = _cached_expiries(sym)
    return jsonify({
        "symbol": sym,
        "expirations": [{"date": e, "dte": opt.days_to_expiry(e)} for e in expiries],
        "default": opt.pick_expiry(expiries, 20, 60) or (expiries[0] if expiries else None),
    })


@app.route("/options/chain")
@limiter.limit("60 per minute")
def options_chain() -> tuple:
    sym, expiry, err = _option_args({})
    if err:
        return err
    chain = _cached_chain(sym, expiry)
    return jsonify(chain) if chain else _chain_error(sym, expiry)


@app.route("/options/strategy", methods=["POST"])
@limiter.limit("60 per minute")
def options_strategy() -> tuple:
    """Build a strategy from a preset, or price user-chosen legs, and analyse it."""
    body = request.get_json(silent=True) or {}
    sym, expiry, err = _option_args(body)
    if err:
        return err
    chain = _cached_chain(sym, expiry)
    if not chain:
        return _chain_error(sym, expiry)
    try:
        if body.get("legs"):
            legs = opt.legs_from_request(body["legs"], chain)
        else:
            legs = opt.build_preset(str(body.get("preset") or ""), chain)
        days = body.get("days_forward")
        days = float(days) if isinstance(days, (int, float)) and not isinstance(days, bool) else None
        result = opt.analyze(legs, chain["spot"], chain["years"], chain["rate"], chain["dividend_yield"],
                             sigma=chain["atm_iv"], symbol=sym, expiry=expiry, days_forward=days)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    result.update({"symbol": sym, "expiry": expiry, "dte": chain["dte"], "spot": chain["spot"],
                   "atm_iv": chain["atm_iv"], "market_state": chain.get("market_state")})
    return jsonify(result)


@app.route("/options/scan")
@limiter.limit("10 per minute")
def options_scan() -> tuple:
    """Best cash-secured put or covered call per symbol, under the given filters."""
    kind = request.args.get("kind", "cash_secured_put")
    if kind not in opt.SCAN_KINDS:
        return jsonify({"error": f"kind must be one of {', '.join(opt.SCAN_KINDS)}"}), 400
    raw = request.args.get("symbols", "")
    syms = [s for s in dict.fromkeys(_clean_symbol(x) for x in raw.split(",")) if s][:_OPTIONS_SCAN_MAX]
    if not syms:
        return jsonify({"error": "give one or more symbols, comma separated"}), 400

    def num(name, default, lo, hi):
        try:
            return max(lo, min(hi, float(request.args.get(name, default))))
        except (TypeError, ValueError):
            return default

    min_dte, max_dte = int(num("min_dte", 20, 0, 365)), int(num("max_dte", 50, 1, 730))
    filters = {"max_delta": num("max_delta", 0.30, 0.05, 0.6), "min_oi": int(num("min_oi", 100, 0, 1e6)),
               "max_spread_pct": num("max_spread", 10, 1, 100)}

    def one(sym):
        expiry = opt.pick_expiry(_cached_expiries(sym), min_dte, max_dte, (min_dte + max_dte) // 2)
        if not expiry:
            return {"symbol": sym, "skipped": f"no expiry between {min_dte} and {max_dte} days"}
        chain = _cached_chain(sym, expiry)
        if not chain:
            return {"symbol": sym, "skipped": "chain unavailable"}
        return opt.scan_candidate(kind, chain, **filters) or {"symbol": sym, "skipped": "nothing passes the filters"}

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(one, syms))
    found = sorted((r for r in rows if "skipped" not in r), key=lambda r: -r["annualized_pct"])
    return jsonify({"kind": kind, "filters": {**filters, "min_dte": min_dte, "max_dte": max_dte},
                    "results": found, "skipped": [r for r in rows if "skipped" in r]})


# ─────────────────────────────────────────────────────────────
# Correlation Heatmap
# ─────────────────────────────────────────────────────────────

@app.route("/correlation")
def correlation_endpoint() -> tuple:
    """Return 90-day return correlation matrix for tracked symbols."""
    cached = _cache.get("correlation")
    if cached:
        return jsonify(cached)

    closes: dict = {}
    for sym in _CORR_SYMS:
        bars = get_ohlc_history(sym, "3mo", "1d")
        if bars and len(bars) > 15:
            closes[sym] = [b["close"] for b in bars]

    if len(closes) < 2:
        return jsonify({"error": "Insufficient data"}), 503

    min_len = min(len(v) for v in closes.values())
    syms = list(closes.keys())

    returns_matrix = []
    for sym in syms:
        prices = np.array(closes[sym][-min_len:], dtype=float)
        returns_matrix.append(np.diff(prices) / prices[:-1])

    corr = np.corrcoef(returns_matrix)
    result = {
        "symbols": syms,
        "matrix": [[round(float(corr[i][j]), 3) for j in range(len(syms))] for i in range(len(syms))],
    }
    _cache.set("correlation", result, ttl=_CORR_TTL)
    return jsonify(result)


# ─────────────────────────────────────────────────────────────
# Portfolio Risk Metrics
# ─────────────────────────────────────────────────────────────

DEFAULT_RISK_FREE = 0.045  # used only when FRED is unavailable


def _risk_free_rate() -> Tuple[float, str]:
    """Annual risk-free rate as a fraction, and where it came from.

    The effective federal funds rate from the FRED snapshot the dashboard
    already fetches (cached an hour). A hardcoded 4.5% made every Sharpe ratio
    wrong by however far rates had moved.
    """
    fred_key = os.environ.get("FRED_API_KEY", "")
    snap = _cache.get("macro_snapshot")
    if snap is None and fred_key:
        try:
            snap = get_macro_snapshot(fred_key)
            _cache.set("macro_snapshot", snap, ttl=_FRED_TTL)
        except Exception:
            snap = None
    value = ((snap or {}).get("FEDFUNDS") or {}).get("value")
    if isinstance(value, (int, float)) and np.isfinite(value) and 0 <= value < 25:
        return value / 100, "fed_funds"
    return DEFAULT_RISK_FREE, "default"


def _compute_portfolio_risk(holdings: List[dict]) -> Tuple[Optional[dict], Optional[str]]:
    """Compute Sharpe, beta vs SPY, and annualized vol from enriched holdings.

    Returns (metrics, None) on success or (None, reason) when it can't be computed.
    """
    valued = [h for h in holdings if h.get("market_value") and h["market_value"] > 0]
    if not valued:
        return None, "No valued holdings"

    total_value = sum(h["market_value"] for h in valued)
    fetch_syms = list({h["symbol"] for h in valued}) + ["SPY"]

    price_data: dict = {}
    for sym in fetch_syms:
        bars = get_ohlc_history(sym, "1y", "1d")
        if bars and len(bars) > 20:
            prices = np.array([b["close"] for b in bars], dtype=float)
            price_data[sym] = np.diff(prices) / prices[:-1]

    if "SPY" not in price_data:
        return None, "Insufficient data"

    min_len = min(len(v) for v in price_data.values())
    aligned = {k: v[-min_len:] for k, v in price_data.items()}

    port_returns = np.zeros(min_len)
    for h in valued:
        sym = h["symbol"]
        if sym in aligned:
            port_returns += (h["market_value"] / total_value) * aligned[sym]

    spy_returns = aligned["SPY"]
    std = float(np.std(port_returns))
    if std == 0:
        return None, "Insufficient variance"

    risk_free, rf_source = _risk_free_rate()
    RISK_FREE_DAILY = risk_free / 252
    ann_vol = round(std * float(np.sqrt(252)) * 100, 1)
    sharpe = round(float((np.mean(port_returns) - RISK_FREE_DAILY) / std * np.sqrt(252)), 2)
    spy_var = float(np.var(spy_returns))
    beta = round(float(np.cov(port_returns, spy_returns)[0][1] / spy_var), 2) if spy_var > 0 else 1.0

    return {"sharpe": sharpe, "beta": beta, "volatility": ann_vol,
            "risk_free_pct": round(risk_free * 100, 2), "risk_free_source": rf_source}, None


def _portfolio_risk_cached(user_id: int) -> Optional[dict]:
    """Return cached portfolio risk metrics for a user, computing them if stale."""
    key = f"risk:{user_id}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    holdings = [_enrich_holding(h) for h in database.get_portfolio(user_id)]
    result, _err = _compute_portfolio_risk(holdings)
    if result is not None:
        _cache.set(key, result, ttl=300)
    return result


@app.route("/portfolio/risk")
@require_auth
def portfolio_risk_endpoint() -> tuple:
    """Return Sharpe ratio, beta vs SPY, and annualized volatility for the user's portfolio."""
    holdings = [_enrich_holding(h) for h in database.get_portfolio(g.user_id)]
    result, err = _compute_portfolio_risk(holdings)
    if result is None:
        return jsonify({"error": err}), 404 if err == "No valued holdings" else 503
    _cache.set(f"risk:{g.user_id}", result, ttl=300)
    return jsonify(result)


# Claude Haiku 5.5: a tenth of Haiku 4.5's price for prompts under 100K tokens.
# It thinks before answering by default, and that thinking counts against
# max_tokens -- so effort is "low" (quick chat, little thinking) and the caps leave
# room for it, or a long thought could crowd out the reply entirely.
SKI_MODEL = "claude-haiku-5-5"
SKI_EFFORT = {"effort": "low"}
SKI_EMPTY = "Sorry, I couldn't generate a response just now — try again."
SKI_REFUSAL = ("I can't help with that one. Try asking about your holdings, "
               "the market, or the macro data on your dashboard.")

_SKI_SYSTEM_PROMPT = """You are Ski, a financial Q&A assistant built into the Tradeski real-time market analytics platform. \
You are sharp, concise, and authoritative — like a seasoned Wall Street analyst who can explain complex concepts clearly \
to retail traders.

Your areas of expertise:

CORE FINANCIAL CONCEPTS
- Equities: stocks, ETFs, IPOs, stock splits, dividends, buybacks, short selling, margin trading
- Fixed income: bonds, yield curves, duration, credit spreads, Treasury rates
- Derivatives: options (calls/puts, Greeks, IV, covered calls), futures, hedging strategies
- Market structure: order types, bid-ask spread, market makers, dark pools, circuit breakers
- Valuation: P/E, P/S, EV/EBITDA, DCF, book value, earnings per share, revenue growth

MACROECONOMIC TRENDS AND MARKET CONSEQUENCES
Federal Reserve policy:
  - Rate hikes → higher borrowing costs → pressure on growth/tech stocks (higher discount rate lowers DCF valuations); \
banking sector spreads widen (net interest margin expands, benefiting bank stocks); housing/mortgage-sensitive names fall
  - Rate cuts → growth/tech stocks re-rate higher; financials compress; bond prices rise; \
REITs and dividend stocks become more attractive; USD typically weakens
  - Quantitative tightening (QT) → liquidity withdrawal → risk assets sell off
  - Yield curve inversion (2s10s) → historically precedes recession by 12–18 months; watch regional bank stocks

Inflation dynamics:
  - CPI/PCE beats → hawkish Fed expectations → rates up → tech/growth down; commodities, energy, materials outperform
  - Disinflation → growth stocks re-rate; consumer discretionary recovers
  - Stagflation → defensive sectors (utilities, consumer staples, healthcare) outperform; real assets outperform

Economic growth indicators:
  - Strong GDP / PMI beats → cyclicals (industrials, materials, financials) outperform; risk-on rotation
  - Weak GDP / recession fears → defensives, Treasuries, gold rally; credit spreads widen
  - Unemployment rate: falling UE → inflationary → hawkish; rising UE → dovish pivot bets → growth rally

Currency and global macro:
  - Strong USD → headwind for multinationals (revenue translated back at worse rates); commodities priced in USD fall
  - Weak USD → tailwind for exporters; emerging markets rally; gold and commodities rise
  - China stimulus → commodity producers, luxury goods, semiconductors benefit
  - Geopolitical risk → oil spikes → energy stocks; defense contractors; safe-haven flows into gold, USD, Treasuries

SECTOR ROTATION AND MICROECONOMIC TRENDS
- Tech earnings beats (FAANG/MAG7) → sector multiple expansion; semiconductor cycle drives memory/foundry stocks
- Energy: oil supply/demand balance, OPEC cuts, inventory data (EIA weekly) drive XLE, refiners
- Healthcare: FDA approvals, drug pricing legislation, biotech binary events (trial readouts)
- Consumer: retail sales data, confidence surveys, credit card delinquency rates signal consumer health
- Real estate: mortgage rates directly impact homebuilders and REITs; cap rates vs. Treasury spreads matter
- Financials: credit quality, loan growth, net interest margin, reserve releases
- Industrials: PMI, capex cycles, reshoring trends, defense budgets
- Semiconductors: PC/smartphone/server demand cycles; AI capex buildout (NVDA, AMD, TSM)

MARKET INDICATORS TO WATCH (background knowledge only: Tradeski does NOT feed you any of these readings, \
so never quote a current value for them unless a web search just returned it)
- VIX (volatility index): spike above 20 = fear; above 30 = panic; mean-reversion after spikes
- Put/call ratio: elevated = bearish sentiment / potential contrarian buy
- Credit spreads (HY, IG): widening = risk-off; compressing = risk-on
- AAII sentiment: extreme bearish readings historically contrarian bullish
- Options flow: unusual call sweeps = institutional bullish positioning
- Short interest: high short interest + positive catalyst = potential short squeeze

WHAT DATA YOU ACTUALLY HAVE
Only what appears in the sections below this prompt: the macro snapshot (FRED), the user's portfolio, recent \
headlines for the symbol on their chart, and the latest values of that chart's indicators (close, RSI, MACD, \
SMA 20/50, EMA 20, Bollinger Bands, Z-Score, volatility). Any section can be missing.
You also have TOOLS. Use them instead of guessing, and call several at once when a question needs several:
- get_price_summary: returns, 52-week range, volatility and indicator trends for ANY ticker, not only the charted one, \nplus its return against the S&P 500 and its beta (use these for "is it the stock or the market?").
- get_fundamentals: sector, P/E, market cap for a ticker; when those are missing, a from_filings section has \ntrailing EPS, P/E, market cap, revenue growth and net margin computed from SEC filings.
- get_news: recent headlines for any ticker.
- get_correlation: how closely tickers move together (diversification questions).
- portfolio_what_if: the user's weights and risk before and after hypothetical trades ("what if I sold half my TSLA").
- get_macro_history: the trend of a macro series, not just its latest reading.
- get_options_overview: what a ticker's options imply (implied vs realised volatility, the expected move by an \
expiry, put/call ratios, the strikes with the most open interest).
- analyze_option_strategy: build a standard options strategy (covered call, spreads, straddle, iron condor...) \
from the live chain and get its cost, max profit and loss, break-evens and chance of profit. Say that strikes follow \
fixed rules and prices are delayed midpoints, and that the user can adjust it in the Options tab.
- web_search: for events, earnings dates, people in office, and anything else the tools above don't cover.
Rules:
- Quote a number only if it appears in the data below, in a tool result, or in a search result you just ran. Never \
estimate or recall a price, ratio or indicator reading from memory.
- Tradeski's tools are the source for prices, indicators and portfolio maths; prefer them to web search for those.
- If no tool or search can supply what was asked (trade-level options flow such as sweeps, VIX, short \
interest), say so plainly and answer conceptually.
- When relevant, suggest which indicators on the Tradeski dashboard are most useful for the user's question.

PORTFOLIO-AWARE BEHAVIOR
You have access to the user's actual portfolio — holdings with cost basis and live P&L, each position's WEIGHT (percent \
of the portfolio), the portfolio's computed RISK METRICS (Sharpe ratio, beta vs. the S&P 500, annualized volatility), any \
CONCENTRATION flag, and their WATCHLIST — plus current macro data and news, all injected below. Use it:
- Always reference the user's specific tickers, weights, and P&L rather than generic market commentary.
- Reason about risk and diversification: cite their beta when discussing market sensitivity, their volatility/Sharpe when \
discussing risk-adjusted performance, and call out single-name concentration when one position dominates.
- Prioritize: how does today's macro environment affect THIS user's specific, largest-weighted holdings? Lead with the \
positions most affected before general context.
- Treat watchlist names as candidates the user is considering but does not yet own.
Interpretation guide: beta > 1 means more volatile than the market (amplified moves); a Sharpe below ~1 is weak \
risk-adjusted return; a single position above ~40% of the book is concentrated. Explain these in plain language.

Keep answers focused and actionable. Use specific examples. If you don't know something, say so. Never give personalized \
investment advice — always clarify you're providing educational information, not a recommendation to buy or sell.

ANSWER FORMAT (the chat panel renders this as a card):
- First line: "Bottom line: " followed by a one-sentence answer to the question.
- Then the detail as 2 to 5 short bullets, each starting with "- ", or one or two short paragraphs for conceptual questions.
- Wrap the key figures in **double asterisks**, sparingly. No headings, no tables.
- Keep the whole answer under about 150 words unless the user asks for more."""


# Ski's tools. Code computes every number; the model picks what to look up.
SKI_MAX_TOOL_ROUNDS = 4
# Haiku 5.5 takes the basic web search variant (the _20260209 one with
# dynamic filtering is for Opus/Sonnet).
_SKI_WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


def _cached_bars(symbol: str, period: str) -> list:
    """Daily bars for a Ski tool, cached like the chart endpoints."""
    key = f"ski_bars:{symbol}:{period}"
    bars = _cache.get(key)
    if bars is None:
        bars = get_ohlc_history(symbol, period, "1d")
        if bars:
            _cache.set(key, bars, ttl=_CHART_TTL)
    return bars or []


def _cached_macro_history(series_id: str, count: int) -> list:
    fred_key = os.environ.get("FRED_API_KEY", "")
    if not fred_key:
        return []
    key = f"ski_fred:{series_id}:{count}"
    obs = _cache.get(key)
    if obs is None:
        obs = fetch_fred_observations(series_id, fred_key, limit=count)
        if obs:
            _cache.set(key, obs, ttl=_FRED_TTL)
    return obs or []


_FILINGS_TTL = 12 * 3600  # filings change once a quarter; the price moves, so not longer


def _cached_filings(symbol: str, price: Optional[float]) -> Optional[dict]:
    """Fundamentals from SEC filings (None unless SEC_USER_AGENT is set)."""
    if not sec_fundamentals.user_agent():
        return None
    if not price:
        bars = _cached_bars(symbol, "1y")
        price = bars[-1]["close"] if bars else None
    key = f"ski_filings:{symbol}"
    base = _cache.get(key)
    if base is None:
        base = sec_fundamentals.fundamentals(symbol) or {}
        _cache.set(key, base, ttl=_FILINGS_TTL)
    return sec_fundamentals.with_price(base, price) if base else None


def _ski_data(user_id: Optional[int], sample: Optional[list]) -> ski_tools.SkiData:
    """The data Ski's tools read, scoped to this user (or the signed-out sample)."""
    def holdings() -> list:
        if user_id is not None:
            return database.get_portfolio(user_id)
        return list(sample or [])

    def risk(raw: list) -> tuple:
        return _compute_portfolio_risk([_enrich_holding(h) for h in raw])

    return ski_tools.SkiData(
        bars=_cached_bars,
        fundamentals=_fetch_screener_row,
        news=_fetch_cached_news,
        macro_history=_cached_macro_history,
        holdings=holdings,
        risk=risk,
        filings=_cached_filings,
        options=_chain_for_dte,
    )


def _reply_text(response) -> str:
    # With tools the response holds several blocks (thinking, searches,
    # results, answer); the reply is the concatenation of the text blocks.
    return "".join(
        getattr(b, "text", "") for b in response.content
        if getattr(b, "type", None) == "text"
    ).strip()


def _system_blocks(system) -> list:
    """System prompt as content blocks, with a cache breakpoint after the fixed part.

    ``system`` is a string, or a sequence whose first item is the fixed prompt
    (the same for every user) and the rest is per-request context. Tools come
    before the system prompt in the cached prefix, so tools plus the fixed
    prompt are cached across all users and requests.
    """
    if isinstance(system, str):
        return [{"type": "text", "text": system}]
    fixed, *rest = system
    blocks = [{"type": "text", "text": fixed, "cache_control": {"type": "ephemeral"}}]
    if any(rest):
        blocks.append({"type": "text", "text": "\n\n".join(r for r in rest if r)})
    return blocks


def _run_ski(client, system, messages: list, data: ski_tools.SkiData, web_search: bool = True) -> dict:
    """Ask Ski, running its tool calls until it answers (at most SKI_MAX_TOOL_ROUNDS rounds).

    ``system`` is as for _system_blocks. Returns {"reply", "tools_used", "tool_outputs", "search_texts"}; the last
    two are the evidence the reply's numbers are checked against.
    """
    messages = list(messages)
    first_turn = len(messages)
    # If the account or model rejects a tool feature, fall back step by step
    # (drop web search, then all tools) rather than failing the chat outright.
    tool_sets = [[_SKI_WEB_SEARCH, *ski_tools.TOOLS], list(ski_tools.TOOLS), []]
    if not web_search:
        tool_sets.pop(0)
    system_blocks = _system_blocks(system)
    tools_used: list = []
    lookups: list = []
    outputs: list = []
    search_texts: list = []
    response = None

    def done(reply: str) -> dict:
        return {"reply": reply, "tools_used": tools_used, "lookups": list(dict.fromkeys(lookups)),
                "tool_outputs": outputs, "search_texts": search_texts}

    for round_no in range(SKI_MAX_TOOL_ROUNDS + 1):
        while True:
            # Top-level cache_control also caches the conversation so far, so
            # each tool round re-reads the previous rounds from cache.
            kwargs = dict(model=SKI_MODEL, max_tokens=4096, output_config=SKI_EFFORT,
                          system=system_blocks, messages=messages, cache_control={"type": "ephemeral"})
            if tool_sets[0]:
                kwargs["tools"] = tool_sets[0]
                if round_no == SKI_MAX_TOOL_ROUNDS:
                    kwargs["tool_choice"] = {"type": "none"}  # out of rounds: answer now
            try:
                response = client.messages.create(**kwargs)
                break
            except (anthropic.BadRequestError, anthropic.PermissionDeniedError):
                if len(messages) != first_turn or len(tool_sets) == 1:
                    raise
                app.logger.warning("Ski request rejected with tools %s; retrying with fewer",
                                   [t["name"] for t in tool_sets[0]])
                tool_sets.pop(0)

        # A safety classifier can decline a request: HTTP 200 with no answer text.
        if response.stop_reason == "refusal":
            return done(SKI_REFUSAL)

        # Server-side searches run inside the response; record them and keep
        # what they showed the model as evidence.
        searches = [b for b in response.content if getattr(b, "type", None) == "server_tool_use"]
        tools_used += [getattr(b, "name", "web_search") for b in searches]
        lookups += ["web search" for _ in searches]
        search_texts += ski_grounding.evidence_from_response_blocks(response.content)

        if response.stop_reason == "pause_turn":
            # A long server-side web search paused; send it back to resume.
            messages.append({"role": "assistant", "content": response.content})
            continue

        calls = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        if response.stop_reason != "tool_use" or not calls:
            break

        messages.append({"role": "assistant", "content": response.content})
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(
                lambda b: ski_tools.tool_result_block(b.id, b.name, b.input, data), calls))
        # Every result goes back in one user message, as the API expects.
        messages.append({"role": "user", "content": [block for block, _ in results]})
        tools_used += [b.name for b in calls]
        lookups += [ski_tools.describe_call(b.name, b.input) for b in calls]
        outputs += [out for _, out in results if out is not None]

    return done(_reply_text(response) or SKI_EMPTY)


@app.route("/chat", methods=["POST"])
@limiter.limit("20 per hour; 50 per day")
@optional_auth
def chat() -> tuple:
    """Ski financial Q&A chatbot powered by Claude."""
    data = request.json or {}
    raw_msg = (data.get("message") or "")
    message = re.sub(r'<[^>]+>', '', raw_msg).strip()[:500]
    history = data.get("history") or []
    symbol  = _clean_symbol(data.get("symbol"))
    chart_context = data.get("chart_context") or {}

    if not message:
        return jsonify({"error": "No message provided"}), 400

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "AI service not configured"}), 503

    # Build system prompt
    system_parts = [_SKI_SYSTEM_PROMPT]
    now = datetime.datetime.now(datetime.timezone.utc)
    system_parts.append(
        f"CURRENT DATE: Today is {now:%A, %B %d, %Y}. "
        "Your built-in knowledge has a training cutoff and may be stale for time-sensitive facts — "
        "who currently holds offices (e.g. the Federal Reserve Chair), the latest Fed rate decisions, "
        "recent economic data releases (CPI, jobs reports), earnings, or breaking news. Whenever a "
        "question depends on a current fact that could have changed since your training, USE THE "
        "web_search TOOL to verify it and answer from those fresh results instead of from memory. "
        "Briefly mention the source/date when you rely on a search."
    )
    macro_ctx = _get_macro_context()
    if macro_ctx:
        system_parts.append(macro_ctx)
    user_id = g.get("user_id")
    sample = _parse_sample_portfolio(data.get("sample_portfolio")) if user_id is None else None
    portfolio_ctx = _get_portfolio_context(user_id, sample)
    if portfolio_ctx:
        system_parts.append(portfolio_ctx)
    news_ctx = _get_news_context(symbol)
    if news_ctx:
        system_parts.append(news_ctx)
    if chart_context:
        system_parts.append(_format_chart_context(chart_context))

    # Build messages list — Anthropic requires strict user/assistant alternation
    messages = []
    expected_role = "user"
    for turn in history[-10:]:
        role = (turn.get("role") or "").strip()
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if role != expected_role:
            continue
        messages.append({"role": role, "content": content})
        expected_role = "assistant" if expected_role == "user" else "user"

    # Current message must go last as "user"
    if messages and messages[-1]["role"] == "user":
        messages.append({"role": "assistant", "content": "..."})
    messages.append({"role": "user", "content": message})

    try:
        client = anthropic.Anthropic(api_key=api_key)
        system_prompt = "\n\n".join(system_parts)
        result = _run_ski(client, system_parts, messages, _ski_data(user_id, sample))
        # Log-only for now: are the reply's numbers in the data Ski was given?
        # The history is evidence too, since Ski may repeat its earlier figures.
        grounding = ski_grounding.check(
            result["reply"],
            [system_prompt, *result["search_texts"], *(m["content"] for m in messages if isinstance(m["content"], str))],
            result["tool_outputs"],
        )
        if not grounding["grounded"] and result["reply"] != SKI_REFUSAL:
            app.logger.warning("Ski reply has figures not found in its data: %s (tools: %s)",
                               grounding["ungrounded"], result["tools_used"])
        return jsonify({
            "reply": result["reply"],
            "tools_used": result["tools_used"],
            "lookups": result["lookups"],
            "grounded": grounding["grounded"],
            "ungrounded_figures": grounding["ungrounded"],
        })
    except anthropic.RateLimitError:
        return jsonify({"error": "Ski is at capacity — I've hit my hourly AI quota. Try again in a few minutes."}), 429
    except anthropic.APIStatusError as exc:
        if exc.status_code == 529:
            return jsonify({"error": "Anthropic API is overloaded right now. Try again in 30 seconds."}), 503
        return jsonify({"error": f"AI service error ({exc.status_code})"}), 502
    except Exception:
        app.logger.exception("AI request failed")
        return jsonify({"error": "AI service error. Try again in a moment."}), 502


_SKI_BRIEFING_PROMPT = """You are Ski, the financial-intelligence assistant built into Tradeski. \
Generate a short, PROACTIVE briefing on THIS user's portfolio from the context provided below \
(their real holdings, position weights, P&L, risk metrics, live macro data, and recent news). \
You may call tools for facts the context lacks: get_price_summary for how their largest positions have moved \
recently, get_correlation for how related their holdings are. Keep it to one or two rounds of tool calls. \
Every number you cite must come from the context or a tool result.

Format rules — follow them exactly:
- Output 3 to 4 bullets, each starting with "• " and each a single sentence.
- Most important first: lead with the biggest risk or the biggest mover in THEIR book right now.
- Every bullet must cite a specific number from the context — a position weight %, beta, Sharpe, \
annualized volatility, P&L %, or a macro figure (CPI, Fed funds rate, unemployment). No vague filler.
- After the bullets, add one final line starting with "Watch: " naming the single most relevant thing \
to keep an eye on next: a technical level from a tool result, or the next release of a macro series in the \
context (CPI, jobs, the Fed). You have no earnings calendar, so never state an earnings date.
- No greeting, no preamble, no headers, no sign-off — the bullets and the Watch line only.
- Educational only. Never phrase anything as a recommendation to buy or sell."""


@app.route("/briefing", methods=["POST"])
@limiter.limit("30 per hour; 100 per day")
@require_auth
def briefing() -> tuple:
    """Proactive, portfolio-grounded briefing Ski generates for the dashboard.

    Unlike /chat (reactive Q&A), this needs no user question: it pulls the same
    live context — macro snapshot, the user's holdings + risk metrics, and news
    for their largest position — and asks Ski to surface what matters right now.
    Result is cached per user (15 min) so dashboard loads don't burn AI quota.
    """
    user_id = g.user_id

    holdings = database.get_portfolio(user_id)
    if not holdings:
        return jsonify({"briefing": None, "reason": "no_holdings"})

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "AI service not configured"}), 503

    cache_key = f"briefing:{user_id}"
    if request.args.get("refresh") != "1":
        cached = _cache.get(cache_key)
        if cached:
            return jsonify({"briefing": cached, "cached": True})

    # Same grounded context Ski uses in chat: macro, portfolio + risk, and news
    # for the single largest holding (where headline risk hits hardest).
    system_parts = [_SKI_BRIEFING_PROMPT]
    now = datetime.datetime.now(datetime.timezone.utc)
    system_parts.append(f"CURRENT DATE: Today is {now:%A, %B %d, %Y}.")

    macro_ctx = _get_macro_context()
    if macro_ctx:
        system_parts.append(macro_ctx)

    portfolio_ctx = _get_portfolio_context(user_id)
    if portfolio_ctx:
        system_parts.append(portfolio_ctx)

    enriched = [_enrich_holding(h) for h in holdings]
    enriched.sort(key=lambda h: h.get("market_value") or 0, reverse=True)
    top_symbol = enriched[0]["symbol"] if enriched else ""
    news_ctx = _get_news_context(top_symbol) if top_symbol else ""
    if news_ctx:
        system_parts.append(news_ctx)

    messages = [{"role": "user", "content": "Give me today's briefing on my portfolio."}]

    try:
        client = anthropic.Anthropic(api_key=api_key)
        # Same tool loop as chat, minus web search: the briefing loads with the
        # dashboard, so it should stay quick and cheap.
        result = _run_ski(client, system_parts, messages, _ski_data(user_id, None), web_search=False)
        reply = result["reply"]
        if reply == SKI_REFUSAL:
            return jsonify({"briefing": None, "reason": "refusal"})
        if reply == SKI_EMPTY:
            return jsonify({"briefing": None, "reason": "empty"})
        grounding = ski_grounding.check(reply, ["\n\n".join(system_parts)], result["tool_outputs"])
        if not grounding["grounded"]:
            app.logger.warning("Ski briefing has figures not found in its data: %s", grounding["ungrounded"])
        _cache.set(cache_key, reply, ttl=900)
        return jsonify({"briefing": reply, "cached": False})
    except anthropic.RateLimitError:
        return jsonify({"error": "Ski is at capacity — hourly AI quota reached."}), 429
    except anthropic.APIStatusError as exc:
        if exc.status_code == 529:
            return jsonify({"error": "Anthropic API is overloaded right now."}), 503
        return jsonify({"error": f"AI service error ({exc.status_code})"}), 502
    except Exception:
        app.logger.exception("AI request failed")
        return jsonify({"error": "AI service error. Try again in a moment."}), 502


# ─────────────────────────────────────────────────────────────
# WebSocket Broadcasts
# ─────────────────────────────────────────────────────────────

# Alerts are delivered by the owner's own /alerts poll, never by a socket
# broadcast: an emit with no room would reach every connected visitor.


# ─────────────────────────────────────────────────────────────
# Background price tracker
# ─────────────────────────────────────────────────────────────

def _background_tracker() -> None:
    """Fetch prices on an interval and push WebSocket updates."""
    raw_symbols = os.environ.get("STOCK_SYMBOLS", "AAPL,MSFT,TSLA,NVDA,AMZN")
    symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
    interval = int(os.environ.get("CHECK_INTERVAL", "60"))

    while True:
        for sym in symbols:
            try:
                price = get_stock_price(sym)
                if price is not None:
                    database.insert_price(sym, price)
                    socketio.emit(
                        "price_update",
                        {
                            "symbol": sym,
                            "price": price,
                            "timestamp": time.time(),
                        },
                    )
            except Exception:
                pass
        # Check alerts while awake. Moves made while asleep are caught too,
        # because alerts are evaluated against price history, not ticks.
        try:
            _check_alerts(database.get_active_alerts_for_eval())
        except Exception:
            app.logger.exception("background alert check failed")
        time.sleep(interval)


# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────

database.init_db()
socketio.start_background_task(_background_tracker)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
