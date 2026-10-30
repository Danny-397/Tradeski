// dashboard.js — Tradeski Real-Time Fintech Dashboard

// ============================================================
// CONFIG
// ============================================================

const CFG = {
    API: "https://tradeski.onrender.com",
    WS:  "https://tradeski.onrender.com",
    TICKER_REFRESH_MS: 60_000,
    PORTFOLIO_REFRESH_MS: 30_000,
};

const TICKER_SYMS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SOFI", "RDW", "GOOGL", "META", "SPY", "QQQ"];

// ============================================================
// STATE
// ============================================================

// Touch device? (phones/tablets) — drives the cleaner, gesture-friendly
// chart behaviour and a less cluttered set of default overlays.
const IS_TOUCH = !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);

let state = {
    symbol:     "AAPL",
    timeframe:  "1D",
    chartType:  "candle",
    showRsi:    false,
    showMacd:   false,
    // All chart overlays on by default (every device) so the indicators are
    // visible right away; users can toggle any of them off.
    indicators: { bb: true, sma: true, ema: true, vol: true },
    chartData:  null,
    alerts:     [],
    lastPrices: {},
    socket:     null,
};

// ============================================================
// AUTH
// ============================================================

const AUTH_KEY = "tradeski_token";
const authState = { user: null, mode: "login" };

function getToken() { return localStorage.getItem(AUTH_KEY) || ""; }

function setSession(token, user) {
    localStorage.setItem(AUTH_KEY, token);
    authState.user = user;
    updateAuthUI();
}

function clearSession() {
    localStorage.removeItem(AUTH_KEY);
    authState.user = null;
    updateAuthUI();
}

// Inject the bearer token on same-API requests from one place, so every
// existing fetch call is authenticated without being individually modified.
const _origFetch = window.fetch.bind(window);
window.fetch = function (input, init) {
    try {
        const url = typeof input === "string" ? input : (input && input.url) || "";
        const token = getToken();
        if (token && url.startsWith(CFG.API)) {
            init = init ? { ...init } : {};
            const headers = new Headers(init.headers || {});
            if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
            init.headers = headers;
        }
    } catch (_) { /* fall through to a normal request */ }
    return _origFetch(input, init);
};

function initAuth() {
    document.getElementById("signin-btn").addEventListener("click", () => openAuthModal("login"));
    document.getElementById("logout-btn").addEventListener("click", logout);
    document.getElementById("close-auth-btn").addEventListener("click", closeAuthModal);
    document.getElementById("auth-modal").addEventListener("click", (e) => {
        if (e.target === document.getElementById("auth-modal")) closeAuthModal();
    });
    document.getElementById("auth-toggle-btn").addEventListener("click", () =>
        setAuthMode(authState.mode === "login" ? "register" : "login"));
    document.getElementById("auth-submit-btn").addEventListener("click", submitAuth);
    ["auth-email-input", "auth-password-input"].forEach((id) => {
        document.getElementById(id).addEventListener("keydown", (e) => {
            if (e.key === "Enter") submitAuth();
        });
    });
    validateSession();
}

function openAuthModal(mode) {
    setAuthMode(mode || "login");
    clearAuthError();
    document.getElementById("auth-modal").style.display = "flex";
    document.getElementById("auth-email-input").focus();
}

function closeAuthModal() {
    document.getElementById("auth-modal").style.display = "none";
}

function setAuthMode(mode) {
    authState.mode = mode;
    const isLogin = mode === "login";
    document.getElementById("auth-title").textContent = isLogin ? "Sign in" : "Create account";
    document.getElementById("auth-submit-btn").textContent = isLogin ? "Sign in" : "Create account";
    document.getElementById("auth-intro").textContent = isLogin
        ? "Sign in to save your portfolio, alerts, and watchlist across devices."
        : "Create a free account to save your portfolio, alerts, and watchlist.";
    document.getElementById("auth-toggle-text").textContent = isLogin ? "New to Tradeski?" : "Already have an account?";
    document.getElementById("auth-toggle-btn").textContent = isLogin ? "Create an account" : "Sign in";
    document.getElementById("auth-password-input").setAttribute("autocomplete", isLogin ? "current-password" : "new-password");
    clearAuthError();
}

function showAuthError(msg) {
    const el = document.getElementById("auth-error");
    el.textContent = msg;
    el.style.display = "";
}

function clearAuthError() {
    const el = document.getElementById("auth-error");
    el.textContent = "";
    el.style.display = "none";
}

