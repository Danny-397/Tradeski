// Fetch price history and update the Plotly chart
// javascript
// lightweigth display for graphs
// works in real time nad on any laptop with no GPU needed 
// Added price line 
// SMA overlay 
// EMA overlay 
async function fetchPriceHistory() {
    const response = await fetch("/price_history");
    return await response.json();
}

async function updateChart() {
    const data = await fetchPriceHistory();

    const times = data.timestamps;
    const prices = data.prices;
    const sma20 = data.sma20;
    const ema20 = data.ema20;

    const priceTrace = {
        x: times,
        y: prices,
        mode: "lines",
        line: { color: "blue" },
        name: "Price"
    };

    const smaTrace = {
        x: times,
        y: sma20,
        mode: "lines",
        line: { color: "orange" },
        name: "SMA 20"
    };

    const emaTrace = {
        x: times,
        y: ema20,
        mode: "lines",
        line: { color: "green" },
        name: "EMA 20"
    };

    const layout = {
        title: "Real-Time Stock Price",
        xaxis: { title: "Time" },
        yaxis: { title: "Price (USD)" }
    };

    Plotly.newPlot("chart", [priceTrace, smaTrace, emaTrace], layout);
}

updateChart();
setInterval(updateChart, 5000);
