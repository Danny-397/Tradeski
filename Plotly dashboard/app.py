# dashboard/app.py
# Adds SMA20 and EMA20, plus caching and WebSocket support.

import yfinance as yf
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO

from .cache import SimpleCache
from tracker.database import database  # Ensure DB is imported

# Flask application setup
app = Flask(__name__)

# WebSocket server
socketio = SocketIO(app, cors_allowed_origins="*")

# In‑memory cache for stats + RSI
cache = SimpleCache()


# Stats endpoint (cached)
@app.route("/stats")
def stats():
    """Return OHLC + 52‑week stats for a symbol."""
    symbol = request.args.get("symbol", "AAPL").upper()
    cache_key = f"stats_{symbol}"

    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="1y")

    if hist.empty:
        return jsonify({"error": "No data"}), 400

    today = hist.iloc[-1]

    result = {
        "symbol": symbol,
        "open": float(today["Open"]),
        "high": float(today["High"]),
        "low": float(today["Low"]),
        "close": float(today["Close"]),
        "high_52w": float(hist["High"].max()),
        "low_52w": float(hist["Low"].min()),
    }

    cache.set(cache_key, result, ttl=60)
    return jsonify(result)


# RSI endpoint (cached)
@app.route("/rsi")
def rsi():
    """Return RSI(14) values for a symbol."""
    symbol = request.args.get("symbol", "AAPL").upper()
    cache_key = f"rsi_{symbol}"

    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached)

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="3mo")

    if hist.empty:
        return jsonify({"error": "No data"}), 400

    close_prices = hist["Close"]

    delta = close_prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss
    rsi_values = 100 - (100 / (1 + rs))

    result = {
        "timestamps": hist.index.strftime("%Y-%m-%d %H:%M:%S").tolist(),
        "rsi": rsi_values.fillna(0).tolist(),
    }

    cache.set(cache_key, result, ttl=60)
    return jsonify(result)


# Price history + SMA/EMA
@app.route("/price_history")
def price_history():
    """Return last 200 prices + SMA20 + EMA20."""
    symbol = request.args.get("symbol", "AAPL").upper()

    # Get last 200 rows from DB
    rows = database.get_recent_prices(symbol, limit=200)

    timestamps = [ts for ts, price in rows]
    prices = [price for ts, price in rows]

    # Simple SMA
    def sma(values, window):
        if len(values) < window:
            return [None] * len(values)
        prefix = [None] * (window - 1)
        series = [
            sum(values[i - window + 1:i + 1]) / window
            for i in range(window - 1, len(values))
        ]
        return prefix + series

    # Simple EMA
    def ema(values, window):
        if len(values) < window:
            return [None] * len(values)
        ema_values = [None] * len(values)
        k_factor = 2 / (window + 1)
        ema_values[window - 1] = sum(values[:window]) / window
        for i in range(window, len(values)):
            ema_values[i] = (
                values[i] * k_factor +
                ema_values[i - 1] * (1 - k_factor)
            )
        return ema_values

    sma20 = sma(prices, 20)
    ema20 = ema(prices, 20)

    return jsonify(
        {
            "timestamps": timestamps,
            "prices": prices,
            "sma20": sma20,
            "ema20": ema20,
        }
    )


# Alert CRUD endpoints
@app.route("/alerts", methods=["POST"])
def create_alert():
    """Create a new alert rule."""
    data = request.json
    alert_id = database.create_alert(
        symbol=data["symbol"],
        alert_type=data["alert_type"],
        threshold=data.get("threshold"),
        multiplier=data.get("multiplier"),
        zscore=data.get("zscore"),
    )
    return jsonify({"status": "ok", "alert_id": alert_id})


@app.route("/alerts", methods=["GET"])
def list_alerts():
    """Return all active alerts."""
    alerts = database.get_alerts()
    return jsonify(alerts)


@app.route("/alerts/<int:alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    """Delete an alert rule."""
    database.delete_alert(alert_id)
    return jsonify({"status": "deleted"})


# WebSocket accessor
def get_socketio():
    """Expose Socket.IO instance to tracker."""
    return socketio


# Entry point
if __name__ == "__main__":
    
    # Run Flask + WebSocket server
    socketio.run(app, debug=True)
