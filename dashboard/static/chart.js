// Fetch price history and update the Plotly chart
// javascript
// lightweigth display for graphs
// works in real time nad on any laptop with no GPU needed 
async function fetchPriceHistory() {
    const response = await fetch("/price_history");
    return await response.json();
}

async function updateChart() {
    const data = await fetchPriceHistory();

    const times = data.map(p => p.timestamp);
    const prices = data.map(p => p.price);

    const trace = {
        x: times,
        y: prices,
        mode: "lines",
        line: { color: "blue" },
        name: "Price"
    };

    const layout = {
        title: "Real-Time Stock Price",
        xaxis: { title: "Time" },
        yaxis: { title: "Price (USD)" }
    };

    Plotly.newPlot("chart", [trace], layout);
}

// Initial load
updateChart();

// Refresh every 5 seconds
setInterval(updateChart, 5000);
