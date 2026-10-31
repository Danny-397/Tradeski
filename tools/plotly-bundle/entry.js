// Tradeski's Plotly: core plus the four trace types the dashboard draws.
'use strict';
var Plotly = require('plotly.js/lib/core');
Plotly.register([
    require('plotly.js/lib/bar'),
    require('plotly.js/lib/candlestick'),
    require('plotly.js/lib/heatmap'),
]);
module.exports = Plotly;
