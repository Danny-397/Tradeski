// dashboard.js — Tradeski Real-Time Fintech Dashboard

// ============================================================
// CONFIG
// ============================================================

const CFG = {
    API: "https://tradeski.onrender.com",
    WS:  "https://tradeski.onrender.com",
    WATCHLIST_REFRESH_MS: 30_000,
    TICKER_REFRESH_MS:    60_000,
};

const DEFAULT_WATCHLIST = [
    { symbol: "AAPL",  name: "Apple" },
    { symbol: "MSFT",  name: "Microsoft" },
    { symbol: "NVDA",  name: "NVIDIA" },
    { symbol: "TSLA",  name: "Tesla" },
    { symbol: "AMZN",  name: "Amazon" },
    { symbol: "SOFI",  name: "SoFi Technologies" },
    { symbol: "RDW",   name: "Redwire Corp" },
];

function _loadWatchlist() {
    try {
        const saved = localStorage.getItem("tradeski_watchlist");
        return saved ? JSON.parse(saved) : DEFAULT_WATCHLIST;
    } catch { return DEFAULT_WATCHLIST; }
}

function _saveWatchlist() {
    localStorage.setItem("tradeski_watchlist", JSON.stringify(WATCHLIST));
}

let WATCHLIST = _loadWatchlist();

const TICKER_EXTRA = ["GOOGL", "META", "SPY", "QQQ"];
function getTickerSyms() {
    const wl = WATCHLIST.map(w => w.symbol);
    return [...new Set([...wl, ...TICKER_EXTRA])];
}

// ============================================================
// STATE
// ============================================================

let state = {
    symbol:     "AAPL",
    timeframe:  "1M",
    chartType:  "line",
    showRsi:    false,
    showMacd:   false,
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
    initPortfolio();
    loadAllSparklines();
    setInterval(loadAllSparklines, 3_600_000); // refresh sparklines hourly
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
    const input = document.getElementById("symbol-input");
    const btn   = document.getElementById("symbol-go-btn");

    function go() {
        const sym = input.value.trim().toUpperCase();
        if (sym) { input.value = ""; switchSymbol(sym); }
    }

    input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    btn.addEventListener("click", go);

    document.getElementById("add-symbol-btn").addEventListener("click", async () => {
        const sym = prompt("Enter ticker symbol to add to watchlist:")?.trim().toUpperCase();
        if (sym) await addToWatchlist(sym);
    });
}

function switchSymbol(sym) {
    state.symbol = sym;
    document.getElementById("current-symbol-badge").textContent = sym;
    document.querySelectorAll(".watchlist-item").forEach(el => {
        el.classList.toggle("active", el.dataset.symbol === sym);
    });
    loadDashboard(sym);
}

async function addToWatchlist(sym) {
    if (!sym || WATCHLIST.some(w => w.symbol === sym)) return;
    try {
        const res = await fetch(`${CFG.API}/stats?symbol=${sym}`);
        if (!res.ok) { alert(`"${sym}" not found — check the ticker and try again.`); return; }
    } catch { alert("Could not reach backend — check your connection."); return; }
    WATCHLIST.push({ symbol: sym, name: sym });
    _saveWatchlist();
    renderWatchlist();
    refreshWatchlistPrices();
    loadAllSparklines();
}

