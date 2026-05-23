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
updateChart();

// Refresh every 5 seconds
setInterval(updateChart, 5000);