async function submitAuth() {
    const email = document.getElementById("auth-email-input").value.trim();
    const password = document.getElementById("auth-password-input").value;
    if (!email || !password) { showAuthError("Enter your email and password."); return; }

    const btn = document.getElementById("auth-submit-btn");
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "...";
    clearAuthError();

    try {
        const endpoint = authState.mode === "login" ? "login" : "register";
        const res = await fetch(`${CFG.API}/auth/${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            showAuthError(data.error || "Something went wrong — please try again.");
            return;
        }
        setSession(data.token, data.user);
        closeAuthModal();
        document.getElementById("auth-password-input").value = "";
        onSignedIn();
    } catch (_) {
        showAuthError("Network error — the backend may be waking up. Try again in a moment.");
    } finally {
        btn.disabled = false;
        btn.textContent = original;
    }
}

async function validateSession() {
    if (!getToken()) { updateAuthUI(); onSignedOut(); return; }
    try {
        const res = await fetch(`${CFG.API}/auth/me`);
        if (res.ok) {
            const data = await res.json();
            authState.user = data.user;
            updateAuthUI();
            onSignedIn();
        } else {
            clearSession();
            onSignedOut();
        }
    } catch (_) {
        // Backend asleep/unreachable — keep the token and show optimistic UI.
        updateAuthUI();
    }
}

function logout() {
    clearSession();
    onSignedOut();
}

function updateAuthUI() {
    const signinBtn = document.getElementById("signin-btn");
    const userBox = document.getElementById("auth-user");
    const emailEl = document.getElementById("auth-email");
    if (!signinBtn || !userBox) return;
    if (authState.user) {
        signinBtn.style.display = "none";
        userBox.style.display = "";
        emailEl.textContent = authState.user.email;
    } else {
        signinBtn.style.display = "";
        userBox.style.display = "none";
        emailEl.textContent = "";
    }
}

function onSignedIn() {
    loadPortfolio();
    loadAlerts();
}

function onSignedOut() {
    renderSignedOutPortfolio();
    renderSignedOutAlerts();
}

// A signed-out visitor can try the portfolio features on this example
// instead of creating an account first. It is priced live from /stats, is
// never saved, and is sent to Ski so its answers are about these holdings.
const SAMPLE_PORTFOLIO = [
    { symbol: "AAPL", shares: 12,  avg_cost: 185 },
    { symbol: "NVDA", shares: 30,  avg_cost: 95 },
    { symbol: "MSFT", shares: 6,   avg_cost: 410 },
    { symbol: "SPY",  shares: 10,  avg_cost: 560 },
    { symbol: "SOFI", shares: 150, avg_cost: 9.5 },
];
let sampleActive = false;

async function loadSamplePortfolio() {
    sampleActive = true;
    const priced = await Promise.all(SAMPLE_PORTFOLIO.map(async (h) => {
        let price = null;
        try {
            const res = await fetch(`${CFG.API}/stats?symbol=${h.symbol}`);
            if (res.ok) price = (await res.json()).close ?? null;
        } catch { /* leave this row unpriced */ }
        return {
            ...h,
            current_price: price,
            market_value: price != null ? +(price * h.shares).toFixed(2) : null,
            pnl_pct: price != null ? +((price - h.avg_cost) / h.avg_cost * 100).toFixed(2) : null,
        };
    }));
    if (getToken() || !sampleActive) return;   // signed in or closed the sample meanwhile
    const valued = priced.filter(h => h.market_value != null);
    const total = valued.reduce((a, h) => a + h.market_value, 0);
    const cost = valued.reduce((a, h) => a + h.shares * h.avg_cost, 0);
    renderPortfolio({
        holdings: priced,
        total_value: total,
        total_pnl_pct: cost ? +((total - cost) / cost * 100).toFixed(2) : null,
    }, true);
}

function renderSignedOutPortfolio() {
    sampleActive = false;
    const list = document.getElementById("portfolio-list");
    const badge = document.getElementById("portfolio-total-badge");
    const footer = document.getElementById("pf-footer");
    const risk = document.getElementById("pf-risk");
    if (badge) { badge.textContent = "—"; badge.style.color = ""; }
    if (risk) risk.style.display = "none";
    if (footer) footer.style.display = "none";
    if (list) {
        list.innerHTML =
            '<div class="feed-empty signed-out-prompt">Sign in to track your portfolio & P&amp;L'
            + '<button class="btn-secondary signed-out-cta" onclick="openAuthModal(\'login\')">Sign in</button>'
            + '<button class="text-btn sample-cta" onclick="loadSamplePortfolio()">Try a sample portfolio</button></div>';
    }
    showSkiStarters(false);
}

function renderSignedOutAlerts() {
    const list = document.getElementById("active-alerts-list");
    const badge = document.getElementById("alert-count");
    const footer = document.getElementById("alert-footer");
    if (badge) badge.textContent = "0";
    if (footer) footer.style.display = "none";
    if (list) {
        list.innerHTML =
            '<div class="feed-empty signed-out-prompt">Sign in to create price &amp; indicator alerts'
            + '<button class="btn-secondary signed-out-cta" onclick="openAuthModal(\'login\')">Sign in</button></div>';
    }
}

// ============================================================
// BOOT
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
    initAuth();
    updateMarketStatus();
    setInterval(updateMarketStatus, 60_000);
    initWebSocket();
    initSymbolSelect();
    initTimeframes();
    initIndicatorToggles();
    initAlertModal();
    initSidebarTabs();
    loadDashboard(state.symbol);
    buildTickerTape();
    setInterval(() => { if (!pageIdle()) buildTickerTape(); }, CFG.TICKER_REFRESH_MS);
    initPortfolio();
initMobileDrawer();
    initIdleWatch();
});

// ============================================================
// IDLE: stop talking to the server when nobody is looking
// ============================================================

// The backend runs on Render's free tier, which counts every hour it is awake
// against 750 hours a month shared by all five projects; when they run out,
// Render suspends every backend until the month ends (it happened 2026-10-28).
// The open WebSocket and the 30-60 s polls keep it awake for as long as a tab
// is open, even a forgotten background tab, which alone could use ~720 h a
// month. So while the tab is hidden, or nobody has touched it for 15 minutes,
// the page drops the socket and skips its polls, and picks both back up the
// moment the reader returns.
const IDLE_AFTER_MS = 15 * 60_000;
let lastInputAt = Date.now();
let idleAsleep = false;

function isIdle(hidden, lastInput, now) {
    return hidden || now - lastInput >= IDLE_AFTER_MS;
}

function pageIdle() {
    return isIdle(document.hidden, lastInputAt, Date.now());
}

function initIdleWatch() {
    const sleep = () => {
        if (idleAsleep) return;
        idleAsleep = true;
        state.socket?.disconnect();
    };
    const wake = () => {
        lastInputAt = Date.now();
        if (!idleAsleep || document.hidden) return;
        idleAsleep = false;
        state.socket?.connect();
        buildTickerTape();
        loadPortfolio();
    };
    for (const ev of ["pointerdown", "pointermove", "keydown", "wheel", "touchstart", "scroll"]) {
        window.addEventListener(ev, wake, { passive: true });
    }
    // A quick tab switch should not drop the socket, so going hidden is left to
    // the minute check below; coming back reconnects at once.
    document.addEventListener("visibilitychange", () => { if (!document.hidden) wake(); });
    setInterval(() => { if (pageIdle()) sleep(); }, 60_000);
}

// ============================================================
// MARKET STATUS
// ============================================================

function updateMarketStatus() {
    const dot   = document.getElementById("status-dot");
    const label = document.getElementById("status-label");
    const timeEl = document.getElementById("status-time");

    const estStr = new Date().toLocaleString("en-US", { timeZone: "America/New_York",
        hour: "2-digit", minute: "2-digit", hour12: false });
    if (timeEl) timeEl.textContent = `${estStr} EST`;

    const now = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
    const day = now.getDay();
    const h   = now.getHours() + now.getMinutes() / 60;

    if (day === 0 || day === 6) {
        dot.className = "status-dot closed";
        label.textContent = "Weekend · market closed";
        return;
    }
    if (h >= 9.5 && h < 16) {
        dot.className = "status-dot open";
        label.textContent = "Market open";
    } else if ((h >= 4 && h < 9.5) || (h >= 16 && h < 20)) {
        dot.className = "status-dot pre";
        label.textContent = "Extended hours";
    } else {
        dot.className = "status-dot closed";
        label.textContent = "Market closed";
    }
}

// ============================================================
// WEBSOCKET
// ============================================================

function initWebSocket() {
    if (window.TRADESKI_OFFLINE) return;   // crawler: no socket, see demo-mode.js
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
    if (dot)   dot.className    = connected ? "ws-dot on" : "ws-dot";
    if (label) label.textContent = connected ? "Live" : "Offline";
}

function onPriceUpdate(msg) {
    const pct = msg.change_pct ?? null;
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

// Suggestions under a ticker box, searching symbols and company names from
// symbols.js. It only ever rewrites input.value: on Enter its capture-phase
// listener runs before the box's own handler, so "apple" + Enter reaches that
// handler as "AAPL". Any ticker not in the list still goes through as typed.
// Ties go to the names people look up most, so "micro" lists Microsoft first.
const POPULAR_SYMS = new Set([...TICKER_SYMS, "AMD", "NFLX", "JPM", "V", "MA", "BRK-B", "COIN",
    "PLTR", "DIS", "KO", "WMT", "COST", "BA", "INTC", "UBER", "HOOD", "AVGO", "ORCL", "CRM"]);

function searchSymbols(query, limit = 8) {
    const list = window.TRADESKI_SYMBOLS || [];
    const q = query.trim().toUpperCase();
    if (!q) return [];
    const scored = [];
    for (const [sym, name] of list) {
        const n = name.toUpperCase();
        let score = -1;
        if (sym === q) score = 0;
        else if (sym.startsWith(q)) score = 1;
        else if (n.startsWith(q)) score = 2;
        else if (n.includes(" " + q)) score = 3;
        else if (q.length >= 3 && n.includes(q)) score = 4;
        if (score >= 0) scored.push([score, POPULAR_SYMS.has(sym) ? 0 : 1, sym.length, sym, name]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || a[3].localeCompare(b[3]));
    return scored.slice(0, limit).map(([score, , , sym, name]) => ({ score, sym, name }));
}

function attachSymbolSuggest(input, onPick) {
    // Anchor the list to the input itself, whatever row it sits in.
    const wrap = document.createElement("span");
    wrap.className = "suggest-anchor";
    input.parentElement.insertBefore(wrap, input);
    wrap.appendChild(input);
    const box = document.createElement("ul");
    box.className = "symbol-suggest";
    box.id = input.id + "-suggest";
    box.setAttribute("role", "listbox");
    box.hidden = true;
    wrap.appendChild(box);
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", box.id);
    input.setAttribute("aria-expanded", "false");

    let items = [];
    let active = -1;

    function close() {
        box.hidden = true;
        input.setAttribute("aria-expanded", "false");
        input.removeAttribute("aria-activedescendant");
        active = -1;
    }

    function highlight(i) {
        active = i;
        [...box.children].forEach((li, j) => li.classList.toggle("active", j === i));
        if (i >= 0) input.setAttribute("aria-activedescendant", `${box.id}-${i}`);
        else input.removeAttribute("aria-activedescendant");
    }

    function render() {
        items = searchSymbols(input.value);
        if (!items.length) { close(); return; }
        box.innerHTML = items.map((it, i) => `
            <li id="${box.id}-${i}" role="option" data-i="${i}">
                <span class="ss-sym">${it.sym}</span><span class="ss-name">${escapeHtml(it.name)}</span>
            </li>`).join("");
        box.hidden = false;
        input.setAttribute("aria-expanded", "true");
        // Pre-select the top hit when it is an exact symbol, or when the text
        // only matched company names ("apple"). A bare prefix like "AM" is
        // left alone so Enter can still send a ticker that isn't in the list.
        const top = items[0];
        highlight(top.score === 0 || top.score >= 2 ? 0 : -1);
    }

    function choose(i) {
        input.value = items[i].sym;
        close();
    }

    input.addEventListener("input", render);
    input.addEventListener("blur", () => setTimeout(close, 120));
    input.addEventListener("keydown", (e) => {
        if (box.hidden) return;
        if (e.key === "ArrowDown") { e.preventDefault(); highlight((active + 1) % items.length); }
        else if (e.key === "ArrowUp") { e.preventDefault(); highlight(active <= 0 ? items.length - 1 : active - 1); }
        else if (e.key === "Enter" && active >= 0) choose(active);
        else if (e.key === "Escape") { close(); e.stopImmediatePropagation(); }
    }, true);
    // mousedown, not click: it fires before the input's blur closes the list.
    box.addEventListener("mousedown", (e) => {
        const li = e.target.closest("li[data-i]");
        if (!li) return;
        e.preventDefault();
        choose(+li.dataset.i);
        onPick();
    });
}

function initSymbolSelect() {
    const input = document.getElementById("symbol-input");
    const btn   = document.getElementById("symbol-go-btn");

    // The box always shows the symbol on screen (AAPL on first load), so an
    // empty box is never left for the browser's autofill to claim. Focusing
    // selects it, so typing a new ticker replaces it in one motion.
    input.value = state.symbol;

    function go() {
        const sym = input.value.trim().toUpperCase();
        if (!sym) { input.value = state.symbol; return; }
        input.blur();
        if (sym !== state.symbol) switchSymbol(sym);
        else input.value = sym;
    }

    attachSymbolSuggest(input, go);
    input.addEventListener("focus", () => input.select());
    input.addEventListener("blur", () => { if (!input.value.trim()) input.value = state.symbol; });
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") go();
        if (e.key === "Escape") { input.value = state.symbol; input.blur(); }
    });
    btn.addEventListener("click", go);
}

function switchSymbol(sym) {
    state.symbol = sym;
    const symInput = document.getElementById("symbol-input");
    if (symInput && document.activeElement !== symInput) symInput.value = sym;
    const badge = document.getElementById("current-symbol-badge");
    if (badge) badge.textContent = sym;
    loadDashboard(sym);
}

// ============================================================
// TIMEFRAMES
// ============================================================

function initTimeframes() {
    const tfBtns = document.querySelectorAll("#timeframe-group .tf-btn[data-tf]");
    tfBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            tfBtns.forEach(b => b.classList.remove("active"));
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
        // Reflect the actual starting state (overlays default off on mobile).
        btn.classList.toggle("active", !!state.indicators[btn.dataset.ind]);
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
                btn.classList.toggle("active", state.showRsi);
            } else if (p === "macd") {
                state.showMacd = !state.showMacd;
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
    showChartLoading(true);
    renderHeaderPrice(sym, null, null);

    try {
        await Promise.all([loadChart(sym), loadStats(sym)]);
        setStatus(`${sym} — data loaded`);
    } catch (e) {
        setStatus(`Error: ${e.message}`);
        showChartLoading(false);
    }

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
            increasing: { line: { color: "#16A34A", width: 1 }, fillcolor: "rgba(22,163,74,0.25)" },
            decreasing: { line: { color: "#DC2626", width: 1 }, fillcolor: "rgba(220,38,38,0.25)" },
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
            hovertemplate: "<b>$%{y:.2f}</b><extra>" + state.symbol + "</extra>",
        });
    }

    // SMA
    if (state.indicators.sma) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.sma20, name: "SMA20",
            line: { color: "#60A5FA", width: 1.5 }, xaxis: "x", yaxis: "y",
            hovertemplate: "<b>%{y:.2f}</b><extra>SMA20</extra>" });
        if (d.sma50) {
            traces.push({ type: "scatter", mode: "lines", x: ts, y: d.sma50, name: "SMA50",
                line: { color: "#A78BFA", width: 1.5, dash: "dot" }, xaxis: "x", yaxis: "y",
                hovertemplate: "<b>%{y:.2f}</b><extra>SMA50</extra>" });
        }
    }

    // EMA
    if (state.indicators.ema) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.ema20, name: "EMA20",
            line: { color: "#FB923C", width: 1.5 }, xaxis: "x", yaxis: "y",
            hovertemplate: "<b>%{y:.2f}</b><extra>EMA20</extra>" });
    }

    // Bollinger Bands
    if (state.indicators.bb) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.upper_band, name: "BB Upper",
            line: { color: "rgba(148,163,184,0.45)", width: 1 },
            xaxis: "x", yaxis: "y", showlegend: true,
            hovertemplate: "<b>%{y:.2f}</b><extra>BB Upper</extra>" });
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.lower_band, name: "BB Lower",
            line: { color: "rgba(148,163,184,0.45)", width: 1 },
            fill: "tonexty", fillcolor: "rgba(148,163,184,0.06)",
            xaxis: "x", yaxis: "y", showlegend: false,
            hovertemplate: "<b>%{y:.2f}</b><extra>BB Lower</extra>" });
    }

    // RSI subpanel (toggled)
    if (showRsi) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.rsi, name: "RSI",
            line: { color: "#F472B6", width: 1.5 }, xaxis: "x2", yaxis: "y3",
            hovertemplate: "<b>%{y:.1f}</b><extra>RSI</extra>" });
        traces.push({
            type: "scatter", mode: "lines",
            x: [ts[0], ts[ts.length - 1]], y: [70, 70],
            line: { color: "rgba(220,38,38,0.3)", width: 1, dash: "dash" },
            xaxis: "x2", yaxis: "y3", showlegend: false, hoverinfo: "skip",
        });
        traces.push({
            type: "scatter", mode: "lines",
            x: [ts[0], ts[ts.length - 1]], y: [30, 30],
            line: { color: "rgba(22,163,74,0.3)", width: 1, dash: "dash" },
            xaxis: "x2", yaxis: "y3", showlegend: false, hoverinfo: "skip",
        });
    }

    // MACD subpanel (toggled)
    if (showMacd) {
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.macd, name: "MACD",
            line: { color: "#38BDF8", width: 1.5 }, xaxis: "x3", yaxis: "y4",
            hovertemplate: "<b>%{y:.4f}</b><extra>MACD</extra>" });
        traces.push({ type: "scatter", mode: "lines", x: ts, y: d.signal, name: "Signal",
            line: { color: "#FB923C", width: 1.5 }, xaxis: "x3", yaxis: "y4",
            hovertemplate: "<b>%{y:.4f}</b><extra>Signal</extra>" });
        const histCols = (d.histogram || []).map(v =>
            v == null ? "rgba(80,80,80,0.35)" : (v >= 0 ? "rgba(22,163,74,0.55)" : "rgba(220,38,38,0.55)"));
        traces.push({ type: "bar", x: ts, y: d.histogram, name: "Histogram",
            marker: { color: histCols }, xaxis: "x3", yaxis: "y4", opacity: 0.9,
            hovertemplate: "<b>%{y:.4f}</b><extra>Histogram</extra>" });
    }

    // Cursor dot — line mode only, always last trace, updated by hover listener
    if (state.chartType === "line") {
        traces.push({
            type: "scatter", mode: "markers",
            x: [], y: [],
            name: "__cursor__",
            marker: { size: 9, color: "#3B82F6", line: { color: "#ffffff", width: 1.5 } },
            hoverinfo: "skip",
            showlegend: false,
            xaxis: "x", yaxis: "y",
        });
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

    const spike = {
        showspikes: true,
        spikemode: "across",
        spikesnap: "cursor",
        spikecolor: "rgba(148,163,184,0.4)",
        spikedash: "dot",
        spikethickness: 1,
    };

    const ax = {
        gridcolor:     "rgba(255,255,255,0.04)",
        linecolor:     "rgba(255,255,255,0.07)",
        zerolinecolor: "rgba(255,255,255,0.06)",
        tickfont: { family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif", size: 11, color: "#7C838E" },
        showgrid: true, zeroline: false, showline: false,
        // On touch screens lock pan/zoom so a finger-drag reads the value
        // at that point (spikeline + tooltip) instead of dragging the chart.
        fixedrange: IS_TOUCH,
    };

    const layout = {
        paper_bgcolor: "#0A0B0D",
        plot_bgcolor:  "#0A0B0D",
        font: { color: "#DCDFE4", family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif", size: 11 },
        showlegend: true,
        // On touch the chart is small, so float the indicator key ABOVE the
        // plot (y just over the top edge) instead of overlaying the data.
        legend: {
            x: 0,
            y: 1.0,
            xanchor: "left",
            yanchor: "bottom",
            orientation: "h",
            font: { size: 11, family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif", color: "#9BA2AD" },
            bgcolor: "transparent",
        },
        margin: { t: 30, l: 10, r: 60, b: 32 },
        xaxis:  { ...ax, ...spike, domain: [0, 1], anchor: "y", type: "date", rangeslider: { visible: false } },
        yaxis:  { ...ax, ...spike, domain: mainDom, side: "right", title: { text: "" } },
        dragmode: IS_TOUCH ? false : "pan",
        // On touch we scrub by x (finger controls time), so hover by x-column;
        // desktop keeps "closest" for precise mouse hovering.
        hovermode: IS_TOUCH ? "x" : "closest",
        hoverdistance: 80,
        spikedistance: 100,
        hoverlabel: {
            bgcolor: "#1C1E22",
            bordercolor: "rgba(255,255,255,0.14)",
            font: { family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif", size: 12, color: "#F4F5F7" },
            namelength: -1,
        },
        shapes,
    };

    if (showRsi) {
        layout.xaxis2 = { ...ax, ...spike, domain: [0, 1], anchor: "y3", matches: "x",
            type: "date", showticklabels: !showMacd };
        layout.yaxis3 = { ...ax, ...spike, domain: rsiDom, side: "right", range: [0, 100],
            title: { text: "RSI", font: { size: 11, color: "#7C838E" } } };
    }
    if (showMacd) {
        layout.xaxis3 = { ...ax, ...spike, domain: [0, 1], anchor: "y4", matches: "x",
            type: "date", showticklabels: false };
        layout.yaxis4 = { ...ax, ...spike, domain: macdDom, side: "right",
            title: { text: "MACD", font: { size: 11, color: "#7C838E" } } };
    }

    const config = {
        responsive: true, displaylogo: false,
        // Touch: no scroll-zoom, and hide the floating mode bar (clutter on
        // a phone). Desktop keeps the full interactive toolbar.
        scrollZoom: !IS_TOUCH,
        displayModeBar: IS_TOUCH ? false : "hover",
        modeBarButtonsToRemove: ["select2d", "lasso2d", "toImage"],
    };

    if (!document.getElementById("price-chart")) return;
    Plotly.react("price-chart", traces, layout, config);
    watchChartSize();
    initChartHoverListeners();
    updateIndicatorsPanel(d);
}

function initChartHoverListeners() {
    const el = document.getElementById("price-chart");
    if (!el || el._tradeskiHoverInit) return;
    el._tradeskiHoverInit = true;

    // On touch, let a finger-drag "scrub" the chart — Plotly only does
    // tap-to-hover natively, so we drive the hover ourselves.
    if (IS_TOUCH) attachTouchScrub(el);

    el.on("plotly_hover", function(data) {
        if (state.chartType !== "line") return;
        const gd = document.getElementById("price-chart");
        const cursorIdx = (gd.data || []).findIndex(t => t.name === "__cursor__");
        if (cursorIdx < 0) return;
        const pt = data.points.find(p => p.data.name === state.symbol);
        if (!pt) {
            Plotly.restyle("price-chart", { x: [[]], y: [[]] }, [cursorIdx]);
            return;
        }
        Plotly.restyle("price-chart", { x: [[pt.x]], y: [[pt.y]] }, [cursorIdx]);
    });

    el.on("plotly_unhover", function() {
        const gd = document.getElementById("price-chart");
        const cursorIdx = (gd.data || []).findIndex(t => t.name === "__cursor__");
        if (cursorIdx < 0) return;
        Plotly.restyle("price-chart", { x: [[]], y: [[]] }, [cursorIdx]);
    });

    el.on("plotly_click", function(data) {
        if (state.chartType !== "candle") return;
        const pt = data.points.find(p => p.data.type === "candlestick");
        if (!pt) return;

        const idx   = pt.pointIndex;
        const open  = pt.data.open[idx];
        const high  = pt.data.high[idx];
        const low   = pt.data.low[idx];
        const close = pt.data.close[idx];
        const xVal  = pt.x;
        const dateStr = typeof xVal === "string"
            ? xVal.slice(0, 10)
            : new Date(xVal).toISOString().slice(0, 10);

        const pct   = open > 0 ? ((close - open) / open * 100) : 0;
        const dir   = close >= open ? "up" : "down";
        const arrow = close >= open ? "▲" : "▼";
        const range = high - low;

        const strip = document.getElementById("market-data-strip");
        if (!strip) return;
        strip.innerHTML = `
            <div class="md-item md-selected">
                <span class="md-label">Date</span>
                <span class="md-value" style="font-size:11px">${dateStr}</span>
            </div>
            <div class="md-item">
                <span class="md-label">Open</span>
                <span class="md-value">$${fmt(open)}</span>
            </div>
            <div class="md-item">
                <span class="md-label">High</span>
                <span class="md-value up">$${fmt(high)}</span>
            </div>
            <div class="md-item">
                <span class="md-label">Low</span>
                <span class="md-value down">$${fmt(low)}</span>
            </div>
            <div class="md-item">
                <span class="md-label">Close</span>
                <span class="md-value ${dir}">$${fmt(close)}</span>
            </div>
            <div class="md-item">
                <span class="md-label">Change</span>
                <span class="md-value ${dir}">${arrow} ${Math.abs(pct).toFixed(2)}%</span>
            </div>
            <div class="md-item">
                <span class="md-label">Candle Range</span>
                <span class="md-value">$${fmt(range)}</span>
            </div>
            <div class="md-item" style="cursor:pointer;opacity:0.6" onclick="loadStats(state.symbol)" title="Reset to current day">
                <span class="md-label">↩ Reset</span>
                <span class="md-value" style="font-size:10px">Today</span>
            </div>
        `;
    });
}

// Finger-drag scrubbing for touch devices. On a laptop, moving the mouse
// across the chart shows the value under the cursor; we reproduce that on
// touch by mapping the finger's x to a data value and driving Plotly's hover
// there (Fx.hover with an xval snaps to the nearest candle/point under the
// finger and shows its tooltip + crosshair). Verified on candlestick charts.
function attachTouchScrub(el) {
    let scheduled = false;
    let xsClient = [];   // latest finger clientX values (1 or 2)

    // Nearest data index to a finger's screen-x.
    function nearestIdx(clientX) {
        const fl = el._fullLayout;
        const xs = state.chartData && state.chartData.timestamps;
        if (!fl || !fl.xaxis || !xs || !xs.length) return -1;
        const px = clientX - el.getBoundingClientRect().left;
        let best = 0, bestDist = Infinity;
        for (let i = 0; i < xs.length; i++) {
            const dist = Math.abs(fl.xaxis.d2p(xs[i]) - px);
            if (dist < bestDist) { bestDist = dist; best = i; }
        }
        return best;
    }

    function process() {
        scheduled = false;
        if (!xsClient.length) return;
        if (xsClient.length >= 2) {
            // Two fingers → compare the two points (Apple-style).
            try { Plotly.Fx.unhover(el); } catch (_) {}
            const i1 = nearestIdx(xsClient[0]);
            const i2 = nearestIdx(xsClient[1]);
            if (i1 >= 0 && i2 >= 0) showChartCompare(el, i1, i2);
        } else {
            // One finger → scrub: show the value under the finger.
            hideChartCompare();
            const fl = el._fullLayout;
            if (!fl || !fl.xaxis) return;
            const xval = fl.xaxis.p2c(xsClient[0] - el.getBoundingClientRect().left);
            try { Plotly.Fx.hover(el, { xval: xval }); } catch (_) {}
        }
    }

    function read(e) {
        xsClient = [];
        for (let i = 0; i < e.touches.length && i < 2; i++) xsClient.push(e.touches[i].clientX);
    }

    el.addEventListener("touchstart", (e) => { read(e); process(); }, { passive: true });

    el.addEventListener("touchmove", (e) => {
        read(e);
        e.preventDefault();                 // keep the page from scrolling mid-gesture
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(process);
    }, { passive: false });

    el.addEventListener("touchend", (e) => {
        read(e);
        if (e.touches.length < 2) hideChartCompare();
        if (e.touches.length === 0) { try { Plotly.Fx.unhover(el); } catch (_) {} }
        else process();
    }, { passive: true });
}

// Two-point comparison overlay (shaded band + delta readout), fixed-positioned
// over the chart so Plotly never clobbers it.
let _chartSizeObserver = null;
function watchChartSize() {
    const el = document.getElementById("price-chart");
    if (_chartSizeObserver || !el || typeof ResizeObserver === "undefined") return;
    let raf = 0;
    _chartSizeObserver = new ResizeObserver(() => {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => {
            if (el.data) Plotly.Plots.resize(el);
        });
    });
    _chartSizeObserver.observe(el);
}

let _cmpBand = null, _cmpReadout = null;
function _ensureCmpEls() {
    if (_cmpBand) return;
    _cmpBand = document.createElement("div");
    _cmpReadout = document.createElement("div");
    _cmpBand.style.cssText = "position:fixed;z-index:600;pointer-events:none;display:none";
    _cmpReadout.style.cssText = "position:fixed;z-index:601;pointer-events:none;display:none;" +
        "background:rgba(28,30,34,0.96);border:1px solid rgba(255,255,255,0.14);border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.45);" +
        "padding:5px 12px;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text',Inter,'Segoe UI',system-ui,sans-serif;font-size:12px;font-weight:600;font-variant-numeric:tabular-nums;color:#F4F5F7;white-space:nowrap";
    document.body.appendChild(_cmpBand);
    document.body.appendChild(_cmpReadout);
}

function showChartCompare(el, i1, i2) {
    const d = state.chartData;
    if (!d || !d.close || !d.timestamps || !el._fullLayout) return;
    _ensureCmpEls();
    const xaxis = el._fullLayout.xaxis;
    const rect  = el.getBoundingClientRect();
    const lo = Math.min(i1, i2), hi = Math.max(i1, i2);
    const xLo = rect.left + xaxis.d2p(d.timestamps[lo]);
    const xHi = rect.left + xaxis.d2p(d.timestamps[hi]);
    const p1 = d.close[lo], p2 = d.close[hi];
    if (p1 == null || p2 == null) return;
    const delta = p2 - p1;
    const pct   = p1 ? (delta / p1 * 100) : 0;
    const up    = delta >= 0;
    const col   = up ? "#16A34A" : "#DC2626";

    _cmpBand.style.cssText = "position:fixed;z-index:600;pointer-events:none;display:block;" +
        `top:${rect.top}px;left:${xLo}px;width:${Math.max(0, xHi - xLo)}px;height:${rect.height}px;` +
        `background:${up ? "rgba(22,163,74,0.13)" : "rgba(220,38,38,0.13)"};` +
        `border-left:1px solid ${col};border-right:1px solid ${col}`;

    _cmpReadout.style.display = "block";
    _cmpReadout.style.top  = (rect.top + 8) + "px";
    _cmpReadout.style.left = (rect.left + rect.width / 2) + "px";
    _cmpReadout.style.transform = "translateX(-50%)";
    const sign = up ? "+" : "-";
    _cmpReadout.innerHTML =
        `$${fmt(p1)} <span style="color:#6B7280">&rarr;</span> $${fmt(p2)} &nbsp;` +
        `<b style="color:${col}">${sign}$${fmt(Math.abs(delta))} (${sign}${Math.abs(pct).toFixed(2)}%)</b>`;
}

function hideChartCompare() {
    if (_cmpBand)    _cmpBand.style.display = "none";
    if (_cmpReadout) _cmpReadout.style.display = "none";
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

    const strip = document.getElementById("market-data-strip");
    if (!strip) return;
    strip.innerHTML = `
        <div class="md-item">
            <span class="md-label">Symbol</span>
            <span class="md-value" id="current-symbol-badge">${sym}</span>
        </div>
        <div class="md-item">
            <span class="md-label">Open</span>
            <span class="md-value">$${fmt(d.open)}</span>
        </div>
        <div class="md-item">
            <span class="md-label">High</span>
            <span class="md-value up">$${fmt(d.high)}</span>
        </div>
        <div class="md-item">
            <span class="md-label">Low</span>
            <span class="md-value down">$${fmt(d.low)}</span>
        </div>
        <div class="md-item">
            <span class="md-label">Close</span>
            <span class="md-value ${dir}">$${fmt(d.close)}</span>
        </div>
        <div class="md-item">
            <span class="md-label">Change</span>
            <span class="md-value ${dir}">${arrow} ${Math.abs(pct).toFixed(2)}%</span>
        </div>
        <div class="md-item">
            <span class="md-label">Day Range</span>
            <span class="md-value">$${fmt(d.high - d.low)}</span>
        </div>
        <div class="md-range-item">
            <span class="md-label">52W &nbsp;$${fmt(d.low_52w)} — $${fmt(d.high_52w)}</span>
            <div class="md-range-track">
                <div class="md-range-fill" style="width:${range52}%"></div>
                <div class="md-range-cursor" style="left:${range52}%"></div>
            </div>
        </div>
    `;
}

// ============================================================
// INDICATORS PANEL
// ============================================================

function _indBlock(name, badge, detailHtml) {
    return `<div class="ind-card">
        <div class="ind-header-static">
            <span class="ind-name">${name}</span>
            ${badge}
        </div>
        <div class="ind-detail">${detailHtml}</div>
    </div>`;
}

function updateIndicatorsPanel(d) {
    const last = arr => {
        if (!arr) return null;
        for (let i = arr.length - 1; i >= 0; i--)
            if (arr[i] != null) return arr[i];
        return null;
    };

    const rsiVal   = last(d.rsi);
    const macdVal  = last(d.macd);
    const sigVal   = last(d.signal);
    const upper    = last(d.upper_band);
    const lower    = last(d.lower_band);
    const closeVal = last(d.close);
    const zVal     = last(d.zscore);
    const sma20    = last(d.sma20);
    const sma50    = last(d.sma50);
    const ema20    = last(d.ema20);

    // RSI
    let rsiSig = "neutral", rsiLabel = "Neutral";
    if (rsiVal != null) {
        if (rsiVal > 70)      { rsiSig = "sell"; rsiLabel = "Overbought"; }
        else if (rsiVal < 30) { rsiSig = "buy";  rsiLabel = "Oversold"; }
    }
    const rsiPct   = rsiVal != null ? Math.min(100, Math.max(0, rsiVal)) : 0;
    const rsiClass = rsiVal > 70 ? "overbought" : rsiVal < 30 ? "oversold" : "neutral";

    // MACD
    let macdSig = "neutral", macdLabel = "Flat";
    if (macdVal != null && sigVal != null) {
        macdSig   = macdVal > sigVal ? "buy" : "sell";
        macdLabel = macdVal > sigVal ? "Bullish" : "Bearish";
    }

    // BB
    let bbSig = "neutral", bbLabel = "Mid band";
    if (closeVal && upper && lower) {
        const span = upper - lower;
        const pct  = span > 0 ? (closeVal - lower) / span : 0.5;
        if (pct > 0.85)      { bbSig = "sell"; bbLabel = "Near upper"; }
        else if (pct < 0.15) { bbSig = "buy";  bbLabel = "Near lower"; }
    }

    // Z-Score
    let zSig = "neutral", zLabel = "Normal";
    if (zVal != null) {
        if (zVal > 2)        { zSig = "sell"; zLabel = "High"; }
        else if (zVal < -2)  { zSig = "buy";  zLabel = "Low"; }
    }

    const smaArrow  = v => closeVal && v ? (closeVal > v ? "▲ Above" : "▼ Below") : "—";
    const smaSig    = v => closeVal && v ? (closeVal > v ? "buy" : "sell") : "neutral";
    const chip      = (sig, label) => `<span class="signal-chip ${sig}">${label}</span>`;
    // Reuses the chip the four indicators above use, instead of an inline
    // style="color:..." on bare text. The moving-average rows sat in the same
    // column as RSI/MACD/Bollinger/Z-score but rendered as loose red words, so
    // the column read as two different kinds of thing stacked together.
    const trendBadge = v => chip(smaSig(v), smaArrow(v));

    const panel = document.getElementById("indicators-panel");
    if (!panel) return;

    panel.innerHTML =
        _indBlock("RSI (14)", chip(rsiSig, rsiLabel), `
            <div class="ind-row">
                <span class="ind-val">${rsiVal != null ? rsiVal.toFixed(1) : "—"}</span>
            </div>
            <div class="gauge-track">
                <div class="gauge-marks">
                    <div class="gauge-mark" style="left:30%"></div>
                    <div class="gauge-mark" style="left:70%"></div>
                </div>
                <div class="gauge-fill ${rsiClass}" style="width:${rsiPct}%"></div>
            </div>`) +

        _indBlock("MACD", chip(macdSig, macdLabel), `
            <div class="ind-row">
                <span class="ind-val">${macdVal != null ? macdVal.toFixed(3) : "—"}</span>
                <span class="ind-sub">SIG ${sigVal != null ? sigVal.toFixed(3) : "—"}</span>
            </div>`) +

        _indBlock("Bollinger Bands", chip(bbSig, bbLabel), `
            <div class="ind-row">
                <span class="ind-sub">U: ${upper ? "$" + fmt(upper) : "—"}</span>
                <span class="ind-sub">L: ${lower ? "$" + fmt(lower) : "—"}</span>
            </div>`) +

        _indBlock("Z-Score (20)", chip(zSig, zLabel), `
            <div class="ind-row">
                <span class="ind-val">${zVal != null ? zVal.toFixed(2) : "—"}</span>
            </div>`) +

        _indBlock("SMA 20", trendBadge(sma20), `
            <div class="ind-row">
                <span class="ind-val">${sma20 ? "$" + fmt(sma20) : "—"}</span>
            </div>`) +

        (sma50 ? _indBlock("SMA 50", trendBadge(sma50), `
            <div class="ind-row">
                <span class="ind-val">$${fmt(sma50)}</span>
            </div>`) : "") +

        _indBlock("EMA 20", trendBadge(ema20), `
            <div class="ind-row">
                <span class="ind-val">${ema20 ? "$" + fmt(ema20) : "—"}</span>
            </div>`);
}

// ============================================================
// TICKER TAPE
// ============================================================

async function buildTickerTape() {
    const tape    = document.getElementById("ticker-tape");
    const results = [];

    for (const sym of TICKER_SYMS) {
        if (idleAsleep) return;   // the page went idle mid-run (see initIdleWatch)
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
        return `<span class="ticker-item">
            <span class="ticker-symbol">${symbol}</span>
            <span class="ticker-price">$${fmt(price)}</span>
            <span class="ticker-change ${dir}">${sign}${pct.toFixed(2)}%</span>
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
    if (!el) return;
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
    if (!getToken()) { renderSignedOutAlerts(); return; }
    try {
        const res = await fetch(`${CFG.API}/alerts`);
        if (res.status === 401) { clearSession(); renderSignedOutAlerts(); return; }
        if (!res.ok) return;
        state.alerts = await res.json();
        renderAlertList();
    } catch (_) {}
}

function renderAlertList() {
    const el    = document.getElementById("active-alerts-list");
    const badge = document.getElementById("alert-count");
    const footer = document.getElementById("alert-footer");
    if (footer) footer.style.display = "";
    badge.textContent = state.alerts.length;

    if (!state.alerts.length) {
        el.innerHTML = `<div class="feed-empty">No alerts set</div>`;
        return;
    }

    el.innerHTML = state.alerts.map(([id, sym, type, thresh]) => `
        <div class="alert-row">
            <div class="alert-row-left">
                <span class="alert-sym-type">${escapeHtml(String(sym))} · ${escapeHtml(fmtAlertType(type))}</span>
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
    if (!getToken()) { openAuthModal("login"); return; }
    const symbol    = document.getElementById("alert-symbol").value.trim().toUpperCase();
    const alertType = document.getElementById("alert-type").value;
    const threshold = parseFloat(document.getElementById("alert-threshold").value) || null;

    if (!symbol) {
        document.getElementById("alert-symbol").focus();
        return;
    }

    try {
        await fetch(`${CFG.API}/alerts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol, alert_type: alertType, threshold }),
        });
        document.getElementById("alert-modal").style.display = "none";
        document.getElementById("alert-symbol").value = "";
        document.getElementById("alert-threshold").value = "";
        await loadAlerts();
        pushFeed(`Alert created: ${symbol} ${fmtAlertType(alertType)}`, "buy");
    } catch (_) {
        setStatus("Failed to create alert");
    }
}

