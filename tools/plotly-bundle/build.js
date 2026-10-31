// Mirrors plotly.js 3.0.1's own esbuild-config.js, minus the glsl plugin
// (none of the bundled traces use WebGL).  Run: npm ci && npm run build
const fs = require('fs');
const esbuild = require('esbuild');
const stylePlugin = require('esbuild-style-plugin');
const { environmentPlugin } = require('esbuild-plugin-environment');

esbuild.build({
    entryPoints: [require.resolve('./entry.js')],
    outfile: process.argv[2],
    format: 'iife',
    globalName: 'Plotly',
    bundle: true,
    minify: true,
    sourcemap: false,
    plugins: [stylePlugin(), environmentPlugin({ NODE_DEBUG: false })],
    alias: { stream: 'stream-browserify' },
    define: { global: 'window', 'define.amd': 'false' },
    target: 'es2016',
    logLevel: 'warning',
    banner: { js: '/*! plotly.js v3.0.1 (MIT) | partial bundle for Tradeski: core + scatter, bar, candlestick, heatmap */' },
}).then(() => {
    // The style plugin also writes MapLibre's stylesheet (core imports it for map
    // subplots). The dashboard draws no maps, and Plotly injects its own styles
    // from JS, so the .css output is dropped.
    fs.rmSync(process.argv[2].replace(/\.js$/, '.css'), { force: true });
    console.log('built', process.argv[2]);
})
  .catch((e) => { console.error(e.message); process.exit(1); });
