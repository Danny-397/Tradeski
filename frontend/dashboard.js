// dashboard.js — Tradeski Real-Time Fintech Dashboard

// ============================================================
// CONFIG
// ============================================================

const CFG = {
    API: "http://localhost:5000",
    WS:  "http://localhost:5000",
    WATCHLIST_REFRESH_MS: 30_000,
    TICKER_REFRESH_MS:    60_000,
};

const WATCHLIST = [
    { symbol: "AAPL",  name: "Apple" },
    { symbol: "MSFT",  name: "Microsoft" },
    { symbol: "NVDA",  name: "NVIDIA" },
    { symbol: "TSLA",  name: "Tesla" },
    { symbol: "AMZN",  name: "Amazon" },
];

const TICKER_SYMS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ"];

// ============================================================
// STATE
// ============================================================

let state = {
    symbol:     "AAPL",
    timeframe:  "1M",
    indicators: { bb: true, sma: true, ema: true, vol: true },
    chartData:  null,
    alerts:     [],
    lastPrices: {},
    socket:     null,
};

// ============================================================
// BOOT
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
    startClock();
    updateMarketStatus();
    setInterval(updateMarketStatus, 60_000);
    initWebSocket();
    initSymbolSelect();
    initTimeframes();
    initIndicatorToggles();
    initAlertModal();
    document.getElementById("clear-feed-btn").addEventListener("click", clearFeed);
    renderWatchlist();
    loadDashboard(state.symbol);
    loadAlerts();
    refreshWatchlistPrices();
    setInterval(refreshWatchlistPrices, CFG.WATCHLIST_REFRESH_MS);
    buildTickerTape();
    setInterval(buildTickerTape, CFG.TICKER_REFRESH_MS);
});

// ============================================================
// CLOCK
// ============================================================

function startClock() {
    const el = document.getElementById("live-clock");
    const tick = () => { el.textContent = new Date().toLocaleTimeString("en-US", { hour12: false }); };
    tick();
    setInterval(tick, 1000);
}

// ============================================================
// MARKET STATUS
// ============================================================

function updateMarketStatus() {
    const dot   = document.getElementById("status-dot");
    const label = document.getElementById("status-label");
    const now   = new Date();
    const day   = now.getDay();
    const h     = now.getHours() + now.getMinutes() / 60;

    if (day === 0 || day === 6) {
        dot.className = "status-dot closed";
        label.textContent = "WEEKEND";
        return;
    }
    if (h >= 9.5 && h < 16) {
        dot.className = "status-dot open";
        label.textContent = "MARKET OPEN";
    } else if ((h >= 4 && h < 9.5) || (h >= 16 && h < 20)) {
        dot.className = "status-dot pre";
        label.textContent = "EXTENDED HRS";
    } else {
        dot.className = "status-dot closed";
        label.textContent = "MARKET CLOSED";
    }
}

// ============================================================
// WEBSOCKET
// ============================================================

function initWebSocket() {
    try {
        state.socket = io(CFG.WS, { transports: ["websocket", "polling"], reconnection: true });
        state.socket.on("connect",    () => setWs(true));
        state.socket.on("disconnect", () => setWs(false));
        state.socket.on("price_update",    onPriceUpdate);
        state.socket.on("alert_triggered", onAlertTriggered);
    } catch (_) {
        setWs(false);
    }
}

function setWs(connected) {
    const dot   = document.getElementById("ws-dot");
    const label = document.querySelector(".ws-label");
    dot.className   = connected ? "ws-dot on" : "ws-dot";
    label.textContent = connected ? "LIVE" : "OFFLINE";
}

function onPriceUpdate(msg) {
    const pct = msg.change_pct ?? null;
    updateWatchlistPrice(msg.symbol, msg.price, pct);
    if (msg.symbol === state.symbol) {
        renderHeaderPrice(msg.symbol, msg.price, pct);
        setLastUpdate();
    }
}

function onAlertTriggered(alert) {
    pushFeed(`${alert.symbol}: ${alert.message}`, "alert");
}

// ============================================================
// SYMBOL SELECT
// ============================================================

function initSymbolSelect() {
    document.getElementById("symbol-select").addEventListener("change", (e) => {
        switchSymbol(e.target.value);
    });
}

