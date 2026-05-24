const API_BASE = "http://localhost:5000";  // Change to Railway URL after deploy
const socket = io(API_BASE);

const chartDiv = document.getElementById("price-chart");
const statsDiv = document.getElementById("stats-content");
const alertsDiv = document.getElementById("alerts-feed");
const symbolSelect = document.getElementById("symbol-select");

let currentSymbol = "AAPL";

async function loadPriceHistory(symbol) {
    const res = await fetch(`${API_BASE}/price_history?symbol=${symbol}`);
    const data = await res.json();

    const tracePrice = {
        x: data.timestamps,
        y: data.prices,
        type: "scatter",
        name: "Price",
        line: { color: "#4caf50" }
    };

    const traceSMA = {
        x: data.timestamps,
        y: data.sma20,
        type: "scatter",
        name: "SMA20",
        line: { color: "#2196f3" }
    };

    const traceEMA = {
        x: data.timestamps,
        y: data.ema20,
        type: "scatter",
        name: "EMA20",
        line: { color: "#ff9800" }
    };

    Plotly.newPlot(chartDiv, [tracePrice, traceSMA, traceEMA], {
        paper_bgcolor: "#111",
        plot_bgcolor: "#111",
        font: { color: "#eee" }
    });
}

async function loadStats(symbol) {
    const res = await fetch(`${API_BASE}/stats?symbol=${symbol}`);
    const data = await res.json();

    statsDiv.innerHTML = `
        <p>Open: ${data.open}</p>
        <p>High: ${data.high}</p>
        <p>Low: ${data.low}</p>
        <p>Close: ${data.close}</p>
        <p>52W High: ${data.high_52w}</p>
        <p>52W Low: ${data.low_52w}</p>
    `;
}

function setupWebSocket() {
    socket.on("connect", () => {
        console.log("Connected to WebSocket");
    });

    socket.on("price_update", (msg) => {
        if (msg.symbol !== currentSymbol) return;

        Plotly.extendTraces(chartDiv, {
            y: [[msg.price]],
            x: [[msg.timestamp]]
        }, [0]);
    });

    socket.on("alert_triggered", (alert) => {
        const div = document.createElement("div");
        div.textContent = `${alert.symbol}: ${alert.message}`;
        alertsDiv.prepend(div);
    });
}

symbolSelect.addEventListener("change", () => {
    currentSymbol = symbolSelect.value;
    loadPriceHistory(currentSymbol);
    loadStats(currentSymbol);
});

loadPriceHistory(currentSymbol);
loadStats(currentSymbol);
setupWebSocket();