// ============================================================
// SIDEBAR TABS
// ============================================================

function initSidebarTabs() {
    document.querySelectorAll(".sidebar-tab").forEach(btn => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll(".sidebar-tab").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            document.querySelectorAll(".tab-pane").forEach(p => { p.style.display = "none"; });
            const pane = document.getElementById(`tab-${tab}`);
            if (pane) pane.style.display = "";
        });
    });
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
    const importFile = document.getElementById("pf-import-file");
    document.getElementById("pf-import-btn").addEventListener("click", () => importFile.click());
    importFile.addEventListener("change", () => {
        if (importFile.files[0]) importHoldingsCsv(importFile.files[0]);
        importFile.value = "";   // so choosing the same file again still fires
    });
    loadPortfolio();
    setInterval(() => { if (!pageIdle()) loadPortfolio(); }, CFG.PORTFOLIO_REFRESH_MS);
}

async function loadPortfolio() {
    if (!getToken()) { sampleActive ? loadSamplePortfolio() : renderSignedOutPortfolio(); return; }
    sampleActive = false;
    try {
        const res  = await fetch(`${CFG.API}/portfolio`);
        if (res.status === 401) { clearSession(); renderSignedOutPortfolio(); return; }
        const data = await res.json();
        renderPortfolio(data);
    } catch {
        // silently ignore if backend not up
    }
}