function switchSymbol(sym) {
    state.symbol = sym;
    document.getElementById("symbol-select").value = sym;
    document.getElementById("current-symbol-badge").textContent = sym;
    document.querySelectorAll(".watchlist-item").forEach(el => {
        el.classList.toggle("active", el.dataset.symbol === sym);
    });
    loadDashboard(sym);
}

// ============================================================
// TIMEFRAMES
// ============================================================

function initTimeframes() {
    document.querySelectorAll(".tf-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            state.timeframe = btn.dataset.tf;
            loadChart(state.symbol);
        });
    });
}

function tfToLimit(tf) {
    return { "1D": 78, "5D": 390, "1M": 300, "3M": 900, "6M": 1800, "1Y": 3600 }[tf] ?? 300;
}

// ============================================================
// INDICATOR TOGGLES
// ============================================================

function initIndicatorToggles() {
    document.querySelectorAll(".ind-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const k = btn.dataset.ind;
            state.indicators[k] = !state.indicators[k];
            btn.classList.toggle("active", state.indicators[k]);
            if (state.chartData) renderChart(state.chartData);
        });
    });
}

// ============================================================
// MAIN DASHBOARD LOAD
// ============================================================

async function loadDashboard(sym) {
    setStatus(`Loading ${sym}…`);
    document.getElementById("current-symbol-badge").textContent = sym;
    showChartLoading(true);
    renderHeaderPrice(sym, null, null);

    try {
        await Promise.all([loadChart(sym), loadStats(sym)]);
        setStatus(`${sym} — data loaded`);
    } catch (e) {
        setStatus(`Error: ${e.message}`);
        showChartLoading(false);
    }
}

// ============================================================
// CHART
// ============================================================

