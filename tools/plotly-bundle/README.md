# Tradeski's Plotly bundle

`frontend/vendor/plotly-tradeski.min.js` is plotly.js 3.0.1 with only the trace
types the dashboard draws: scatter (in core), bar, candlestick and heatmap.
The full CDN bundle was 4.65 MB (1.41 MB gzipped) and took ~2 s of main-thread
time to parse on Lighthouse's mobile profile; this one is 1.13 MB (388 KB gzipped).

Adding a new chart type to `dashboard.js`? Register its module in `entry.js`
and rebuild, or Plotly will log "trace type ... is not registered" and draw nothing:

    cd tools/plotly-bundle
    npm install
    npm run build