function renderPortfolio(data, sample = false) {
    const list  = document.getElementById("portfolio-list");
    const badge = document.getElementById("portfolio-total-badge");
    const footer = document.getElementById("pf-footer");
    if (footer) footer.style.display = sample ? "none" : "";

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
        document.getElementById("pf-risk").style.display = "none";
        showSkiStarters(false);
        return;
    }

    showSkiStarters(true);
    if (sample) {
        document.getElementById("pf-risk").style.display = "none";
    } else {
        loadPortfolioRisk();
        loadSkiBriefing();
    }

    list.innerHTML = sample
        ? '<div class="sample-note">Sample portfolio, not saved. Ask Ski about it, or '
          + '<button class="text-btn" onclick="openAuthModal(\'register\')">sign up</button> to track your own. '
          + '<button class="text-btn" onclick="renderSignedOutPortfolio()">Close</button></div>'
        : "";
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
        if (!sample) row1.appendChild(del);

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

// ---- CSV import -------------------------------------------------------------
// Adding holdings one at a time is the main chore for a new account. This reads
// a broker export or a hand-made sheet in the browser, maps the usual header
// names, and adds each row through the normal /portfolio endpoint (which
// upserts, so re-importing the same file updates rather than duplicates).
const CSV_IMPORT_MAX = 100;
const CSV_COLS = {
    symbol: ["symbol", "ticker", "security", "instrument"],
    shares: ["shares", "quantity", "qty", "units", "position"],
    avg:    ["average cost basis", "avg cost basis", "average cost", "avg cost", "cost per share",
             "avg price", "average price", "purchase price", "price paid", "avg_cost", "cost basis per share"],
    total:  ["cost basis total", "total cost basis", "cost basis", "total cost"],
};