async function loadChart(sym) {
    const limit = tfToLimit(state.timeframe);
    const res   = await fetch(`${CFG.API}/price_history?symbol=${sym}&limit=${limit}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.chartData = await res.json();
    renderChart(state.chartData);
    showChartLoading(false);
}

function renderChart(d) {
    const traces = [];
    const ts = d.timestamps;

    // Candlestick
    traces.push({
        type: "candlestick",
        x: ts,
        open: d.open, high: d.high, low: d.low, close: d.close,
        name: state.symbol,
        increasing: { line: { color: "#00e87a", width: 1 }, fillcolor: "rgba(0,232,122,0.15)" },
        decreasing: { line: { color: "#ff2d55", width: 1 }, fillcolor: "rgba(255,45,85,0.15)" },
        xaxis: "x", yaxis: "y",
        whiskerwidth: 0.3,
    });

    // Volume
    if (state.indicators.vol && d.volume) {
        const cols = d.close.map((c, i) =>
            c == null ? "rgba(90,90,90,0.4)"
            : (d.open[i] == null || c >= d.open[i])
                ? "rgba(0,232,122,0.45)"
                : "rgba(255,45,85,0.45)"
        );
        traces.push({
            type: "bar", x: ts, y: d.volume,
            name: "Volume", marker: { color: cols },
            xaxis: "x", yaxis: "y2", opacity: 0.8,
        });
    }

    // SMA
    if (state.indicators.sma) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.sma20, name: "SMA20",
            line: { color: "#2196f3", width: 1.5 }, xaxis: "x", yaxis: "y" });
        if (d.sma50) {
            traces.push({ type: "scatter", mode: "lines", x: ts, y: d.sma50, name: "SMA50",
                line: { color: "#9c27b0", width: 1.5, dash: "dot" }, xaxis: "x", yaxis: "y" });
        }
    }

    // EMA
    if (state.indicators.ema) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.ema20, name: "EMA20",
            line: { color: "#ff9800", width: 1.5 }, xaxis: "x", yaxis: "y" });
    }

    // Bollinger Bands — fill between
    if (state.indicators.bb) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.upper_band, name: "BB Upper",
            line: { color: "rgba(120,90,220,0.55)", width: 1 },
            xaxis: "x", yaxis: "y", showlegend: true });
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.lower_band, name: "BB Lower",
            line: { color: "rgba(120,90,220,0.55)", width: 1 },
            fill: "tonexty", fillcolor: "rgba(90,60,180,0.06)",
            xaxis: "x", yaxis: "y", showlegend: false });
    }

    // RSI
    traces.push({ type: "scatter", mode: "lines", x: ts, y: d.rsi, name: "RSI",
        line: { color: "#e91e63", width: 1.5 }, xaxis: "x2", yaxis: "y3" });

    const rsiEdge = (y) => ({
        type: "scatter", mode: "lines",
        x: [ts[0], ts[ts.length - 1]], y: [y, y],
        line: { color: y === 70 ? "rgba(255,45,85,0.3)" : "rgba(0,232,122,0.3)", width: 1, dash: "dash" },
        xaxis: "x2", yaxis: "y3", showlegend: false,
    });
    traces.push(rsiEdge(70));
    traces.push(rsiEdge(30));

    // MACD
    traces.push({ type: "scatter", mode: "lines", x: ts, y: d.macd, name: "MACD",
        line: { color: "#03a9f4", width: 1.5 }, xaxis: "x3", yaxis: "y4" });
    traces.push({ type: "scatter", mode: "lines", x: ts, y: d.signal, name: "Signal",
        line: { color: "#ff5722", width: 1.5 }, xaxis: "x3", yaxis: "y4" });

    const histCols = (d.histogram || []).map(v => v == null ? "rgba(80,80,80,0.4)" : (v >= 0 ? "rgba(0,232,122,0.55)" : "rgba(255,45,85,0.55)"));
    traces.push({ type: "bar", x: ts, y: d.histogram, name: "Histogram",
        marker: { color: histCols }, xaxis: "x3", yaxis: "y4", opacity: 0.9 });

    const ax = {
        gridcolor:   "rgba(255,255,255,0.04)",
        linecolor:   "rgba(255,255,255,0.07)",
        zerolinecolor: "rgba(255,255,255,0.08)",
        tickfont: { family: "JetBrains Mono, monospace", size: 10, color: "#5e7e9a" },
        showgrid: true, zeroline: false, showline: false,
    };

    const layout = {
        paper_bgcolor: "#07090f",
        plot_bgcolor:  "#07090f",
        font: { color: "#d8eaf5", family: "Inter, sans-serif", size: 11 },
        showlegend: true,
        legend: {
            x: 0.01, y: 0.99,
            xanchor: "left", yanchor: "top",
            orientation: "h",
            font: { size: 10, family: "JetBrains Mono, monospace", color: "#5e7e9a" },
            bgcolor: "transparent",
        },
        margin: { t: 8, l: 10, r: 65, b: 8 },

        xaxis:  { ...ax, domain: [0, 1], anchor: "y",  type: "date", rangeslider: { visible: false } },
        yaxis:  { ...ax, domain: [0.44, 1.0], side: "right", title: { text: "Price", font: { size: 9 } } },
        yaxis2: { ...ax, overlaying: "y", side: "left", showgrid: false, visible: false },

        xaxis2:  { ...ax, domain: [0, 1], anchor: "y3", showticklabels: false },
        yaxis3:  { ...ax, domain: [0.24, 0.41], side: "right", range: [0, 100], title: { text: "RSI", font: { size: 9 } } },

        xaxis3:  { ...ax, domain: [0, 1], anchor: "y4", showticklabels: false },
        yaxis4:  { ...ax, domain: [0.0, 0.21], side: "right", title: { text: "MACD", font: { size: 9 } } },

        dragmode: "pan",
        hovermode: "x unified",
        hoverlabel: {
            bgcolor: "#0c1120",
            bordercolor: "rgba(0,212,255,0.3)",
            font: { family: "JetBrains Mono, monospace", size: 11, color: "#d8eaf5" },
            namelength: -1,
        },
        shapes: [
            { type: "line", x0: 0, x1: 1, xref: "paper", y0: 0.43, y1: 0.43, yref: "paper",
              line: { color: "rgba(255,255,255,0.07)", width: 1 } },
            { type: "line", x0: 0, x1: 1, xref: "paper", y0: 0.23, y1: 0.23, yref: "paper",
              line: { color: "rgba(255,255,255,0.07)", width: 1 } },
        ],
    };

    const config = {
        responsive:  true,
        displaylogo: false,
        scrollZoom:  true,
        displayModeBar: true,
        modeBarButtonsToRemove: ["select2d", "lasso2d", "toImage"],
    };

    const container = document.getElementById("price-chart");
    if (!container) return;

    Plotly.react("price-chart", traces, layout, config);
    updateIndicatorsPanel(d);
}

function showChartLoading(on) {
    const el = document.getElementById("chart-loading");
    if (el) el.classList.toggle("hidden", !on);
}

// ============================================================
// STATS
// ============================================================

async function loadStats(sym) {
    const res = await fetch(`${CFG.API}/stats?symbol=${sym}`);
    if (!res.ok) return;
    const d = await res.json();

    const pct   = d.open > 0 ? ((d.close - d.open) / d.open * 100) : 0;
    const dir   = pct >= 0 ? "up" : "down";
    const arrow = pct >= 0 ? "▲" : "▼";

    renderHeaderPrice(sym, d.close, pct);

    const range52 = d.high_52w > d.low_52w
        ? ((d.close - d.low_52w) / (d.high_52w - d.low_52w) * 100).toFixed(1)
        : 50;

    document.getElementById("stats-content").innerHTML = `
        <div class="stat-cell">
            <span class="stat-label">Open</span>
            <span class="stat-value">$${fmt(d.open)}</span>
        </div>
        <div class="stat-cell">
            <span class="stat-label">Close</span>
            <span class="stat-value ${dir}">$${fmt(d.close)}</span>
        </div>
        <div class="stat-cell">
            <span class="stat-label">High</span>
            <span class="stat-value up">$${fmt(d.high)}</span>
        </div>
        <div class="stat-cell">
            <span class="stat-label">Low</span>
            <span class="stat-value down">$${fmt(d.low)}</span>
        </div>
        <div class="stat-cell">
            <span class="stat-label">Change</span>
            <span class="stat-value ${dir}">${arrow} ${Math.abs(pct).toFixed(2)}%</span>
        </div>
        <div class="stat-cell">
            <span class="stat-label">Day Range</span>
            <span class="stat-value">$${fmt(d.high - d.low)}</span>
        </div>
        <div class="range-cell">
            <div class="range-label">52-WEEK RANGE</div>
            <div class="range-track">
                <div class="range-fill"></div>
                <div class="range-cursor" style="left:${range52}%"></div>
            </div>
            <div class="range-extremes">
                <span>$${fmt(d.low_52w)}</span>
                <span>$${fmt(d.high_52w)}</span>
            </div>
        </div>
    `;
}

// ============================================================
// INDICATORS PANEL
// ============================================================

function updateIndicatorsPanel(d) {
    const last = arr => {
        if (!arr) return null;
        for (let i = arr.length - 1; i >= 0; i--)
            if (arr[i] != null) return arr[i];
        return null;
    };

    const rsiVal    = last(d.rsi);
    const macdVal   = last(d.macd);
    const sigVal    = last(d.signal);
    const histVal   = last(d.histogram);
    const upper     = last(d.upper_band);
    const lower     = last(d.lower_band);
    const closeVal  = last(d.close);
    const zVal      = last(d.zscore);
    const sma20     = last(d.sma20);
    const sma50     = last(d.sma50);
    const ema20     = last(d.ema20);

    // RSI signal
    let rsiSig = "neutral", rsiLabel = "NEUTRAL";
    if (rsiVal != null) {
        if (rsiVal > 70) { rsiSig = "sell"; rsiLabel = "OVERBOUGHT"; }
        else if (rsiVal < 30) { rsiSig = "buy"; rsiLabel = "OVERSOLD"; }
    }
    const rsiPct     = rsiVal != null ? Math.min(100, Math.max(0, rsiVal)) : 0;
    const rsiClass   = rsiVal > 70 ? "overbought" : rsiVal < 30 ? "oversold" : "neutral";

    // MACD signal
    let macdSig = "neutral", macdLabel = "FLAT";
    if (macdVal != null && sigVal != null) {
        macdSig   = macdVal > sigVal ? "buy" : "sell";
        macdLabel = macdVal > sigVal ? "BULLISH" : "BEARISH";
    }

    // BB signal
    let bbSig = "neutral", bbLabel = "MID BAND";
    if (closeVal && upper && lower) {
        const span = upper - lower;
        const pct  = span > 0 ? (closeVal - lower) / span : 0.5;
        if (pct > 0.85) { bbSig = "sell"; bbLabel = "NEAR UPPER"; }
        else if (pct < 0.15) { bbSig = "buy"; bbLabel = "NEAR LOWER"; }
    }

    // Z-Score signal
    let zSig = "neutral", zLabel = "NORMAL";
    if (zVal != null) {
        if (zVal > 2) { zSig = "sell"; zLabel = "HIGH"; }
        else if (zVal < -2) { zSig = "buy"; zLabel = "LOW"; }
    }

    // SMA trend
    const smaColor = (val) => closeVal && val ? (closeVal > val ? "var(--green)" : "var(--red)") : "var(--text-muted)";
    const smaArrow = (val) => closeVal && val ? (closeVal > val ? "▲ Above" : "▼ Below") : "—";

    document.getElementById("indicators-panel").innerHTML = `
        <div class="ind-card">
            <div class="ind-row">
                <span class="ind-name">RSI (14)</span>
                <span class="signal-chip ${rsiSig}">${rsiLabel}</span>
            </div>
            <div class="ind-row">
                <span class="ind-val">${rsiVal != null ? rsiVal.toFixed(1) : "—"}</span>
                <span class="ind-sub">&nbsp;</span>
            </div>
            <div class="gauge-track">
                <div class="gauge-marks">
                    <div class="gauge-mark" style="left:30%"></div>
                    <div class="gauge-mark" style="left:70%"></div>
                </div>
                <div class="gauge-fill ${rsiClass}" style="width:${rsiPct}%"></div>
            </div>
        </div>

        <div class="ind-card">
            <div class="ind-row">
                <span class="ind-name">MACD</span>
                <span class="signal-chip ${macdSig}">${macdLabel}</span>
            </div>
            <div class="ind-row">
                <span class="ind-val">${macdVal != null ? macdVal.toFixed(3) : "—"}</span>
                <span class="ind-sub">SIG ${sigVal != null ? sigVal.toFixed(3) : "—"}</span>
            </div>
        </div>

        <div class="ind-card">
            <div class="ind-row">
                <span class="ind-name">Bollinger Bands</span>
                <span class="signal-chip ${bbSig}">${bbLabel}</span>
            </div>
            <div class="ind-row">
                <span class="ind-sub">U: ${upper ? "$" + fmt(upper) : "—"}</span>
                <span class="ind-sub">L: ${lower ? "$" + fmt(lower) : "—"}</span>
            </div>
        </div>

        <div class="ind-card">
            <div class="ind-row">
                <span class="ind-name">Z-Score (20)</span>
                <span class="signal-chip ${zSig}">${zLabel}</span>
            </div>
            <div class="ind-val">${zVal != null ? zVal.toFixed(2) : "—"}</div>
        </div>

        <div class="ind-card">
            <div class="ind-row">
                <span class="ind-name">SMA 20</span>
                <span style="font-size:10px;color:${smaColor(sma20)}">${smaArrow(sma20)}</span>
            </div>
            <div class="ind-val">${sma20 ? "$" + fmt(sma20) : "—"}</div>
        </div>

        ${sma50 ? `
        <div class="ind-card">
            <div class="ind-row">
                <span class="ind-name">SMA 50</span>
                <span style="font-size:10px;color:${smaColor(sma50)}">${smaArrow(sma50)}</span>
            </div>
            <div class="ind-val">$${fmt(sma50)}</div>
        </div>` : ""}

        <div class="ind-card">
            <div class="ind-row">
                <span class="ind-name">EMA 20</span>
                <span style="font-size:10px;color:${smaColor(ema20)}">${smaArrow(ema20)}</span>
            </div>
            <div class="ind-val">${ema20 ? "$" + fmt(ema20) : "—"}</div>
        </div>
    `;
}

// ============================================================
// WATCHLIST
// ============================================================

function renderWatchlist() {
    const el = document.getElementById("watchlist");
    el.innerHTML = WATCHLIST.map(({ symbol, name }) => `
        <div class="watchlist-item ${symbol === state.symbol ? "active" : ""}"
             data-symbol="${symbol}"
             onclick="switchSymbol('${symbol}')">
            <div class="wl-left">
                <span class="wl-symbol">${symbol}</span>
                <span class="wl-name">${name}</span>
            </div>
            <div class="wl-right">
                <span class="wl-price neutral" id="wlp-${symbol}">——</span>
                <span class="wl-change"        id="wlc-${symbol}">——</span>
            </div>
        </div>
    `).join("");
}

async function refreshWatchlistPrices() {
    for (const { symbol } of WATCHLIST) {
        try {
            const res = await fetch(`${CFG.API}/stats?symbol=${symbol}`);
            if (!res.ok) continue;
            const d   = await res.json();
            const pct = d.open > 0 ? ((d.close - d.open) / d.open * 100) : 0;
            updateWatchlistPrice(symbol, d.close, pct);
        } catch (_) {}
    }
}

function updateWatchlistPrice(symbol, price, pct) {
    const pEl = document.getElementById(`wlp-${symbol}`);
    const cEl = document.getElementById(`wlc-${symbol}`);
    if (!pEl || price == null) return;

    const prev = state.lastPrices[symbol];
    const dir  = prev != null ? (price > prev ? "up" : price < prev ? "down" : "neutral") : "neutral";
    state.lastPrices[symbol] = price;

    pEl.textContent = `$${fmt(price)}`;
    pEl.className   = `wl-price ${dir}`;

    if (pct != null) {
        const sign = pct >= 0 ? "+" : "";
        cEl.textContent = `${sign}${pct.toFixed(2)}%`;
        cEl.className   = `wl-change ${pct >= 0 ? "up" : "down"}`;
    }

    if (dir !== "neutral") {
        pEl.classList.add(`flash-${dir}`);
        setTimeout(() => pEl.classList.remove(`flash-${dir}`), 950);
    }
}

// ============================================================
// TICKER TAPE
// ============================================================

async function buildTickerTape() {
    const tape    = document.getElementById("ticker-tape");
    const results = [];

    for (const sym of TICKER_SYMS) {
        try {
            const res = await fetch(`${CFG.API}/stats?symbol=${sym}`);
            if (!res.ok) continue;
            const d   = await res.json();
            const pct = d.open > 0 ? ((d.close - d.open) / d.open * 100) : 0;
            results.push({ symbol: sym, price: d.close, pct });
        } catch (_) {}
    }

    if (!results.length) return;

    // Duplicate for seamless loop
    const html = [...results, ...results].map(({ symbol, price, pct }) => {
        const dir   = pct >= 0 ? "up" : "down";
        const sign  = pct >= 0 ? "+" : "";
        const arrow = pct >= 0 ? "▲" : "▼";
        return `<span class="ticker-item">
            <span class="ticker-symbol">${symbol}</span>
            <span class="ticker-price">$${fmt(price)}</span>
            <span class="ticker-change ${dir}">${arrow}${sign}${pct.toFixed(2)}%</span>
        </span>`;
    }).join("");

    tape.innerHTML = html;
    // Reset animation
    tape.style.animation = "none";
    void tape.offsetWidth;
    tape.style.animation = "";
}

// ============================================================
// HEADER PRICE
// ============================================================

function renderHeaderPrice(symbol, price, pct) {
    const el = document.getElementById("header-price-display");
    if (price == null) {
        el.innerHTML = `<div class="header-price-item skeleton">
            <span class="hp-symbol">${symbol}</span>
            <div class="loading-spinner"></div>
        </div>`;
        return;
    }
    const dir   = pct >= 0 ? "up" : "down";
    const sign  = pct >= 0 ? "+" : "";
    const arrow = pct >= 0 ? "▲" : "▼";
    el.innerHTML = `<div class="header-price-item">
        <span class="hp-symbol">${symbol}</span>
        <span class="hp-price ${dir}">$${fmt(price)}</span>
        <span class="hp-change ${dir}">${arrow} ${sign}${pct != null ? pct.toFixed(2) : "0.00"}%</span>
    </div>`;
}

// ============================================================
// ALERTS
// ============================================================

async function loadAlerts() {
    try {
        const res = await fetch(`${CFG.API}/alerts`);
        if (!res.ok) return;
        state.alerts = await res.json();
        renderAlertList();
    } catch (_) {}
}

function renderAlertList() {
    const el    = document.getElementById("active-alerts-list");
    const badge = document.getElementById("alert-count");
    badge.textContent = state.alerts.length;

    if (!state.alerts.length) {
        el.innerHTML = `<div class="feed-empty">No alerts set</div>`;
        return;
    }

    el.innerHTML = state.alerts.map(([id, sym, type, thresh]) => `
        <div class="alert-row">
            <div class="alert-row-left">
                <span class="alert-sym-type">${sym} · ${fmtAlertType(type)}</span>
                ${thresh != null ? `<span class="alert-thresh">@ $${fmt(thresh)}</span>` : ""}
            </div>
            <button class="del-btn" onclick="deleteAlert(${id})" title="Delete alert">✕</button>
        </div>
    `).join("");
}

async function deleteAlert(id) {
    try {
        await fetch(`${CFG.API}/alerts/${id}`, { method: "DELETE" });
        await loadAlerts();
        pushFeed(`Alert #${id} removed`, "");
    } catch (_) {}
}

