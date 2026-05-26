"""Plotly dashboard backend using Flask + Socket.IO for Tradeski."""

import sys
import os

# When run via gunicorn --chdir, the repo root is the parent of this file's directory.
# Insert it so `tracker` can always be found regardless of working directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import eventlet
eventlet.monkey_patch()

import time
import datetime
from typing import List, Tuple, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

import anthropic

from tracker import database
from tracker.price_fetcher import get_stock_price
from tracker.analyzer import (
    sma,
    ema,
    rsi,
    macd,
    bollinger_bands,
    zscore,
    volatility,
    linear_regression_prediction,
)

app = Flask(__name__)
CORS(app)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
)


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
# REST Endpoints
# ─────────────────────────────────────────────────────────────

@app.route("/health")
def health() -> tuple:
    return jsonify({"status": "ok"})


@app.route("/stats")
def stats() -> tuple:
    """Return basic OHLC + 52‑week stats for a symbol."""
    symbol = request.args.get("symbol", "AAPL")
    rows = database.get_recent_prices(symbol, limit=300)

    if not rows:
        return jsonify({"error": "No data"}), 404

    prices = [row[1] for row in rows]
    open_price = prices[0]
    close_price = prices[-1]
    high_price = max(prices)
    low_price = min(prices)

    change_pct = (
        (close_price - open_price) / open_price * 100
        if open_price else 0.0
    )

    return jsonify(
        {
            "symbol": symbol,
            "open": round(open_price, 4),
            "high": round(high_price, 4),
            "low": round(low_price, 4),
            "close": round(close_price, 4),
            "high_52w": round(high_price, 4),
            "low_52w": round(low_price, 4),
            "change_pct": round(change_pct, 4),
        }
    )


@app.route("/price_history")
def price_history() -> tuple:
    """Return price history + indicators."""
    symbol = request.args.get("symbol", "AAPL")
    limit = int(request.args.get("limit", 300))

    rows = database.get_recent_prices(symbol, limit=max(limit, 300))
    if not rows:
        return jsonify({"error": "No data"}), 404

    timestamps, prices, volume = rows_to_dict(rows, limit)

    sma20_vals = sma(prices, 20)
    sma50_vals = sma(prices, 50)
    ema20_vals = ema(prices, 20)
    rsi_vals = rsi(prices, 14)
    macd_line, signal_line, hist_vals = macd(prices)
    upper_band, lower_band = bollinger_bands(prices, 20)
    z_vals = zscore(prices, 20)
    vol_vals = volatility(prices, 20)
    prediction = linear_regression_prediction(prices)

    return jsonify(
        {
            "timestamps": timestamps,
            "prices": prices,
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": volume,
            "sma20": sma20_vals,
            "sma50": sma50_vals,
            "ema20": ema20_vals,
            "rsi": rsi_vals,
            "macd": macd_line,
            "signal": signal_line,
            "histogram": hist_vals,
            "upper_band": upper_band,
            "lower_band": lower_band,
            "zscore": z_vals,
            "volatility": vol_vals,
            "prediction": prediction,
        }
    )


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
def get_alerts() -> tuple:
    """Return all alerts."""
    return jsonify(database.get_alerts())


@app.route("/alerts", methods=["POST"])
def create_alert() -> tuple:
    """Create a new alert."""
    data = request.json or {}

    symbol = data.get("symbol")
    alert_type = data.get("alert_type")
    threshold = data.get("threshold")
    multiplier = data.get("multiplier")
    zscore_val = data.get("zscore")

    alert_id = database.create_alert(
        symbol,
        alert_type,
        threshold,
        multiplier,
        zscore_val,
    )

    return jsonify({"status": "ok", "alert_id": alert_id})


@app.route("/alerts/<int:alert_id>", methods=["DELETE"])
def delete_alert(alert_id: int) -> tuple:
    """Delete an alert."""
    database.delete_alert(alert_id)
    return jsonify({"status": "deleted"})


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

MARKET INDICATORS TO WATCH
- VIX (volatility index): spike above 20 = fear; above 30 = panic; mean-reversion after spikes
- Put/call ratio: elevated = bearish sentiment / potential contrarian buy
- Credit spreads (HY, IG): widening = risk-off; compressing = risk-on
- AAII sentiment: extreme bearish readings historically contrarian bullish
- Options flow: unusual call sweeps = institutional bullish positioning
- Short interest: high short interest + positive catalyst = potential short squeeze

TRADESKI PLATFORM
- You have access to real-time price data, technical indicators (RSI, MACD, Bollinger Bands, SMA, EMA, ATR, Z-Score, \
Stochastic, Linear Regression), and alert functionality
- When relevant, suggest which indicators on the Tradeski dashboard are most useful for the user's question

Keep answers focused and actionable. Use specific examples. If you don't know something, say so. Never give personalized \
investment advice — always clarify you're providing educational information, not a recommendation to buy or sell."""


@app.route("/chat", methods=["POST"])
def chat() -> tuple:
    """Ski financial Q&A chatbot powered by Claude."""
    data = request.json or {}
    message = (data.get("message") or "").strip()
    history = data.get("history") or []

    if not message:
        return jsonify({"error": "No message provided"}), 400

    client = anthropic.Anthropic()

    messages = []
    for turn in history[-10:]:
        role = turn.get("role")
        content = turn.get("content", "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": _SKI_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=messages,
    )

    return jsonify({"reply": response.content[0].text})


# ─────────────────────────────────────────────────────────────
# WebSocket Broadcasts
# ─────────────────────────────────────────────────────────────

def broadcast_price(
    symbol: str,
    price: float,
    change_pct: Optional[float] = None,
) -> None:
    """Broadcast price update."""
    socketio.emit(
        "price_update",
        {
            "symbol": symbol,
            "price": price,
            "change_pct": change_pct,
            "timestamp": time.time(),
        },
    )


def broadcast_alert(symbol: str, message: str) -> None:
    """Broadcast alert trigger."""
    socketio.emit(
        "alert_triggered",
        {
            "symbol": symbol,
            "message": message,
            "timestamp": time.time(),
        },
    )


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
                        namespace="/stream",
                    )
            except Exception:
                pass
        time.sleep(interval)


# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────

database.init_db()
socketio.start_background_task(_background_tracker)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
