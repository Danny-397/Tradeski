# Dashboard server for real-time Plotly charts
# API endpoint 

from flask import Flask, jsonify, render_template
from .. import database

app = Flask(__name__)


@app.route("/")
def index():
    # Serve the dashboard HTML
    return render_template("index.html")


@app.route("/price_history")
def price_history():
    # Return the last 200 price points for the chart
    rows = database.get_recent_prices("AAPL", limit=200)

    # rows = [(timestamp, price), ...]
    data = [
        {"timestamp": ts, "price": price}
        for ts, price in rows
    ]

    return jsonify(data)


def run_dashboard() -> None:
    # Start the dashboard server
    app.run(host="127.0.0.1", port=5001, debug=False)