function parseCsvLine(line) {
    const out = []; let cur = "", q = false;
    for (let i = 0; i < line.length; i++) {
        const c = line[i];
        if (q) {
            if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
            else if (c === '"') q = false;
            else cur += c;
        } else if (c === '"') q = true;
        else if (c === ",") { out.push(cur); cur = ""; }
        else cur += c;
    }
    out.push(cur);
    return out.map(x => x.trim());
}

function csvNumber(v) {
    if (v == null) return NaN;
    const s = String(v).replace(/[$,\s]/g, "").replace(/^\((.*)\)$/, "-$1");
    return s === "" || s === "--" ? NaN : Number(s);
}

function parseHoldingsCsv(text) {
    const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter(l => l.trim());
    if (!lines.length) return { rows: [], skipped: [], error: "The file is empty." };
    const head = parseCsvLine(lines[0]).map(h => h.toLowerCase().replace(/\s+/g, " ").trim());
    const find = names => head.findIndex(h => names.includes(h));
    const ci = { symbol: find(CSV_COLS.symbol), shares: find(CSV_COLS.shares),
                 avg: find(CSV_COLS.avg), total: find(CSV_COLS.total) };
    if (ci.symbol < 0 || ci.shares < 0) {
        return { rows: [], skipped: [], error: "Need a header row with Symbol and Shares (or Quantity) columns." };
    }
    const rows = [], skipped = [];
    for (let i = 1; i < lines.length; i++) {
        const cells = parseCsvLine(lines[i]);
        // Brokers write class shares as BRK.B or BRK/B; the price API wants BRK-B.
        const symbol = (cells[ci.symbol] || "").toUpperCase().replace(/[./]/g, "-").replace(/[^A-Z0-9-]/g, "").slice(0, 10);
        const shares = csvNumber(cells[ci.shares]);
        if (!symbol) { skipped.push({ line: i + 1, reason: "no symbol" }); continue; }
        if (!(shares > 0)) { skipped.push({ line: i + 1, reason: `${symbol}: no positive share count` }); continue; }
        let avg = ci.avg >= 0 ? csvNumber(cells[ci.avg]) : NaN;
        if (!(avg >= 0) && ci.total >= 0) avg = csvNumber(cells[ci.total]) / shares;
        rows.push({ symbol, shares, avg_cost: avg >= 0 && isFinite(avg) ? +avg.toFixed(4) : null });
    }
    if (rows.length > CSV_IMPORT_MAX) {
        return { rows: [], skipped, error: `That is ${rows.length} rows; import up to ${CSV_IMPORT_MAX} at a time.` };
    }
    return { rows, skipped, error: null };
}

