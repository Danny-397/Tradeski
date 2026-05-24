// dashboard.js
// Frontend logic for FinSeek dashboard: charts, stats, alerts, WebSocket.

const API_BASE = "http://localhost:5000";  // Change to your Railway URL in production
const socket = io(API_BASE);

const chartDiv = document.getElementById("price-chart");
const statsDiv = document.getElementById("stats-content");
const alertsDiv = document.getElementById("alerts-feed");
const symbolSelect = document.getElementById("symbol-select");

let currentSymbol = "AAPL";

// Load full price history and indicators, then render charts
async function loadPriceHistory(symbol) {
    const res = await fetch(`${API_BASE}/price_history?symbol=${symbol}`);
    const data = await res.json();

    // Main price series (candles)
    const traceCandle = {
        x: data.timestamps,
        open: data.open,
        high: data.high,
        low: data.low,
        close: data.close,
        type: "candlestick",
        name: "Price",
        xaxis: "x",
        yaxis: "y"
    };

    // SMA20 and EMA20 overlays
    const traceSMA = {
        x: data.timestamps,
        y: data.sma20,
        type: "scatter",
        mode: "lines",
        name: "SMA20",
        line: { color: "#2196f3" },
        xaxis: "x",
        yaxis: "y"
    };

    const traceEMA = {
        x: data.timestamps,
        y: data.ema20,
        type: "scatter",
        mode: "lines",
        name: "EMA20",
        line: { color: "#ff9800" },
        xaxis: "x",
        yaxis: "y"
    };

    // Optional Bollinger Bands (if provided)
    const tracesBands = [];
    if (data.upper_band && data.lower_band) {
        tracesBands.push({
            x: data.timestamps,
            y: data.upper_band,
            type: "scatter",
            mode: "lines",
            name: "Upper Band",
            line: { color: "#888", width: 1 },
            xaxis: "x",
            yaxis: "y"
        });
        tracesBands.push({
            x: data.timestamps,
            y: data.lower_band,
            type: "scatter",
            mode: "lines",
            name: "Lower Band",
            line: { color: "#888", width: 1 },
            xaxis: "x",
            yaxis: "y"
        });
    }

    // Volume bars (secondary y-axis on first row)
    const traceVolume = {
        x: data.timestamps,
        y: data.volume,
        type: "bar",
        name: "Volume",
        marker: { color: "#444" },
        xaxis: "x",
        yaxis: "y2",
        opacity: 0.5
    };

    // RSI subplot (row 2)
    const traceRSI = {
        x: data.timestamps,
        y: data.rsi,
        type: "scatter",
        mode: "lines",
        name: "RSI(14)",
        line: { color: "#9c27b0" },
        xaxis: "x2",
        yaxis: "y3"
    };

    // MACD subplot (row 3)
    const traceMACD = {
        x: data.timestamps,
        y: data.macd,
        type: "scatter",
        mode: "lines",
        name: "MACD",
        line: { color: "#03a9f4" },
        xaxis: "x3",
        yaxis: "y4"
    };

    const traceSignal = {
        x: data.timestamps,
        y: data.signal,
        type: "scatter",
        mode: "lines",
        name: "Signal",
        line: { color: "#ff5722" },
        xaxis: "x3",
        yaxis: "y4"
    };

    const traceHist = {
        x: data.timestamps,
        y: data.histogram,
        type: "bar",
        name: "Histogram",
        marker: { color: "#4caf50" },
        xaxis: "x3",
        yaxis: "y4",
        opacity: 0.6
    };

    const traces = [
        traceCandle,
        traceSMA,
        traceEMA,
        ...tracesBands,
        traceVolume,
        traceRSI,
        traceMACD,
        traceSignal,
        traceHist
    ];

    const layout = {
        paper_bgcolor: "#111",
        plot_bgcolor: "#111",
        font: { color: "#eee" },
        showlegend: true,
        grid: { rows: 3, columns: 1, pattern: "independent", roworder: "top to bottom" },

        // Row 1: Price + Volume
        xaxis: { domain: [0, 1], anchor: "y" },
        yaxis: { title: "Price", domain: [0.55, 1.0] },
        yaxis2: {
            title: "Volume",
            overlaying: "y",
            side: "right",
            showgrid: false
        },

        // Row 2: RSI
        xaxis2: { domain: [0, 1], anchor: "y3" },
        yaxis3: {
            title: "RSI",
            domain: [0.3, 0.5],
            range: [0, 100]
        },

        // Row 3: MACD
        xaxis3: { domain: [0, 1], anchor: "y4" },
        yaxis4: {
            title: "MACD",
            domain: [0.0, 0.25]
        },

        margin: { t: 30, l: 60, r: 60, b: 40 }
    };

    Plotly.newPlot(chartDiv, traces, layout);
}

// Load stats panel
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

// WebSocket setup for live updates and alerts
function setupWebSocket() {
    socket.on("connect", () => {
        console.log("Connected to WebSocket");
    });

    socket.on("price_update", (msg) => {
        if (msg.symbol !== currentSymbol) return;

        // Extend only the main price trace (candles) and volume
        // For simplicity, we just append a new point to price and volume.
        // In a real system, you might want to update the last candle instead.
        Plotly.extendTraces(
            chartDiv,
            {
                x: [[msg.timestamp], [msg.timestamp]],
                close: [[msg.price]],
                y: [[msg.volume]]
            },
            [0, 4]  // 0: candles, 4: volume (based on traces order above)
        );
    });

    socket.on("alert_triggered", (alert) => {
        const div = document.createElement("div");
        div.textContent = `${alert.symbol}: ${alert.message}`;
        alertsDiv.prepend(div);
    });
}

// Symbol selector
symbolSelect.addEventListener("change", () => {
    currentSymbol = symbolSelect.value;
    loadPriceHistory(currentSymbol);
    loadStats(currentSymbol);
});

// Initial load
currentSymbol = symbolSelect.value;
loadPriceHistory(currentSymbol);
loadStats(currentSymbol);
setupWebSocket();
