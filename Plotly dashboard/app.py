# Plotly dashboard/app.py
# Flask + Socket.IO backend for Tradeski dashboard

import os
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

from tracker import database
from tracker.analyzer import (
    sma, ema, rsi, macd, bollinger_bands,
    zscore, volatility, linear_regression_prediction,
)

app = Flask(__name__)
CORS(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# ── helpers ──────────────────────────────────────────────────

def _slice(rows, limit):
    """Return the last `limit` rows (oldest → newest)."""
    return rows[-limit:] if limit and limit < len(rows) else rows


# ── REST endpoints ────────────────────────────────────────────

@app.route("/stats")
def stats():
    symbol = request.args.get("symbol", "AAPL")
    rows = database.get_recent_prices(symbol, limit=300)

    if not rows:
        return jsonify({"error": "No data"}), 404

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


@app.route("/price_history")
def price_history():
    symbol = request.args.get("symbol", "AAPL")
    limit = int(request.args.get("limit", 300))

    rows = database.get_recent_prices(symbol, limit=max(limit, 300))
    if not rows:
        return jsonify({"error": "No data"}), 404

    rows = _slice(rows, limit)
    timestamps = [r[0] for r in rows]
    prices = [r[1] for r in rows]
    volume = [r[2] for r in rows]

    sma20_vals = sma(prices, 20)
    sma50_vals = sma(prices, 50)
    ema20_vals = ema(prices, 20)
    rsi_vals = rsi(prices, 14)
    macd_line, sig, hist = macd(prices)
    upper_band, lower_band = bollinger_bands(prices, 20)
    z_vals = zscore(prices, 20)
    vol_vals = volatility(prices, 20)
    prediction = linear_regression_prediction(prices)

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
    result = {}

    for sym in symbols:
        rows = database.get_recent_prices(sym, limit=2)
        if not rows:
            result[sym] = None
            continue
        prices = [r[1] for r in rows]
        open_p = prices[0]
        close_p = prices[-1]
        pct = ((close_p - open_p) / open_p * 100) if open_p else 0.0
        result[sym] = {
            "price": round(close_p, 4),
            "change_pct": round(pct, 4),
        }

    return jsonify(result)


@app.route("/market_status")
def market_status():
    """Market-open heuristic based on UTC time."""
    import datetime
    now = datetime.datetime.utcnow()
    day = now.weekday()
    hour = now.hour + now.minute / 60

    if day >= 5:
        status = "closed"
    elif 13.5 <= hour < 20:
        status = "open"
    elif (8 <= hour < 13.5) or (20 <= hour < 24):
        status = "extended"
    else:
        status = "closed"

    return jsonify({"status": status, "utc": now.isoformat()})


@app.route("/alerts", methods=["GET"])
def get_alerts():
    return jsonify(database.get_alerts())


@app.route("/alerts", methods=["POST"])
def create_alert():
    data = request.json or {}
    symbol = data.get("symbol")
    alert_type = data.get("alert_type")
    threshold = data.get("threshold")
    multiplier = data.get("multiplier")
    zscore_val = data.get("zscore")

    alert_id = database.create_alert(symbol, alert_type, threshold, multiplier, zscore_val)
    return jsonify({"status": "ok", "alert_id": alert_id})


@app.route("/alerts/<int:alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    database.delete_alert(alert_id)
    return jsonify({"status": "deleted"})


# ── WebSocket broadcasts ──────────────────────────────────────

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


# ── Runner ────────────────────────────────────────────────────

if __name__ == "__main__":
    database.init_db()
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
