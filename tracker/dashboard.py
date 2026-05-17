from typing import List, Dict, Any
from flask import Flask, jsonify, render_template_string

from .database import get_recent_prices, get_recent_alerts
from .config import load_app_config
from .logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)
config = load_app_config()


INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Stock Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <h1>Stock Dashboard - {{ symbol }}</h1>
    <canvas id="priceChart" width="800" height="400"></canvas>

    <h2>Recent Alerts</h2>
    <ul id="alerts"></ul>

    <script>
        async function fetchData() {
            const priceRes = await fetch('/api/prices');
            const priceData = await priceRes.json();

            const labels = priceData.map(p => p.timestamp);
            const prices = priceData.map(p => p.price);

            const ctx = document.getElementById('priceChart').getContext('2d');
            window.priceChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Price',
                        data: prices,
                        borderColor: 'blue',
                        fill: false
                    }]
                }
            });

            const alertRes = await fetch('/api/alerts');
            const alerts = await alertRes.json();
            const list = document.getElementById('alerts');
            list.innerHTML = '';
            alerts.forEach(a => {
                const li = document.createElement('li');
                li.textContent = `${a.timestamp} - ${a.type}: ${a.message}`;
                list.appendChild(li);
            });
        }

        async function refresh() {
            const priceRes = await fetch('/api/prices');
            const priceData = await priceRes.json();
            const labels = priceData.map(p => p.timestamp);
            const prices = priceData.map(p => p.price);

            window.priceChart.data.labels = labels;
            window.priceChart.data.datasets[0].data = prices;
            window.priceChart.update();

            const alertRes = await fetch('/api/alerts');
            const alerts = await alertRes.json();
            const list = document.getElementById('alerts');
            list.innerHTML = '';
            alerts.forEach(a => {
                const li = document.createElement('li');
                li.textContent = `${a.timestamp} - ${a.type}: ${a.message}`;
                list.appendChild(li);
            });
        }

        fetchData();
        setInterval(refresh, 5000);
    </script>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    """
    Render the main dashboard page with the embedded chart and alert list.
    """
    return render_template_string(INDEX_HTML, symbol=config.stock_symbol)


@app.route("/api/prices")
def api_prices():
    """
    API endpoint returning recent price data for the configured symbol.

    Returns:
        JSON list of {timestamp, price} objects.
    """
    rows = get_recent_prices(config.stock_symbol, limit=200)
    return jsonify(
        [{"timestamp": ts, "price": price} for ts, price in rows]
    )


@app.route("/api/alerts")
def api_alerts():
    """
    API endpoint returning recent alerts for the configured symbol.

    Returns:
        JSON list of {timestamp, type, message} objects.
    """
    rows = get_recent_alerts(config.stock_symbol, limit=50)
    return jsonify(
        [{"timestamp": ts, "type": t, "message": msg} for ts, t, msg in rows]
    )


def run_dashboard() -> None:
    """
    Start the Flask dashboard server.
    """
    logger.info("Starting dashboard on http://127.0.0.1:5000")
    app.run(debug=False)
