# Adds SMA20 and EMA20 

import yfinance as yf

@app.route("/stats")
def stats():
    symbol = request.args.get("symbol", "AAPL").upper()

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="1y")

    if hist.empty:
        return jsonify({"error": "No data"}), 400

    # Today's OHLC
    today = hist.iloc[-1]
    open_price = float(today["Open"])
    high_price = float(today["High"])
    low_price = float(today["Low"])
    close_price = float(today["Close"])

    # 52-week stats
    high_52w = float(hist["High"].max())
    low_52w = float(hist["Low"].min())

    return jsonify({
        "symbol": symbol,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "high_52w": high_52w,
        "low_52w": low_52w
    })


@app.route("/rsi")
def rsi():
    symbol = request.args.get("symbol", "AAPL").upper()

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="3mo")  # enough for RSI

    if hist.empty:
        return jsonify({"error": "No data"}), 400

    close_prices = hist["Close"]

    # RSI calculation
    delta = close_prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss
    rsi_values = 100 - (100 / (1 + rs))

    return jsonify({
        "timestamps": hist.index.strftime("%Y-%m-%d %H:%M:%S").tolist(),
        "rsi": rsi_values.fillna(0).tolist()
    })


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

