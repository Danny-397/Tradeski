# Adds SMA20 and EMA20 

import yfinance as yf
from .cache import SimpleCache

cache = SimpleCache()

# This reduces yfinacnce calls by 95%
@app.route("/stats")
def stats():
    symbol = request.args.get("symbol", "AAPL").upper()
    cache_key = f"stats_{symbol}"

    # Try cache first
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
        "low_52w": float(hist["Low"].min())
    }

    # Cache for 60 seconds
    cache.set(cache_key, result, ttl=60)

    return jsonify(result)

# Caches RSI calcs 
# makes dashboard feel instant 
@app.route("/rsi")
def rsi():
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
        "rsi": rsi_values.fillna(0).tolist()
    }

    # Cache for 60 seconds
    cache.set(cache_key, result, ttl=60)

    return jsonify(result)



@app.route("/price_history")
def price_history():
    # Get symbol from query parameter
    symbol = request.args.get("symbol", "AAPL").upper()

    # Get last 200 prices for this symbol
    rows = database.get_recent_prices(symbol, limit=200)

    timestamps = [ts for ts, price in rows]
    prices = [price for ts, price in rows]

    # Simple SMA and EMA calculations
    def sma(values, window):
        if len(values) < window:
            return [None] * len(values)
        return [None] * (window - 1) + [
            sum(values[i - window + 1:i + 1]) / window
            for i in range(window - 1, len(values))
        ]

    def ema(values, window):
        if len(values) < window:
            return [None] * len(values)
        ema_values = [None] * len(values)
        k = 2 / (window + 1)
        ema_values[window - 1] = sum(values[:window]) / window
        for i in range(window, len(values)):
            ema_values[i] = (
                values[i] * k + ema_values[i - 1] * (1 - k)
            )
        return ema_values

    sma20 = sma(prices, 20)
    ema20 = ema(prices, 20)

    return jsonify({
        "timestamps": timestamps,
        "prices": prices,
        "sma20": sma20,
        "ema20": ema20
    })