function fmtAlertType(t) {
    return {
        price_above: "Price ↑", price_below: "Price ↓",
        rsi_overbought: "RSI >70", rsi_oversold: "RSI <30",
        volume_spike: "Vol Spike", volatility_spike: "Volatility",
    }[t] ?? t;
}

// ============================================================
// ALERT MODAL
// ============================================================

function initAlertModal() {
    document.getElementById("create-alert-btn").addEventListener("click", () => {
        document.getElementById("alert-modal").style.display = "flex";
    });
    document.getElementById("close-modal-btn").addEventListener("click", () => {
        document.getElementById("alert-modal").style.display = "none";
    });
    document.getElementById("alert-modal").addEventListener("click", e => {
        if (e.target === document.getElementById("alert-modal"))
            document.getElementById("alert-modal").style.display = "none";
    });
    document.getElementById("alert-type").addEventListener("change", e => {
        const needs = ["price_above", "price_below"].includes(e.target.value);
        document.getElementById("threshold-group").style.display = needs ? "flex" : "none";
    });
    document.getElementById("submit-alert-btn").addEventListener("click", submitAlert);
}

async function submitAlert() {
    const symbol    = document.getElementById("alert-symbol").value;
    const alertType = document.getElementById("alert-type").value;
    const threshold = parseFloat(document.getElementById("alert-threshold").value) || null;

    try {
        await fetch(`${CFG.API}/alerts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol, alert_type: alertType, threshold }),
        });
        document.getElementById("alert-modal").style.display = "none";
        document.getElementById("alert-threshold").value = "";
        await loadAlerts();
        pushFeed(`Alert created: ${symbol} ${fmtAlertType(alertType)}`, "buy");
    } catch (_) {
        setStatus("Failed to create alert");
    }
}

// ============================================================
// SIGNAL FEED
// ============================================================

function pushFeed(message, type = "") {
    const feed  = document.getElementById("alerts-feed");
    const empty = feed.querySelector(".feed-empty");
    if (empty) empty.remove();

    const now = new Date().toLocaleTimeString("en-US", { hour12: false });
    const el  = document.createElement("div");
    el.className = `feed-item ${type}`;
    el.innerHTML = `${message}<time class="feed-time">${now}</time>`;
    feed.prepend(el);

    const items = feed.querySelectorAll(".feed-item");
    if (items.length > 60) items[items.length - 1].remove();
}

function clearFeed() {
    document.getElementById("alerts-feed").innerHTML =
        `<div class="feed-empty">Feed cleared — monitoring active</div>`;
}

// ============================================================
// STATUS BAR
// ============================================================

function setStatus(msg) {
    const el = document.getElementById("status-msg");
    if (el) el.textContent = msg;
}

function setLastUpdate() {
    const el = document.getElementById("last-update");
    if (el) el.textContent = `Updated ${new Date().toLocaleTimeString("en-US", { hour12: false })}`;
}

// ============================================================
// UTILS
// ============================================================

function fmt(n) {
    if (n == null || isNaN(n)) return "—";
    return parseFloat(n).toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
}