async function importHoldingsCsv(file) {
    const msg = document.getElementById("pf-import-msg");
    const btn = document.getElementById("pf-import-btn");
    if (!getToken()) { openAuthModal("login"); return; }
    const { rows, skipped, error } = parseHoldingsCsv(await file.text());
    if (error) { msg.textContent = error; return; }
    if (!rows.length) { msg.textContent = "No holdings found in that file."; return; }
    btn.disabled = true;
    let ok = 0;
    const failed = [];
    for (const [n, r] of rows.entries()) {
        msg.textContent = `Importing ${n + 1} of ${rows.length}…`;
        try {
            const res = await fetch(`${CFG.API}/portfolio`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(r),
            });
            if (res.ok) ok += 1; else failed.push(r.symbol);
        } catch { failed.push(r.symbol); }
    }
    btn.disabled = false;
    const parts = [`Imported ${ok} holding${ok === 1 ? "" : "s"}.`];
    if (skipped.length) parts.push(`Skipped ${skipped.length} row${skipped.length === 1 ? "" : "s"} (${skipped.slice(0, 3).map(s => s.reason).join("; ")}${skipped.length > 3 ? "; …" : ""}).`);
    if (failed.length) parts.push(`Could not add ${failed.slice(0, 5).join(", ")}.`);
    msg.textContent = parts.join(" ");
    await loadPortfolio();
}

async function submitHolding() {
    if (!getToken()) { openAuthModal("login"); return; }
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
    briefingLoaded: false,   // proactive briefing fetched once per session
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

    document.querySelectorAll(".ski-starter-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            input.value = btn.dataset.prompt;
            input.focus();
        });
    });
}

function showSkiStarters(hasPortfolio) {
    const starters = document.getElementById("ski-starters");
    if (!starters) return;
    if (hasPortfolio) starters.classList.add("visible");
    else starters.classList.remove("visible");
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
    if (isLoading) {
        // Animated typing dots so the user can see Ski is working, not frozen.
        bubble.innerHTML = '<span class="ski-typing"><span></span><span></span><span></span></span>';
    } else {
        bubble.textContent = content;
    }
    wrap.appendChild(bubble);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
    return bubble;
}

// Render a Ski reply as a card: a "Bottom line:" first line becomes the
// summary, "- " / "• " lines become a list, **text** is bold, signed
// percentages are coloured, and a "Watch:" line (the briefing) is a callout.
// Everything is escaped first, so the reply can never inject markup; the only
// links kept are http(s) markdown links from web-search citations.
function formatSkiText(text) {
    const inline = (raw) => escapeHtml(raw)
        .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
                 '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[\s(])([+−-]\d[\d,]*(?:\.\d+)?%)/g, (m, pre, pct) =>
            `${pre}<span class="${/^\+/.test(pct) ? "ski-up" : "ski-down"}">${pct}</span>`);

    const out = [];
    let list = null;
    const flush = () => { if (list) { out.push(`<ul class="ski-list">${list.join("")}</ul>`); list = null; } };

    for (let line of String(text).split(/\r?\n/)) {
        line = line.trim();
        if (!line) { flush(); continue; }
        line = line.replace(/^#{1,6}\s+/, "");
        const bottom = line.match(/^\**bottom line:?\**:?\s*(.*)$/i);
        const watch = line.match(/^watch:\s*(.*)$/i);
        const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
        if (bottom) { flush(); out.push(`<div class="ski-summary">${inline(bottom[1])}</div>`); }
        else if (watch) { flush(); out.push(`<div class="ski-watch"><span>Watch</span>${inline(watch[1])}</div>`); }
        else if (bullet) { (list ||= []).push(`<li>${inline(bullet[1])}</li>`); }
        else { flush(); out.push(`<p>${inline(line)}</p>`); }
    }
    flush();
    return out.join("");
}

function setSkiReply(el, text) {
    el.innerHTML = formatSkiText(text);
    el.classList.add("ski-rich");
}

