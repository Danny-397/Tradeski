"""Plotly dashboard backend using Flask + Socket.IO for Tradeski."""

import os
import time
import datetime
from typing import List, Tuple, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

from tracker import database
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
    async_mode="threading",
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

<<<<<<< HEAD
def _slice(rows, limit):
    """Return the last `limit` rows (oldest → newest)."""
    return rows[-limit:] if limit and limit < len(rows) else rows
=======
    return timestamps, prices, volume
>>>>>>> d8c46bd5fd781080e51d3572bbb987026c399a57


# ─────────────────────────────────────────────────────────────
# REST Endpoints
# ─────────────────────────────────────────────────────────────

@app.route("/stats")
def stats() -> tuple:
    """Return basic OHLC + 52‑week stats for a symbol."""
    symbol = request.args.get("symbol", "AAPL")
    rows = database.get_recent_prices(symbol, limit=300)

    if not rows:
        return jsonify({"error": "No data"}), 404

<<<<<<< HEAD
    prices = [r[1] for r in rows]
    open_p = prices[0]
    close_p = prices[-1]
    high_p = max(prices)
    low_p = min(prices)
    change_pct = ((close_p - open_p) / open_p * 100) if open_p else 0.0

    return jsonify({
        "symbol": symbol,
        "open": round(open_p, 4),
        "high": round(high_p, 4),
        "low": round(low_p, 4),
        "close": round(close_p, 4),
        "high_52w": round(high_p, 4),
        "low_52w": round(low_p, 4),
        "change_pct": round(change_pct, 4),
    })
=======
    prices = [row[1] for row in rows]
    open_price = prices[0]
    close_price = prices[-1]
    high_price = max(prices)
    low_price = min(prices)

    if open_price:
        change_pct = (close_price - open_price) / open_price * 100
    else:
        change_pct = 0.0

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
>>>>>>> d8c46bd5fd781080e51d3572bbb987026c399a57


@app.route("/price_history")
def price_history() -> tuple:
    """Return price history + indicators."""
    symbol = request.args.get("symbol", "AAPL")
    limit = int(request.args.get("limit", 300))

    rows = database.get_recent_prices(symbol, limit=max(limit, 300))
    if not rows:
        return jsonify({"error": "No data"}), 404

<<<<<<< HEAD
    rows = _slice(rows, limit)
    timestamps = [r[0] for r in rows]
    prices = [r[1] for r in rows]
    volume = [r[2] for r in rows]
=======
    timestamps, prices, volume = rows_to_dict(rows, limit)
>>>>>>> d8c46bd5fd781080e51d3572bbb987026c399a57

    sma20_vals = sma(prices, 20)
    sma50_vals = sma(prices, 50)
    ema20_vals = ema(prices, 20)
    rsi_vals = rsi(prices, 14)
<<<<<<< HEAD
    macd_line, sig, hist = macd(prices)
=======
    macd_line, signal_line, hist_vals = macd(prices)
>>>>>>> d8c46bd5fd781080e51d3572bbb987026c399a57
    upper_band, lower_band = bollinger_bands(prices, 20)
    z_vals = zscore(prices, 20)
    vol_vals = volatility(prices, 20)
    prediction = linear_regression_prediction(prices)

<<<<<<< HEAD
    return jsonify({
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
        "signal": sig,
        "histogram": hist,
        "upper_band": upper_band,
        "lower_band": lower_band,
        "zscore": z_vals,
        "volatility": vol_vals,
        "prediction": prediction,
    })


@app.route("/watchlist")
def watchlist():
    """Return latest price + pct_change for a comma-separated list of symbols."""
    raw = request.args.get("symbols", "AAPL,MSFT,TSLA,NVDA,AMZN")
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
=======
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

>>>>>>> d8c46bd5fd781080e51d3572bbb987026c399a57
    result = {}

    for sym in symbols:
        rows = database.get_recent_prices(sym, limit=2)
        if not rows:
            result[sym] = None
            continue
<<<<<<< HEAD
        prices = [r[1] for r in rows]
        open_p = prices[0]
        close_p = prices[-1]
        pct = ((close_p - open_p) / open_p * 100) if open_p else 0.0
        result[sym] = {
            "price": round(close_p, 4),
            "change_pct": round(pct, 4),
=======

        prices = [row[1] for row in rows]
        open_price = prices[0]
        close_price = prices[-1]

        if open_price:
            pct_change = (close_price - open_price) / open_price * 100
        else:
            pct_change = 0.0

        result[sym] = {
            "price": round(close_price, 4),
            "change_pct": round(pct_change, 4),
>>>>>>> d8c46bd5fd781080e51d3572bbb987026c399a57
        }

    return jsonify(result)


@app.route("/market_status")
<<<<<<< HEAD
def market_status():
    """Market-open heuristic based on UTC time."""
    import datetime
=======
def market_status() -> tuple:
    """Return simple market‑open heuristic based on server UTC time."""
>>>>>>> d8c46bd5fd781080e51d3572bbb987026c399a57
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
<<<<<<< HEAD
def create_alert():
    data = request.json or {}
=======
def create_alert() -> tuple:
    """Create a new alert."""
    data = request.json or {}

>>>>>>> d8c46bd5fd781080e51d3572bbb987026c399a57
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


# ─────────────────────────────────────────────────────────────
# WebSocket Broadcasts
# ─────────────────────────────────────────────────────────────

<<<<<<< HEAD
def broadcast_price(symbol, price, change_pct=None):
    socketio.emit("price_update", {
        "symbol": symbol,
        "price": price,
        "change_pct": change_pct,
        "timestamp": time.time(),
    })


def broadcast_alert(symbol, message):
    socketio.emit("alert_triggered", {
        "symbol": symbol,
        "message": message,
        "timestamp": time.time(),
    })
=======
def broadcast_price(symbol: str, price: float, change_pct: Optional[float] = None) -> None:
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
>>>>>>> d8c46bd5fd781080e51d3572bbb987026c399a57


# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    database.init_db()
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
