# Adds SMA20 and EMA20 


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