function buildChartContext() {
    const d = state.chartData;
    if (!d) return null;
    const last = arr => Array.isArray(arr) && arr.length ? arr[arr.length - 1] : null;
    return {
        symbol:          state.symbol,
        timeframe:       state.timeframe,
        close:           last(d.close),
        rsi:             last(d.rsi),
        macd:            last(d.macd),
        macd_signal:     last(d.signal),
        macd_histogram:  last(d.histogram),
        sma20:           last(d.sma20),
        sma50:           last(d.sma50),
        ema20:           last(d.ema20),
        upper_band:      last(d.upper_band),
        lower_band:      last(d.lower_band),
        zscore:          last(d.zscore),
        volatility:      last(d.volatility),
    };
}

// Proactive briefing — Ski greets a signed-in user with a portfolio-aware
// rundown the moment their holdings load, instead of waiting to be asked.
async function loadSkiBriefing() {
    if (skiState.briefingLoaded || !getToken()) return;
    skiState.briefingLoaded = true;   // guard against portfolio-refresh re-fires
    try {
        const res = await fetch(`${CFG.API}/briefing`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
        });
        if (!res.ok) { skiState.briefingLoaded = false; return; }
        const data = await res.json();
        if (!data.briefing) return;   // no holdings / not configured — stay quiet
        renderSkiBriefing(data.briefing);
    } catch {
        skiState.briefingLoaded = false;   // backend asleep — retry next load
    }
}

function renderSkiBriefing(text) {
    const container = document.getElementById("ski-messages");
    if (!container) return;

    const wrap = document.createElement("div");
    wrap.className = "ski-message ski-message-assistant";
    const bubble = document.createElement("div");
    bubble.className = "ski-bubble ski-briefing";

    const label = document.createElement("div");
    label.className = "ski-briefing-label";
    label.textContent = "Your briefing";
    const body = document.createElement("div");
    body.className = "ski-briefing-body";
    setSkiReply(body, text);

    bubble.appendChild(label);
    bubble.appendChild(body);
    wrap.appendChild(bubble);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;

    // Give Ski follow-up context, and nudge the closed FAB so the user notices.
    skiState.history.push({ role: "assistant", content: text });
    if (!skiState.open) {
        const badge = document.getElementById("ski-badge");
        if (badge) badge.style.display = "";
    }
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
            body: JSON.stringify({
                message,
                history: skiState.history.slice(0, -1),
                symbol: state.symbol,
                chart_context: buildChartContext(),
                sample_portfolio: sampleActive && !getToken() ? SAMPLE_PORTFOLIO : undefined,
            }),
        });
        if (res.status === 429) {
            loadingBubble.textContent = "Rate limit reached — you can send up to 20 messages per hour. Try again later.";
            loadingBubble.classList.remove("loading");
            skiState.history.pop();
            return;
        }
        if (res.status === 503) {
            loadingBubble.textContent = "Ski is temporarily offline — the AI service is overloaded. Try again in 30 seconds.";
            loadingBubble.classList.remove("loading");
            skiState.history.pop();
            return;
        }
        const data = await res.json();
        const reply = data.reply || data.error || "No response.";
        if (data.reply) setSkiReply(loadingBubble, reply);
        else loadingBubble.textContent = reply;
        loadingBubble.classList.remove("loading");
        skiState.history.push({ role: "assistant", content: reply });
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
    FEDFUNDS:     { short: "Fed funds", tip: "Effective Federal Funds Rate" },
    GDP:          { short: "GDP",      tip: "Real GDP (Chained 2017 $B)" },
    UNRATE:       { short: "Unemployment", tip: "Unemployment Rate" },
    DGS10:        { short: "10Y yield", tip: "10-Year Treasury Yield" },
    T10Y2Y:       { short: "Yield curve", tip: "Yield Curve (10Y−2Y Spread)" },
    BAMLH0A0HYM2: { short: "HY spread", tip: "High Yield OAS Credit Spread" },
};

