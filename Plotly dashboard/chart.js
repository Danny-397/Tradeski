// Fetch price history and update the Plotly chart
// javascript
// lightweigth display for graphs
// works in real time nad on any laptop with no GPU needed 
// Added price line 
// SMA overlay 
// EMA overlay 
// Fetch price history for the selected stock
// Dark mode Plotly theme 
// Multi-stock switching 
// Auto-refresh


async function fetchRSI(symbol) {
    const response = await fetch(`/rsi?symbol=${symbol}`);
    return await response.json();
}


async function updateRSI(symbol) {
    const data = await fetchRSI(symbol);

    const rsiTrace = {
        x: data.timestamps,
        y: data.rsi,
        mode: "lines",
        line: { color: "#00eaff" },
        name: "RSI(14)",
        yaxis: "y2"
    };

    const overbought = {
        x: data.timestamps,
        y: Array(data.timestamps.length).fill(70),
        mode: "lines",
        line: { color: "#ff00d4", dash: "dot" },
        name: "Overbought"
    };

    const oversold = {
        x: data.timestamps,
        y: Array(data.timestamps.length).fill(30),
        mode: "lines",
        line: { color: "#ff00d4", dash: "dot" },
        name: "Oversold"
    };

    const layout = {
        paper_bgcolor: "#121212",
        plot_bgcolor: "#1e1e1e",
        font: { color: "#e0e0e0" },
        height: 300,
        margin: { t: 20 }
    };

    Plotly.newPlot("rsi-chart", [rsiTrace, overbought, oversold], layout);
}


async function updateStats(symbol) {
    const response = await fetch(`/stats?symbol=${symbol}`);
    const data = await response.json();

    document.getElementById("stat-symbol").textContent = data.symbol;
    document.getElementById("stat-open").textContent = `$${data.open.toFixed(2)}`;
    document.getElementById("stat-high").textContent = `$${data.high.toFixed(2)}`;
    document.getElementById("stat-low").textContent = `$${data.low.toFixed(2)}`;
    document.getElementById("stat-52wh").textContent = `$${data.high_52w.toFixed(2)}`;
    document.getElementById("stat-52wl").textContent = `$${data.low_52w.toFixed(2)}`;
}


async function fetchPriceHistory(symbol) {
    const response = await fetch(`/price_history?symbol=${symbol}`);
    return await response.json();
}

async function updateChart() {
    const symbol = document.getElementById("symbol-select").value;
    const data = await fetchPriceHistory(symbol);

    const times = data.timestamps;
    const prices = data.prices;
    const sma20 = data.sma20;
    const ema20 = data.ema20;

    const priceTrace = {
        x: times,
        y: prices,
        mode: "lines",
        line: { color: "#4da6ff" },
        name: `${symbol} Price`
    };
// Update stats card
document.getElementById("stat-symbol").textContent = symbol;
document.getElementById("stat-price").textContent = `$${prices[prices.length - 1].toFixed(2)}`;

    const smaTrace = {
        x: times,
        y: sma20,
        mode: "lines",
        line: { color: "#ffa64d" },
        name: "SMA 20"
    };

    const emaTrace = {
        x: times,
        y: ema20,
        mode: "lines",
        line: { color: "#7dff7d" },
        name: "EMA 20"
    };

    const layout = {
        paper_bgcolor: "#121212",
        plot_bgcolor: "#1e1e1e",
        font: { color: "#e0e0e0" },
        title: `${symbol} Real-Time Price`,
        xaxis: { title: "Time" },
        yaxis: { title: "Price (USD)" }
    };

    Plotly.newPlot("chart", [priceTrace, smaTrace, emaTrace], layout);
}

// Update chart when stock selection changes
document.getElementById("symbol-select").addEventListener("change", updateChart);

// Initial load
updateChart();updateStats(symbol);updateRSI(symbol);



// Refresh every 5 seconds
setInterval(updateChart, 5000);