function removeFromWatchlist(sym) {
    WATCHLIST = WATCHLIST.filter(w => w.symbol !== sym);
    _saveWatchlist();
    renderWatchlist();
    if (state.symbol === sym) switchSymbol(WATCHLIST[0]?.symbol || "AAPL");
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

// ============================================================
// INDICATOR TOGGLES
// ============================================================

function initIndicatorToggles() {
    // Overlay toggles (BB, SMA, EMA, VOL)
    document.querySelectorAll(".ind-btn[data-ind]").forEach(btn => {
        btn.addEventListener("click", () => {
            const k = btn.dataset.ind;
            state.indicators[k] = !state.indicators[k];
            btn.classList.toggle("active", state.indicators[k]);
            if (state.chartData) renderChart(state.chartData);
        });
    });

    // Chart type toggle (LINE / CANDLE)
    document.querySelectorAll("#chart-type-group [data-type]").forEach(btn => {
        btn.addEventListener("click", () => {
            state.chartType = btn.dataset.type;
            document.querySelectorAll("#chart-type-group [data-type]").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            if (state.chartData) renderChart(state.chartData);
        });
    });

    // Subpanel toggles (RSI / MACD)
    document.querySelectorAll("[data-panel]").forEach(btn => {
        btn.addEventListener("click", () => {
            const p = btn.dataset.panel;
            if (p === "rsi") {
                state.showRsi = !state.showRsi;
                btn.textContent = (state.showRsi ? "− RSI" : "+ RSI");
                btn.classList.toggle("active", state.showRsi);
            } else if (p === "macd") {
                state.showMacd = !state.showMacd;
                btn.textContent = (state.showMacd ? "− MACD" : "+ MACD");
                btn.classList.toggle("active", state.showMacd);
            }
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

    // Non-blocking — news loads independently after core data
    loadNews(sym);
}

// ============================================================
// CHART
// ============================================================

async function loadChart(sym) {
    const res = await fetch(`${CFG.API}/price_history?symbol=${sym}&tf=${state.timeframe}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.chartData = await res.json();
    renderChart(state.chartData);
    showChartLoading(false);
}

function renderChart(d) {
    const traces = [];
    const ts = d.timestamps;
    const showRsi  = state.showRsi;
    const showMacd = state.showMacd;

    // ── Main price trace ─────────────────────────────────────
    if (state.chartType === "candle") {
        traces.push({
            type: "candlestick",
            x: ts, open: d.open, high: d.high, low: d.low, close: d.close,
            name: state.symbol,
            increasing: { line: { color: "#16A34A", width: 1 }, fillcolor: "rgba(22,163,74,0.18)" },
            decreasing: { line: { color: "#DC2626", width: 1 }, fillcolor: "rgba(220,38,38,0.18)" },
            xaxis: "x", yaxis: "y",
            whiskerwidth: 0.3,
        });
    } else {
        traces.push({
            type: "scatter", mode: "lines",
            x: ts, y: d.close,
            name: state.symbol,
            line: { color: "#3B82F6", width: 2 },
            fill: "tozeroy",
            fillcolor: "rgba(59,130,246,0.05)",
            xaxis: "x", yaxis: "y",
        });
    }

    // Volume
    if (state.indicators.vol && d.volume) {
        const cols = d.close.map((c, i) =>
            c == null ? "rgba(90,90,90,0.35)"
            : (d.open[i] == null || c >= d.open[i]) ? "rgba(22,163,74,0.4)" : "rgba(220,38,38,0.4)"
        );
        traces.push({
            type: "bar", x: ts, y: d.volume,
            name: "Volume", marker: { color: cols },
            xaxis: "x", yaxis: "y2", opacity: 0.75,
        });
    }

    // SMA
    if (state.indicators.sma) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.sma20, name: "SMA20",
            line: { color: "#60A5FA", width: 1.5 }, xaxis: "x", yaxis: "y" });
        if (d.sma50) {
            traces.push({ type: "scatter", mode: "lines", x: ts, y: d.sma50, name: "SMA50",
                line: { color: "#A78BFA", width: 1.5, dash: "dot" }, xaxis: "x", yaxis: "y" });
        }
    }

    // EMA
    if (state.indicators.ema) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.ema20, name: "EMA20",
            line: { color: "#FB923C", width: 1.5 }, xaxis: "x", yaxis: "y" });
    }

    // Bollinger Bands
    if (state.indicators.bb) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.upper_band, name: "BB Upper",
            line: { color: "rgba(139,92,246,0.5)", width: 1 },
            xaxis: "x", yaxis: "y", showlegend: true });
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.lower_band, name: "BB Lower",
            line: { color: "rgba(139,92,246,0.5)", width: 1 },
            fill: "tonexty", fillcolor: "rgba(109,40,217,0.05)",
            xaxis: "x", yaxis: "y", showlegend: false });
    }

    // RSI subpanel (toggled)
    if (showRsi) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.rsi, name: "RSI",
            line: { color: "#F472B6", width: 1.5 }, xaxis: "x2", yaxis: "y3" });
        const rsiRef = (y) => ({
            type: "scatter", mode: "lines",
            x: [ts[0], ts[ts.length - 1]], y: [y, y],
            line: { color: y === 70 ? "rgba(220,38,38,0.3)" : "rgba(22,163,74,0.3)", width: 1, dash: "dash" },
            xaxis: "x2", yaxis: "y3", showlegend: false,
        });
        traces.push(rsiRef(70));
        traces.push(rsiRef(30));
    }

    // MACD subpanel (toggled)
    if (showMacd) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.macd, name: "MACD",
            line: { color: "#38BDF8", width: 1.5 }, xaxis: "x3", yaxis: "y4" });
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.signal, name: "Signal",
            line: { color: "#FB923C", width: 1.5 }, xaxis: "x3", yaxis: "y4" });
        const histCols = (d.histogram || []).map(v =>
            v == null ? "rgba(80,80,80,0.35)" : (v >= 0 ? "rgba(22,163,74,0.55)" : "rgba(220,38,38,0.55)"));
        traces.push({ type: "bar", x: ts, y: d.histogram, name: "Histogram",
            marker: { color: histCols }, xaxis: "x3", yaxis: "y4", opacity: 0.9 });
    }

    // ── Layout domains ────────────────────────────────────────
    let mainDom, rsiDom, macdDom;
    const shapes = [];

    if (!showRsi && !showMacd) {
        mainDom = [0, 1];
    } else if (showRsi && !showMacd) {
        mainDom = [0.34, 1.0];
        rsiDom  = [0.0,  0.31];
        shapes.push({ type: "line", x0: 0, x1: 1, xref: "paper", y0: 0.33, y1: 0.33, yref: "paper",
            line: { color: "rgba(255,255,255,0.07)", width: 1 } });
    } else if (!showRsi && showMacd) {
        mainDom = [0.34, 1.0];
        macdDom = [0.0,  0.31];
        shapes.push({ type: "line", x0: 0, x1: 1, xref: "paper", y0: 0.33, y1: 0.33, yref: "paper",
            line: { color: "rgba(255,255,255,0.07)", width: 1 } });
    } else {
        mainDom = [0.44, 1.0];
        rsiDom  = [0.24, 0.41];
        macdDom = [0.0,  0.21];
        shapes.push(
            { type: "line", x0: 0, x1: 1, xref: "paper", y0: 0.43, y1: 0.43, yref: "paper",
                line: { color: "rgba(255,255,255,0.07)", width: 1 } },
            { type: "line", x0: 0, x1: 1, xref: "paper", y0: 0.23, y1: 0.23, yref: "paper",
                line: { color: "rgba(255,255,255,0.07)", width: 1 } }
        );
    }

    const ax = {
        gridcolor:     "rgba(255,255,255,0.04)",
        linecolor:     "rgba(255,255,255,0.07)",
        zerolinecolor: "rgba(255,255,255,0.06)",
        tickfont: { family: "JetBrains Mono, monospace", size: 10, color: "#6B7280" },
        showgrid: true, zeroline: false, showline: false,
    };

    const layout = {
        paper_bgcolor: "#07090D",
        plot_bgcolor:  "#07090D",
        font: { color: "#D1D5DB", family: "Space Grotesk, sans-serif", size: 11 },
        showlegend: true,
        legend: {
            x: 0.01, y: 0.99,
            xanchor: "left", yanchor: "top",
            orientation: "h",
            font: { size: 10, family: "JetBrains Mono, monospace", color: "#6B7280" },
            bgcolor: "transparent",
        },
        margin: { t: 8, l: 10, r: 65, b: 8 },
        xaxis:  { ...ax, domain: [0, 1], anchor: "y", type: "date", rangeslider: { visible: false } },
        yaxis:  { ...ax, domain: mainDom, side: "right", title: { text: "Price", font: { size: 9 } } },
        yaxis2: { ...ax, overlaying: "y", side: "left", showgrid: false, visible: false },
        dragmode: "pan",
        hovermode: "x unified",
        hoverlabel: {
            bgcolor: "#0C0F16",
            bordercolor: "rgba(59,130,246,0.3)",
            font: { family: "JetBrains Mono, monospace", size: 11, color: "#D1D5DB" },
            namelength: -1,
        },
        shapes,
    };

    if (showRsi) {
        layout.xaxis2 = { ...ax, domain: [0, 1], anchor: "y3", matches: "x",
            type: "date", showticklabels: !showMacd };
        layout.yaxis3 = { ...ax, domain: rsiDom, side: "right", range: [0, 100],
            title: { text: "RSI", font: { size: 9 } } };
    }
    if (showMacd) {
        layout.xaxis3 = { ...ax, domain: [0, 1], anchor: "y4", matches: "x",
            type: "date", showticklabels: false };
        layout.yaxis4 = { ...ax, domain: macdDom, side: "right",
            title: { text: "MACD", font: { size: 9 } } };
    }

    const config = {
        responsive: true, displaylogo: false,
        scrollZoom: true, displayModeBar: true,
        modeBarButtonsToRemove: ["select2d", "lasso2d", "toImage"],
    };

    if (!document.getElementById("price-chart")) return;
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
    el.innerHTML = "";

    for (const { symbol, name } of WATCHLIST) {
        const item = document.createElement("div");
        item.className   = `watchlist-item ${symbol === state.symbol ? "active" : ""}`;
        item.dataset.symbol = symbol;
        item.addEventListener("click", () => switchSymbol(symbol));

        item.innerHTML = `
            <div class="wl-top">
                <div class="wl-left">
                    <span class="wl-symbol">${symbol}</span>
                    <span class="wl-name">${name}</span>
                </div>
                <div class="wl-right">
                    <span class="wl-price neutral" id="wlp-${symbol}">——</span>
                    <span class="wl-change"        id="wlc-${symbol}">——</span>
                    <button class="wl-remove-btn" title="Remove">×</button>
                </div>
            </div>
        `;
        item.querySelector(".wl-remove-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            removeFromWatchlist(symbol);
        });

        // Sparkline canvas — Chart.js will render into this
        const canvas = document.createElement("canvas");
        canvas.className = "wl-sparkline";
        canvas.id = `spark-${symbol}`;
        item.appendChild(canvas);

        el.appendChild(item);
    }
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

    for (const sym of getTickerSyms()) {
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

// ============================================================
// WATCHLIST SPARKLINES (Chart.js)
// ============================================================

const _sparklineCharts = new Map(); // symbol → Chart.js instance

async function loadAllSparklines() {
    await Promise.allSettled(WATCHLIST.map(({ symbol }) => loadSparkline(symbol)));
}

async function loadSparkline(symbol) {
    try {
        const res = await fetch(`${CFG.API}/sparkline?symbol=${symbol}`);
        if (!res.ok) return;
        const data = await res.json();

        const closes = data.close || [];
        if (closes.length < 2) return;

        const canvas = document.getElementById(`spark-${symbol}`);
        if (!canvas) return;

        // Destroy any existing Chart.js instance on this canvas
        const existing = _sparklineCharts.get(symbol);
        if (existing) existing.destroy();

        const isUp    = closes[closes.length - 1] >= closes[0];
        const color   = isUp ? "#00e87a" : "#ff2d55";
        const fill    = isUp ? "rgba(0,232,122,0.07)" : "rgba(255,45,85,0.07)";

        const chart = new Chart(canvas, {
            type: "line",
            data: {
                labels:   closes.map((_, i) => i),
                datasets: [{
                    data:            closes,
                    borderColor:     color,
                    borderWidth:     1.5,
                    fill:            true,
                    backgroundColor: fill,
                    pointRadius:     0,
                    tension:         0.35,
                }],
            },
            options: {
                responsive:          true,
                maintainAspectRatio: false,
                animation:           false,
                plugins: {
                    legend:  { display: false },
                    tooltip: { enabled: false },
                },
                scales: {
                    x: { display: false },
                    y: { display: false },
                },
            },
        });

        _sparklineCharts.set(symbol, chart);
    } catch (_) { /* non-fatal — sparkline failure shouldn't affect anything */ }
}

// ============================================================
// PORTFOLIO
// ============================================================

function initPortfolio() {
    document.getElementById("pf-add-btn").addEventListener("click", submitHolding);
    document.getElementById("pf-symbol").addEventListener("keydown", (e) => {
        if (e.key === "Enter") submitHolding();
    });
    document.getElementById("pf-avgcost").addEventListener("keydown", (e) => {
        if (e.key === "Enter") submitHolding();
    });
    loadPortfolio();
    setInterval(loadPortfolio, CFG.WATCHLIST_REFRESH_MS);
}

async function loadPortfolio() {
    try {
        const res  = await fetch(`${CFG.API}/portfolio`);
        const data = await res.json();
        renderPortfolio(data);
    } catch {
        // silently ignore if backend not up
    }
}

function renderPortfolio(data) {
    const list  = document.getElementById("portfolio-list");
    const badge = document.getElementById("portfolio-total-badge");

    const holdings = data.holdings || [];
    const total    = data.total_value || 0;
    const pnl      = data.total_pnl_pct;

    // Update header badge
    if (total > 0) {
        const pnlStr = pnl != null
            ? ` (${pnl >= 0 ? "+" : ""}${pnl.toFixed(1)}%)`
            : "";
        badge.textContent = `$${total.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}${pnlStr}`;
        badge.style.color = pnl == null ? "" : pnl >= 0 ? "var(--green)" : "var(--red)";
    } else {
        badge.textContent = "—";
        badge.style.color = "";
    }

    if (holdings.length === 0) {
        list.innerHTML = '<div class="feed-empty">No holdings — add one below</div>';
        return;
    }

    list.innerHTML = "";
    for (const h of holdings) {
        const item = document.createElement("div");
        item.className = "portfolio-item";

        // Row 1: symbol + delete
        const row1 = document.createElement("div");
        row1.className = "pf-row1";

        const sym = document.createElement("span");
        sym.className = "pf-symbol";
        sym.textContent = h.symbol;

        const del = document.createElement("button");
        del.className = "pf-delete-btn";
        del.textContent = "✕";
        del.title = `Remove ${h.symbol}`;
        del.addEventListener("click", () => deleteHolding(h.id, h.symbol));

        row1.appendChild(sym);
        row1.appendChild(del);

        // Row 2: shares · value · P&L
        const row2 = document.createElement("div");
        row2.className = "pf-row2";

        const shares = document.createElement("span");
        shares.className = "pf-shares";
        shares.textContent = `${h.shares} sh`;

        row2.appendChild(shares);

        if (h.current_price != null) {
            const val = document.createElement("span");
            val.className = "pf-value";
            val.textContent = h.market_value != null
                ? `$${h.market_value.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
                : `@ $${h.current_price.toFixed(2)}`;
            row2.appendChild(val);

            if (h.pnl_pct != null) {
                const pnlEl = document.createElement("span");
                pnlEl.className = `pf-pnl ${h.pnl_pct >= 0 ? "up" : "down"}`;
                pnlEl.textContent = `${h.pnl_pct >= 0 ? "+" : ""}${h.pnl_pct.toFixed(1)}%`;
                row2.appendChild(pnlEl);
            }
        } else {
            const noPrice = document.createElement("span");
            noPrice.className = "pf-no-price";
            noPrice.textContent = "price pending";
            row2.appendChild(noPrice);
        }

        item.appendChild(row1);
        item.appendChild(row2);
        list.appendChild(item);
    }
}

async function submitHolding() {
    const symEl  = document.getElementById("pf-symbol");
    const shEl   = document.getElementById("pf-shares");
    const costEl = document.getElementById("pf-avgcost");

    const symbol   = symEl.value.trim().toUpperCase();
    const shares   = parseFloat(shEl.value);
    const avg_cost = costEl.value.trim() ? parseFloat(costEl.value) : null;

    if (!symbol || isNaN(shares) || shares <= 0) return;

    const btn = document.getElementById("pf-add-btn");
    btn.disabled = true;
    btn.textContent = "...";

    try {
        const res = await fetch(`${CFG.API}/portfolio`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol, shares, avg_cost }),
        });
        if (res.ok) {
            symEl.value  = "";
            shEl.value   = "";
            costEl.value = "";
            await loadPortfolio();
        }
    } finally {
        btn.disabled = false;
        btn.textContent = "+ ADD";
    }
}

async function deleteHolding(id, symbol) {
    if (!confirm(`Remove ${symbol} from portfolio?`)) return;
    await fetch(`${CFG.API}/portfolio/${id}`, { method: "DELETE" });
    await loadPortfolio();
}

// ============================================================
// SKI CHATBOT
// ============================================================

const skiState = {
    open: false,
    history: [],   // [{role, content}]
    busy: false,
};

function initSki() {
    const fab    = document.getElementById("ski-fab");
    const panel  = document.getElementById("ski-panel");
    const close  = document.getElementById("ski-close-btn");
    const input  = document.getElementById("ski-input");
    const send   = document.getElementById("ski-send-btn");

    panel.classList.add("hidden");

    fab.addEventListener("click", () => skiToggle());
    close.addEventListener("click", () => skiToggle(false));

    send.addEventListener("click", skiSend);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); skiSend(); }
    });
}