async function loadMacroRibbon() {
    const inner = document.getElementById("macro-inner");
    if (!inner) return;

    try {
        const res = await fetch(`${CFG.API}/macro`);
        let data;
        try { data = await res.json(); } catch { data = {}; }
        if (!res.ok || data.error) {
            const msg = data.error || `HTTP ${res.status}`;
            inner.innerHTML = `<div class="macro-item"><span class="macro-error">Federal Reserve data unavailable (${msg})</span></div>`;
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
            const val      = info.value == null ? "—"
                : (info.unit === "B" && Math.abs(info.value) >= 1000)
                    ? `$${(info.value / 1000).toFixed(1)}T`
                    : `${info.value}${info.unit}`;
            const arrow    = arrowMap[info.trend] || "";

            item.innerHTML = `
                <span class="macro-label">${meta.short}</span>
                <span class="macro-value ${cls}">${val}${arrow}</span>
            `;
            inner.appendChild(item);
        }
    } catch {
        inner.innerHTML = '<div class="macro-item"><span class="macro-error">Macro data unavailable</span></div>';
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadMacroRibbon();
    setInterval(() => { if (!pageIdle()) loadMacroRibbon(); }, 3_600_000); // refresh every hour
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
    const feed = document.getElementById("news-feed");
    const chip = document.getElementById("agg-sentiment-chip");
    if (!feed) return;

    feed.innerHTML = '<div class="feed-empty">Loading news…</div>';

    try {
        const res  = await fetch(`${CFG.API}/news?symbol=${encodeURIComponent(sym)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const articles = data.articles || [];
        const agg      = data.aggregate || {};

        if (chip) {
            const label = agg.label || "neutral";
            const sign  = (agg.score || 0) >= 0 ? "+" : "";
            chip.textContent = `${label.charAt(0).toUpperCase() + label.slice(1)} ${sign}${(agg.score || 0).toFixed(2)}`;
            chip.className   = `sentiment-chip ${label}`;
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
                    <span class="news-sentiment ${lbl}">${lbl.charAt(0).toUpperCase() + lbl.slice(1)} ${score}</span>
                </div>
                <a class="news-title" href="${escapeHtml(/^https?:\/\//i.test(a.url || "") ? a.url : "#")}" target="_blank" rel="noopener">
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

// ============================================================
// CORRELATION HEATMAP
// ============================================================

function initHeatmap() {
    document.getElementById("open-heatmap-btn").addEventListener("click", openHeatmap);
    document.getElementById("close-heatmap-btn").addEventListener("click", closeHeatmap);
    document.getElementById("heatmap-modal").addEventListener("click", (e) => {
        if (e.target === e.currentTarget) closeHeatmap();
    });
}

function openHeatmap() {
    document.getElementById("heatmap-modal").style.display = "flex";
    loadHeatmap();
}

function closeHeatmap() {
    document.getElementById("heatmap-modal").style.display = "none";
}

async function loadHeatmap() {
    const container = document.getElementById("heatmap-chart");
    const loading   = document.getElementById("heatmap-loading");
    if (loading) loading.style.display = "flex";

    try {
        const res  = await fetch(`${CFG.API}/correlation`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        if (loading) loading.style.display = "none";

        const syms   = data.symbols;
        const matrix = data.matrix;

        // Reverse row order so diagonal reads top-left → bottom-right
        const zReversed = [...matrix].reverse();
        const yLabels   = [...syms].reverse();

        const customColorscale = [
            [0.0,  "#DC2626"],
            [0.25, "#F87171"],
            [0.5,  "#1E293B"],
            [0.75, "#60A5FA"],
            [1.0,  "#16A34A"],
        ];

        const trace = {
            type: "heatmap",
            z: zReversed,
            x: syms,
            y: yLabels,
            colorscale: customColorscale,
            zmin: -1, zmax: 1,
            text: zReversed.map(row => row.map(v => v.toFixed(2))),
            texttemplate: "%{text}",
            textfont: { size: 11, color: "#F8FAFC", family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif" },
            hovertemplate: "<b>%{x} / %{y}</b><br>Correlation: %{z:.3f}<extra></extra>",
            showscale: true,
            colorbar: {
                thickness: 14,
                len: 0.9,
                tickfont: { color: "#9BA2AD", size: 11, family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif" },
                tickvals: [-1, -0.5, 0, 0.5, 1],
            },
        };

        const layout = {
            paper_bgcolor: "#1C1E22",
            plot_bgcolor:  "#1C1E22",
            margin: { l: 70, r: 20, t: 20, b: 70 },
            xaxis: {
                tickfont: { color: "#9BA2AD", size: 11, family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif" },
                showgrid: false, zeroline: false,
            },
            yaxis: {
                tickfont: { color: "#9BA2AD", size: 11, family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif" },
                showgrid: false, zeroline: false,
            },
        };

        Plotly.newPlot(container, [trace], layout, { responsive: true, displayModeBar: false });
    } catch (err) {
        if (loading) loading.style.display = "none";
        container.innerHTML = `<div class="feed-empty">Heatmap unavailable: ${err.message}</div>`;
    }
}

document.addEventListener("DOMContentLoaded", () => { initHeatmap(); });

// ============================================================
// PORTFOLIO RISK METRICS
// ============================================================

async function loadPortfolioRisk() {
    const row     = document.getElementById("pf-risk");
    const sharpeEl = document.getElementById("pf-sharpe");
    const betaEl   = document.getElementById("pf-beta");
    const volEl    = document.getElementById("pf-vol");
    if (!row) return;

    try {
        const res  = await fetch(`${CFG.API}/portfolio/risk`);
        if (!res.ok) { row.style.display = "none"; return; }
        const data = await res.json();
        if (data.error) { row.style.display = "none"; return; }

        sharpeEl.textContent = data.sharpe != null ? data.sharpe.toFixed(2) : "—";
        betaEl.textContent   = data.beta   != null ? data.beta.toFixed(2)   : "—";
        volEl.textContent    = data.volatility != null ? `${data.volatility}%` : "—";

        sharpeEl.className = "pf-risk-val" + (data.sharpe >= 1 ? " up" : data.sharpe < 0 ? " down" : "");
        betaEl.className   = "pf-risk-val";
        volEl.className    = "pf-risk-val";

        row.style.display = "flex";
    } catch {
        row.style.display = "none";
    }
}

// ============================================================
// COMPARE CHART
// ============================================================

const compareState = {
    active:  false,
    symbols: [],
};

const COMPARE_COLORS = ["#F59E0B", "#10B981", "#EF4444", "#8B5CF6", "#EC4899", "#06B6D4"];

function initCompareMode() {
    document.getElementById("compare-btn").addEventListener("click", toggleCompareMode);
    document.getElementById("compare-exit-btn").addEventListener("click", toggleCompareMode);
    document.getElementById("compare-add-btn").addEventListener("click", addCompareSymbol);
    attachSymbolSuggest(document.getElementById("compare-input"), addCompareSymbol);
    document.getElementById("compare-input").addEventListener("keydown", (e) => {
        if (e.key === "Enter") addCompareSymbol();
    });
}

function toggleCompareMode() {
    compareState.active = !compareState.active;
    const btn       = document.getElementById("compare-btn");
    const controls  = document.getElementById("compare-controls");
    const typeGroup = document.getElementById("chart-type-group");
    const tfGroup   = document.getElementById("timeframe-group");

    if (compareState.active) {
        btn.classList.add("active");
        controls.style.display = "flex";
        typeGroup.style.display = "none";
        tfGroup.style.display   = "none";
        if (compareState.symbols.length === 0) renderCompareChart();
    } else {
        btn.classList.remove("active");
        controls.style.display  = "none";
        typeGroup.style.display = "";
        tfGroup.style.display   = "";
        compareState.symbols    = [];
        renderCompareChips();
        loadDashboard(state.symbol);
    }
}

function addCompareSymbol() {
    const input = document.getElementById("compare-input");
    const sym   = input.value.trim().toUpperCase();
    input.value = "";
    if (!sym || compareState.symbols.includes(sym) || sym === state.symbol) return;
    if (compareState.symbols.length >= 5) return;
    compareState.symbols.push(sym);
    renderCompareChips();
    renderCompareChart();
}

function removeCompareSymbol(sym) {
    compareState.symbols = compareState.symbols.filter(s => s !== sym);
    renderCompareChips();
    renderCompareChart();
}

function renderCompareChips() {
    const container = document.getElementById("compare-chips");
    container.innerHTML = compareState.symbols.map((sym, i) => `
        <span class="compare-chip" style="border-color:${COMPARE_COLORS[i]}; color:${COMPARE_COLORS[i]}">
            ${sym}
            <button class="compare-chip-remove" onclick="removeCompareSymbol('${sym}')">✕</button>
        </span>
    `).join("");
}

async function renderCompareChart() {
    const allSyms = [state.symbol, ...compareState.symbols];
    showChartLoading(true);

    // The market-data provider occasionally returns nothing for one of several
    // parallel requests (the backend answers 404), and that symbol used to drop
    // off the chart without a word. Retry once, then say which ones are missing.
    const fetchSeries = async (sym, retries = 1) => {
        try {
            const res = await fetch(`${CFG.API}/price_history?symbol=${sym}&tf=1M`);
            if (res.ok) {
                const d = await res.json();
                return { sym, timestamps: d.timestamps, close: d.close };
            }
        } catch { /* network error: fall through to the retry */ }
        if (retries > 0) {
            await new Promise(r => setTimeout(r, 800));
            return fetchSeries(sym, retries - 1);
        }
        return null;
    };
    const fetched = await Promise.all(allSyms.map(sym => fetchSeries(sym)));

    showChartLoading(false);
    const missing = allSyms.filter((s, i) => !fetched[i]);
    if (missing.length) setStatus(`Couldn't load ${missing.join(", ")} for comparison. Try adding it again.`);
    const valid = fetched.filter(Boolean);
    if (!valid.length) return;

    // Align to shortest series
    const minLen = Math.min(...valid.map(d => d.close.length));

    const traces = valid.map((d, i) => {
        const closes   = d.close.slice(-minLen);
        const base     = closes[0] || 1;
        const normed   = closes.map(v => parseFloat(((v / base - 1) * 100).toFixed(2)));
        const color    = i === 0 ? "#3B82F6" : COMPARE_COLORS[i - 1];
        return {
            type: "scatter", mode: "lines",
            x: d.timestamps.slice(-minLen),
            y: normed,
            name: d.sym,
            line: { color, width: 2 },
            hovertemplate: `<b>%{y:+.2f}%</b><extra>${d.sym}</extra>`,
        };
    });

    const layout = {
        paper_bgcolor: "#0A0B0D",
        plot_bgcolor:  "#0A0B0D",
        margin: { l: 50, r: 10, t: 10, b: 40 },
        xaxis: {
            type: "date",
            color: "#7C838E", gridcolor: "rgba(255,255,255,0.05)",
            tickfont: { color: "#7C838E", size: 11, family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif" },
            fixedrange: IS_TOUCH,
        },
        yaxis: {
            ticksuffix: "%",
            color: "#7C838E", gridcolor: "rgba(255,255,255,0.05)",
            zeroline: true, zerolinecolor: "rgba(255,255,255,0.18)",
            tickfont: { color: "#7C838E", size: 11, family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif" },
            fixedrange: IS_TOUCH,
        },
        legend: {
            font: { color: "#9BA2AD", size: 11, family: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', Inter, 'Segoe UI', system-ui, sans-serif" },
            bgcolor: "rgba(0,0,0,0)",
            orientation: "h", y: -0.12,
        },
        hovermode: "x unified",
        dragmode: IS_TOUCH ? false : "zoom",
    };

    Plotly.newPlot("price-chart", traces, layout, { responsive: true, displayModeBar: false });
}

document.addEventListener("DOMContentLoaded", () => { initCompareMode(); });

// ============================================================
// API HEALTH CHECK
// ============================================================


// ============================================================
// MOBILE DRAWER
// ============================================================

function initMobileDrawer() {
    const btn      = document.getElementById("hamburger-btn");
    const overlay  = document.getElementById("mobile-overlay");
    const closeBtn = document.getElementById("mobile-drawer-close");
    const sidebar  = document.querySelector(".sidebar-left");

    if (!btn || !overlay) return;

    btn.addEventListener("click", openMobileDrawer);
    if (closeBtn) closeBtn.addEventListener("click", closeMobileDrawer);
    overlay.addEventListener("click", closeMobileDrawer);

    // Keep the open drawer pinned to the *visible* area. When the iOS
    // keyboard slides up it shrinks the visual viewport — without this
    // the drawer stays full-height and the keyboard hides the form
    // fields (e.g. "Shares"), making entry impossible.
    if (window.visualViewport) {
        window.visualViewport.addEventListener("resize", syncDrawerToViewport);
        window.visualViewport.addEventListener("scroll", syncDrawerToViewport);
    }

    // When a field is focused, lift it into the middle of whatever space
    // is left above the keyboard so the user always sees what they type.
    if (sidebar) {
        sidebar.addEventListener("focusin", (e) => {
            if (e.target.matches("input, select, textarea")) {
                setTimeout(() => e.target.scrollIntoView({ block: "center" }), 280);
            }
        });
    }

    // Rotating to landscape (or any non-mobile width) switches to the full
    // desktop layout — make sure the fixed drawer/overlay never linger.
    window.addEventListener("resize", () => {
        const isMobilePortrait = window.matchMedia(
            "(max-width: 768px) and (orientation: portrait)"
        ).matches;
        if (!isMobilePortrait) closeMobileDrawer();
    });
}

// Shrink the drawer to the area the keyboard leaves visible.
function syncDrawerToViewport() {
    const sidebar = document.querySelector(".sidebar-left");
    if (!sidebar || !sidebar.classList.contains("mobile-open")) return;
    const vv = window.visualViewport;
    if (!vv) return;
    sidebar.style.top    = vv.offsetTop + "px";
    sidebar.style.bottom = "auto";
    sidebar.style.height = vv.height + "px";
}

function openMobileDrawer() {
    const overlay = document.getElementById("mobile-overlay");
    const sidebar = document.querySelector(".sidebar-left");
    if (!overlay || !sidebar) return;

    sidebar.classList.add("mobile-open");
    overlay.style.display = "block";
    document.body.style.overflow = "hidden";
    syncDrawerToViewport();
}

function closeMobileDrawer() {
    const overlay = document.getElementById("mobile-overlay");
    const sidebar = document.querySelector(".sidebar-left");
    if (!overlay || !sidebar) return;

    sidebar.classList.remove("mobile-open");
    overlay.style.display = "none";
    document.body.style.overflow = "";

    // Drop the keyboard-fit sizing so the drawer is full-height next time.
    sidebar.style.top    = "";
    sidebar.style.bottom = "";
    sidebar.style.height = "";
}
