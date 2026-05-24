# dashboard/app.py
# Main Flask + Socket.IO backend for FinSeek dashboard

import os
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

from tracker import database
from tracker.analyzer import (
    sma, ema, rsi, macd, bollinger_bands,
    zscore, volatility, linear_regression_prediction
)

# App Setup

app = Flask(__name__)
CORS(app)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)


# REST API Endpoints

@app.route("/stats")
def stats():
    symbol = request.args.get("symbol", "AAPL")
    rows = database.get_recent_prices(symbol, limit=200)

    if not rows:
        return jsonify({"error": "No data"}), 404

    prices = [r[1] for r in rows]
    high_52w = max(prices)
    low_52w = min(prices)

    return jsonify({
        "open": prices[0],
        "high": max(prices),
        "low": min(prices),
        "close": prices[-1],
        "high_52w": high_52w,
        "low_52w": low_52w
    })


@app.route("/price_history")
def price_history():
    symbol = request.args.get("symbol", "AAPL")
    rows = database.get_recent_prices(symbol, limit=300)

    if not rows:
        return jsonify({"error": "No data"}), 404

    timestamps = [r[0] for r in rows]
    prices = [r[1] for r in rows]
    volume = [r[2] for r in rows]

    # OHLC reconstruction (simple)
    open_prices = prices
    high_prices = prices
    low_prices = prices
    close_prices = prices

    # Indicators
    sma20_vals = sma(prices, 20)
    ema20_vals = ema(prices, 20)
    rsi_vals = rsi(prices, 14)
    macd_line, signal_line, histogram = macd(prices)
    upper_band, lower_band = bollinger_bands(prices, 20)
    z_vals = zscore(prices, 20)
    vol_vals = volatility(prices, 20)
    prediction = linear_regression_prediction(prices)

    return jsonify({
        "timestamps": timestamps,
        "prices": prices,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volume,
        "sma20": sma20_vals,
        "ema20": ema20_vals,
        "rsi": rsi_vals,
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
        "upper_band": upper_band,
        "lower_band": lower_band,
        "zscore": z_vals,
        "volatility": vol_vals,
        "prediction": prediction
    })


@app.route("/alerts", methods=["GET"])
def get_alerts():
    alerts = database.get_alerts()
    return jsonify(alerts)


@app.route("/alerts", methods=["POST"])
def create_alert():
    data = request.json
    symbol = data.get("symbol")
    alert_type = data.get("alert_type")
    threshold = data.get("threshold")
    multiplier = data.get("multiplier")
    zscore_val = data.get("zscore")

    alert_id = database.create_alert(
        symbol, alert_type, threshold, multiplier, zscore_val
    )

    return jsonify({"status": "ok", "alert_id": alert_id})


@app.route("/alerts/<int:alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    database.delete_alert(alert_id)
    return jsonify({"status": "deleted"})


# WebSocket Events


def broadcast_price(symbol, price):
    socketio.emit("price_update", {
        "symbol": symbol,
        "price": price,
        "timestamp": time.time()
    })


def broadcast_alert(symbol, message):
    socketio.emit("alert_triggered", {
        "symbol": symbol,
        "message": message,
        "timestamp": time.time()
    })


# App Runner

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