function skiToggle(forceOpen) {
    const panel = document.getElementById("ski-panel");
    const badge = document.getElementById("ski-badge");
    skiState.open = forceOpen !== undefined ? forceOpen : !skiState.open;
    if (skiState.open) {
        panel.classList.remove("hidden");
        badge.style.display = "none";
        document.getElementById("ski-input").focus();
    } else {
        panel.classList.add("hidden");
    }
}

function skiAppendMessage(role, content, isLoading = false) {
    const container = document.getElementById("ski-messages");
    const wrap = document.createElement("div");
    wrap.className = `ski-message ski-message-${role}`;
    const bubble = document.createElement("div");
    bubble.className = "ski-bubble" + (isLoading ? " loading" : "");
    bubble.textContent = content;
    wrap.appendChild(bubble);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
    return bubble;
}

async function skiSend() {
    if (skiState.busy) return;
    const input = document.getElementById("ski-input");
    const send  = document.getElementById("ski-send-btn");
    const message = input.value.trim();
    if (!message) return;

    input.value = "";
    skiState.busy = true;
    send.disabled = true;

    skiAppendMessage("user", message);
    skiState.history.push({ role: "user", content: message });

    const loadingBubble = skiAppendMessage("assistant", "Thinking...", true);

    try {
        const res = await fetch(`${CFG.API}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message, history: skiState.history.slice(0, -1), symbol: state.symbol }),
        });
        const data = await res.json();
        const reply = data.reply || data.error || "No response.";
        loadingBubble.textContent = reply;
        loadingBubble.classList.remove("loading");
        skiState.history.push({ role: "assistant", content: reply });
        // Trim history to last 20 turns to avoid unbounded growth
        if (skiState.history.length > 20) skiState.history = skiState.history.slice(-20);
    } catch {
        loadingBubble.textContent = "Backend is starting up — Render free tier spins down after inactivity. Wait ~30 seconds and try again.";
        loadingBubble.classList.remove("loading");
        skiState.history.pop();
    } finally {
        skiState.busy = false;
        send.disabled = false;
        document.getElementById("ski-input").focus();
    }
}

document.addEventListener("DOMContentLoaded", () => { initSki(); });

// ============================================================
// MACRO RIBBON (FRED data)
// ============================================================

const MACRO_LABELS = {
    CPIAUCSL:     { short: "CPI",      tip: "Consumer Price Index YoY %" },
    FEDFUNDS:     { short: "FED RATE", tip: "Effective Federal Funds Rate" },
    GDP:          { short: "GDP",      tip: "Real GDP (Chained 2017 $B)" },
    UNRATE:       { short: "UNEMP",    tip: "Unemployment Rate" },
    DGS10:        { short: "10Y",      tip: "10-Year Treasury Yield" },
    T10Y2Y:       { short: "CURVE",    tip: "Yield Curve (10Y−2Y Spread)" },
    BAMLH0A0HYM2: { short: "HY SPD",  tip: "High Yield OAS Credit Spread" },
};

async function loadMacroRibbon() {
    const inner = document.getElementById("macro-inner");
    if (!inner) return;

    try {
        const res = await fetch(`${CFG.API}/macro`);
        if (!res.ok) {
            inner.innerHTML = '<div class="macro-item"><span class="macro-error">FRED data unavailable — set FRED_API_KEY</span></div>';
            return;
        }
        const data = await res.json();
        if (data.error) {
            inner.innerHTML = `<div class="macro-item"><span class="macro-error">${data.error}</span></div>`;
            return;
        }

        inner.innerHTML = "";
        for (const [sid, info] of Object.entries(data)) {
            const meta   = MACRO_LABELS[sid] || { short: info.label, tip: info.description };
            const item   = document.createElement("div");
            item.className = "macro-item";
            item.title   = `${meta.tip} — as of ${info.date || "?"}`;

            const arrowMap = { up: " ▲", down: " ▼", neutral: "" };
            const cls      = info.trend === "up" ? "up" : info.trend === "down" ? "down" : "neutral";
            const val      = info.value != null ? `${info.value}${info.unit}` : "—";
            const arrow    = arrowMap[info.trend] || "";

            item.innerHTML = `
                <span class="macro-label">${meta.short}</span>
                <span class="macro-value ${cls}">${val}${arrow}</span>
                <span class="macro-date">${info.date || ""}</span>
            `;
            inner.appendChild(item);
        }
    } catch {
        inner.innerHTML = '<div class="macro-item"><span class="macro-error">Macro data unavailable</span></div>';
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadMacroRibbon();
    setInterval(loadMacroRibbon, 3_600_000); // refresh every hour
    initScreener();
});

// ============================================================
// NEWS FEED + SENTIMENT
// ============================================================

function escapeHtml(s) {
    return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function timeAgo(isoStr) {
    if (!isoStr) return "";
    const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
    if (diff < 60)   return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

async function loadNews(sym) {
    const feed   = document.getElementById("news-feed");
    const chip   = document.getElementById("agg-sentiment-chip");
    if (!feed) return;

    feed.innerHTML = '<div class="feed-empty">Loading news…</div>';

    try {
        const res  = await fetch(`${CFG.API}/news?symbol=${encodeURIComponent(sym)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const articles = data.articles || [];
        const agg      = data.aggregate || {};

        // Update aggregate chip
        if (chip) {
            const label = agg.label || "neutral";
            const sign  = (agg.score || 0) >= 0 ? "+" : "";
            chip.textContent  = `${label.toUpperCase()} ${sign}${(agg.score || 0).toFixed(2)}`;
            chip.className    = `sentiment-chip ${label}`;
        }

        if (!articles.length) {
            feed.innerHTML = '<div class="feed-empty">No news available</div>';
            return;
        }

        feed.innerHTML = "";
        for (const a of articles) {
            const lbl   = a.sentiment_label || "neutral";
            const score = typeof a.sentiment === "number" ? (a.sentiment >= 0 ? "+" : "") + a.sentiment.toFixed(2) : "";
            const item  = document.createElement("div");
            item.className = "news-item";
            item.innerHTML = `
                <div class="news-item-header">
                    <span class="news-sentiment ${lbl}">${lbl.toUpperCase()} ${score}</span>
                </div>
                <a class="news-title" href="${escapeHtml(a.url || "#")}" target="_blank" rel="noopener">
                    ${escapeHtml(a.title || "")}
                </a>
                <div class="news-meta">
                    <span class="news-source">${escapeHtml(a.source || "")}</span>
                    <span class="news-time">${timeAgo(a.published_at)}</span>
                </div>
            `;
            feed.appendChild(item);
        }
    } catch {
        feed.innerHTML = '<div class="feed-empty">News unavailable</div>';
        if (chip) { chip.textContent = "—"; chip.className = "sentiment-chip"; }
    }
}

// ============================================================
// STOCK SCREENER
// ============================================================

const screenerState = {
    data:    [],
    filtered: [],
    sortCol: "symbol",
    sortDir: 1,        // 1 = asc, -1 = desc
    loaded:  false,
};

function initScreener() {
    document.getElementById("open-screener-btn").addEventListener("click", openScreener);
    document.getElementById("close-screener-btn").addEventListener("click", closeScreener);
    document.getElementById("reset-filters-btn").addEventListener("click", resetScreenerFilters);

    document.getElementById("screener-modal").addEventListener("click", e => {
        if (e.target.id === "screener-modal") closeScreener();
    });

    document.querySelectorAll(".screener-table th.sortable").forEach(th => {
        th.addEventListener("click", () => sortScreener(th.dataset.col));
    });

    ["pe-min", "pe-max", "perf-min", "perf-max"].forEach(id => {
        document.getElementById(id).addEventListener("input", applyScreenerFilters);
    });
    ["mcap-filter", "sector-filter"].forEach(id => {
        document.getElementById(id).addEventListener("change", applyScreenerFilters);
    });
}

function openScreener() {
    document.getElementById("screener-modal").style.display = "flex";
    if (!screenerState.loaded) loadScreener();
}

function closeScreener() {
    document.getElementById("screener-modal").style.display = "none";
}

async function loadScreener() {
    const tbody = document.getElementById("screener-tbody");
    tbody.innerHTML = `<tr><td colspan="9" class="screener-loading">
        <div class="loading-spinner"></div> Fetching screening data…</td></tr>`;

    try {
        const res = await fetch(`${CFG.API}/screener`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        screenerState.data   = data.stocks || [];
        screenerState.loaded = true;

        // Populate sector select dynamically from returned data
        const sectorSel = document.getElementById("sector-filter");
        const sectors = [...new Set(
            screenerState.data.map(s => s.sector).filter(s => s && s !== "—")
        )].sort();
        sectors.forEach(s => {
            const opt = document.createElement("option");
            opt.value = s;
            opt.textContent = s;
            sectorSel.appendChild(opt);
        });

        applyScreenerFilters();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="9" class="feed-empty">
            Failed to load screener — ${e.message}</td></tr>`;
    }
}

function applyScreenerFilters() {
    const peMinEl   = document.getElementById("pe-min");
    const peMaxEl   = document.getElementById("pe-max");
    const perfMinEl = document.getElementById("perf-min");
    const perfMaxEl = document.getElementById("perf-max");

    const peMin   = peMinEl.value   !== "" ? parseFloat(peMinEl.value)   : null;
    const peMax   = peMaxEl.value   !== "" ? parseFloat(peMaxEl.value)   : null;
    const perfMin = perfMinEl.value !== "" ? parseFloat(perfMinEl.value) : null;
    const perfMax = perfMaxEl.value !== "" ? parseFloat(perfMaxEl.value) : null;
    const mcap    = document.getElementById("mcap-filter").value;
    const sector  = document.getElementById("sector-filter").value;

    screenerState.filtered = screenerState.data.filter(s => {
        if (peMin   !== null && (s.pe      === null || s.pe      < peMin))   return false;
        if (peMax   !== null && (s.pe      === null || s.pe      > peMax))   return false;
        if (perfMin !== null && (s.perf_52w === null || s.perf_52w < perfMin)) return false;
        if (perfMax !== null && (s.perf_52w === null || s.perf_52w > perfMax)) return false;
        if (sector && s.sector !== sector) return false;
        if (mcap) {
            const mc = s.market_cap;
            if (mc === null) return false;
            if (mcap === "mega"  && mc <  200e9)              return false;
            if (mcap === "large" && (mc < 10e9 || mc >= 200e9)) return false;
            if (mcap === "mid"   && (mc <  2e9 || mc >=  10e9)) return false;
            if (mcap === "small" && mc >=  2e9)               return false;
        }
        return true;
    });

    sortScreenerData();
    renderScreenerTable();
}

function sortScreener(col) {
    if (screenerState.sortCol === col) {
        screenerState.sortDir *= -1;
    } else {
        screenerState.sortCol = col;
        // Default string columns ascending, numeric columns descending
        screenerState.sortDir = (col === "symbol" || col === "name" || col === "sector") ? 1 : -1;
    }

    document.querySelectorAll(".screener-table th.sortable").forEach(th => {
        const icon = th.querySelector(".sort-icon");
        const active = th.dataset.col === screenerState.sortCol;
        icon.textContent = active ? (screenerState.sortDir === 1 ? "↑" : "↓") : "↕";
        th.classList.toggle("sorted", active);
    });

    sortScreenerData();
    renderScreenerTable();
}

function sortScreenerData() {
    const { sortCol: col, sortDir: dir } = screenerState;
    screenerState.filtered.sort((a, b) => {
        const av = a[col], bv = b[col];
        if (av === null || av === undefined || av === "—") return 1;
        if (bv === null || bv === undefined || bv === "—") return -1;
        if (typeof av === "string") return dir * av.localeCompare(bv);
        return dir * (av - bv);
    });
}

function fmtMcap(mc) {
    if (mc === null || mc === undefined) return "—";
    if (mc >= 1e12) return `$${(mc / 1e12).toFixed(2)}T`;
    if (mc >= 1e9)  return `$${(mc / 1e9).toFixed(1)}B`;
    if (mc >= 1e6)  return `$${(mc / 1e6).toFixed(0)}M`;
    return `$${mc.toLocaleString()}`;
}

function renderScreenerTable() {
    const tbody = document.getElementById("screener-tbody");
    const count = document.getElementById("screener-count");
    const rows  = screenerState.filtered;

    count.textContent = `${rows.length} result${rows.length !== 1 ? "s" : ""}`;

    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="9" class="feed-empty">No stocks match the current filters</td></tr>`;
        return;
    }

    tbody.innerHTML = "";
    for (const s of rows) {
        const perf    = s.perf_52w;
        const perfCls = perf === null ? "" : perf >= 0 ? "positive" : "negative";
        const perfStr = perf === null ? "—" : `${perf >= 0 ? "+" : ""}${perf.toFixed(2)}%`;

        const tr = document.createElement("tr");
        tr.className = "screener-row";
        tr.innerHTML = `
            <td class="sc-symbol">${escapeHtml(s.symbol)}</td>
            <td class="sc-name">${escapeHtml(s.name || "")}</td>
            <td class="sc-price">${s.price !== null ? "$" + s.price.toFixed(2) : "—"}</td>
            <td class="sc-pe">${s.pe !== null ? s.pe.toFixed(1) : "—"}</td>
            <td class="sc-mcap">${fmtMcap(s.market_cap)}</td>
            <td class="sc-sector">${escapeHtml(s.sector || "—")}</td>
            <td class="sc-high">${s.high_52w !== null ? "$" + s.high_52w.toFixed(2) : "—"}</td>
            <td class="sc-low">${s.low_52w  !== null ? "$" + s.low_52w.toFixed(2)  : "—"}</td>
            <td class="sc-perf ${perfCls}">${perfStr}</td>
        `;

        tr.querySelector(".sc-symbol").addEventListener("click", () => {
            closeScreener();
            switchSymbol(s.symbol);
        });

        tbody.appendChild(tr);
    }
}

function resetScreenerFilters() {
    ["pe-min", "pe-max", "perf-min", "perf-max"].forEach(id => {
        document.getElementById(id).value = "";
    });
    document.getElementById("mcap-filter").value = "";
    document.getElementById("sector-filter").value = "";
    applyScreenerFilters();
}
