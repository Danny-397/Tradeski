# inside dashboard/app.py

from flask import Flask, request, jsonify
from tracker import database
from tracker.analyzer import (
    sma, ema, rsi, macd, bollinger_bands,
    zscore, volatility, linear_regression_prediction
)

@app.route("/price_history")
def price_history():
    symbol = request.args.get("symbol", "AAPL")
    rows = database.get_recent_prices(symbol, limit=300)

    timestamps = [r[0] for r in rows]
    prices = [r[1] for r in rows]
    volume = [r[2] for r in rows]

    # OHLC reconstruction (simple method)
    open_prices = prices
    high_prices = prices
    low_prices = prices
    close_prices = prices

    sma20 = sma(prices, 20)
    ema20 = ema(prices, 20)
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
        "sma20": sma20,
        "ema20": ema20,
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
