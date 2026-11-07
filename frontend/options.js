// options.js — the Options page (/options): chain with filters, strategy
// builder, scanner.
//
// Every number (IV, Greeks, P/L, probabilities) is computed by the backend
// (tracker/options.py); this file only filters, lays out and charts it. It
// runs on its own page, so it depends on nothing from dashboard.js. The page
// state (symbol, expiry, tab) lives in the URL, so a view can be linked to.

const OPT_PRESETS = [
    ["long_call", "Long call"], ["long_put", "Long put"],
    ["covered_call", "Covered call"], ["cash_secured_put", "Cash-secured put"],
    ["bull_call_spread", "Bull call spread"], ["bear_put_spread", "Bear put spread"],
    ["long_straddle", "Long straddle"], ["long_strangle", "Long strangle"],
    ["iron_condor", "Iron condor"],
];

const OPT_SCAN_DEFAULT = "AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, SPY, QQQ";
const OPT_API = "https://tradeski.onrender.com";
// Quick picks: the symbols whose closing chains are always saved (see capture_snapshot.py).
const OPT_QUICK = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ", "JPM", "SOFI", "RDW"];
const OPT_TABS = ["chain", "strategy", "scan"];
const OPT_SKI_KEY = "tradeski-ski-prompt";   // read by dashboard.js on load
// Fewer daily readings than this and a percentile says more about the sample than the stock.
const OPT_IV_MIN_DAYS = 20;

const optState = {
    symbol: null,
    expiry: null,
    expirations: [],
    chain: null,
    tab: "chain",
    legs: [],          // [{type, qty, strike}]
    preset: null,
    daysForward: 0,
    analysis: null,
    scan: null,
    scanSort: { col: "annualized_pct", dir: -1 },
    reqId: 0,
    ivHistory: undefined,   // undefined = not loaded yet, null = unavailable
};

// ---------- pure helpers (unit-tested in tests/js/options.test.mjs) ----------

function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// The page's starting state from its query string: ?symbol=NVDA&expiry=2026-12-18&tab=strategy.
function optParseQuery(search) {
    const q = new URLSearchParams(search || "");
    const sym = (q.get("symbol") || "").trim().toUpperCase();
    const tab = q.get("tab");
    const expiry = q.get("expiry") || "";
    return {
        symbol: /^[A-Z][A-Z0-9.\-]{0,9}$/.test(sym) ? sym : "AAPL",
        tab: OPT_TABS.includes(tab) ? tab : "chain",
        expiry: /^\d{4}-\d{2}-\d{2}$/.test(expiry) ? expiry : "",
    };
}

function optNum(v) {
    if (v === "" || v === null || v === undefined) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

// Does one contract pass the chain filters? f: {deltaMin, deltaMax, minOi, minVol, maxSpread}
function optPasses(c, f) {
    if (!c) return false;
    const d = c.delta === null || c.delta === undefined ? null : Math.abs(c.delta);
    if (f.deltaMin !== null && (d === null || d < f.deltaMin)) return false;
    if (f.deltaMax !== null && (d === null || d > f.deltaMax)) return false;
    if (f.minOi !== null && c.open_interest < f.minOi) return false;
    if (f.minVol !== null && c.volume < f.minVol) return false;
    if (f.maxSpread !== null && (c.spread_pct === null || c.spread_pct > f.maxSpread)) return false;
    return true;
}

// Chain rows by strike: [{strike, call, put}], each side null if it fails the
// filters; rows outside the strike window or with neither side are dropped.
function optChainRows(chain, f) {
    const byStrike = new Map();
    const add = (c, side) => {
        if (!byStrike.has(c.strike)) byStrike.set(c.strike, { strike: c.strike, call: null, put: null });
        byStrike.get(c.strike)[side] = c;
    };
    chain.calls.forEach(c => add(c, "call"));
    chain.puts.forEach(p => add(p, "put"));
    const lo = f.windowPct === null ? -Infinity : chain.spot * (1 - f.windowPct / 100);
    const hi = f.windowPct === null ? Infinity : chain.spot * (1 + f.windowPct / 100);
    const rows = [];
    for (const row of [...byStrike.values()].sort((a, b) => a.strike - b.strike)) {
        if (row.strike < lo || row.strike > hi) continue;
        const call = f.side !== "puts" && optPasses(row.call, f) ? row.call : null;
        const put = f.side !== "calls" && optPasses(row.put, f) ? row.put : null;
        if (call || put) rows.push({ strike: row.strike, call, put });
    }
    return rows;
}

function optMoney(v, signed) {
    if (v === null || v === undefined) return "—";
    const abs = Math.abs(v);
    const s = abs >= 100 ? abs.toLocaleString("en-US", { maximumFractionDigits: 0 })
                         : abs.toFixed(2);
    const sign = v < 0 ? "-" : (signed && v > 0 ? "+" : "");
    return `${sign}$${s}`;
}

function optPct(v, digits) {
    return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits === undefined ? 1 : digits)}%`;
}

// Where today's ATM IV sits among the recorded daily readings (rows of
// [date, iv, dte], from frontend/data/iv_history.json). Readings dated
// ``today`` are left out so today isn't ranked against itself. pct is null
// until there are OPT_IV_MIN_DAYS readings.
function optIvRank(rows, current, today, minDays) {
    const past = (rows || []).filter(r => r[0] !== today && Number.isFinite(r[1]));
    const out = { n: past.length, since: past.length ? past[0][0] : null, pct: null, low: null, high: null };
    if (!past.length || !Number.isFinite(current)) return out;
    const ivs = past.map(r => r[1]);
    out.low = Math.min(...ivs);
    out.high = Math.max(...ivs);
    if (past.length >= minDays) out.pct = Math.round(ivs.filter(v => v < current).length / ivs.length * 100);
    return out;
}

// "Buy 1 AAPL 350 call" etc., for the Ski prompt and leg list.
function optLegText(leg, symbol) {
    const n = Math.abs(leg.qty);
    const act = leg.qty > 0 ? "buy" : "sell";
    if (leg.type === "stock") return `${act} ${n * 100} ${symbol} shares`;
    return `${act} ${n} ${symbol} ${leg.strike} ${leg.type}${n > 1 ? "s" : ""}`;
}

// ---------- data ----------

// True when demo-mode.js is replaying the offline snapshot.
function optOffline() {
    return !!(window.TRADESKI_DEMO_MODE || window.TRADESKI_OFFLINE);
}

async function optFetch(path, body) {
    const res = await fetch(`${OPT_API}${path}`, body ? {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : undefined);
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok || !data) throw new Error((data && data.error) || `HTTP ${res.status}`);
    return data;
}

// ---------- page ----------

// Keep the address bar in step with what is on screen, without adding history entries.
function optSyncUrl() {
    const q = new URLSearchParams();
    if (optState.symbol) q.set("symbol", optState.symbol);
    if (optState.expiry) q.set("expiry", optState.expiry);
    if (optState.tab && optState.tab !== "chain") q.set("tab", optState.tab);
    history.replaceState(null, "", `${location.pathname}?${q}`);
    const back = document.getElementById("opt-back");
    if (back && optState.symbol) back.href = `/app?symbol=${encodeURIComponent(optState.symbol)}`;
    document.title = `${optState.symbol ? optState.symbol + " options" : "Options"} · Tradeski`;
}

function initOptions() {
    const page = document.getElementById("options-page");
    if (!page) return;
    const quick = document.getElementById("opt-quick");
    quick.innerHTML = OPT_QUICK.map(s => `<button class="opt-quick-btn" data-symbol="${s}">${s}</button>`).join("");
    quick.addEventListener("click", e => {
        const b = e.target.closest("[data-symbol]");
        if (b) optLoadSymbol(b.dataset.symbol);
    });

    document.querySelectorAll(".opt-tab").forEach(b => b.addEventListener("click", () => optShowTab(b.dataset.tab)));
    const symInput = document.getElementById("opt-symbol");
    const go = () => {
        const sym = symInput.value.trim().toUpperCase();
        if (sym) optLoadSymbol(sym);
    };
    document.getElementById("opt-symbol-go").addEventListener("click", go);
    symInput.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
    document.getElementById("opt-expiry").addEventListener("change", e => optLoadChain(e.target.value));

    ["opt-f-window", "opt-f-side"].forEach(id =>
        document.getElementById(id).addEventListener("change", optRenderChain));
    ["opt-f-dmin", "opt-f-dmax", "opt-f-oi", "opt-f-vol", "opt-f-spread"].forEach(id =>
        document.getElementById(id).addEventListener("input", optRenderChain));
    document.getElementById("opt-f-reset").addEventListener("click", () => {
        ["opt-f-dmin", "opt-f-dmax", "opt-f-oi", "opt-f-vol", "opt-f-spread"].forEach(id => {
            document.getElementById(id).value = "";
        });
        document.getElementById("opt-f-window").value = "10";
        document.getElementById("opt-f-side").value = "both";
        optRenderChain();
    });
    document.getElementById("opt-chain-body").addEventListener("click", optChainClick);

    const presetSel = document.getElementById("opt-preset");
    presetSel.innerHTML = `<option value="">Choose a strategy…</option>` +
        OPT_PRESETS.map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
    presetSel.addEventListener("change", () => { if (presetSel.value) optBuildPreset(presetSel.value); });
    document.getElementById("opt-add-leg").addEventListener("click", () => {
        const c = optState.chain;
        if (!c) return;
        const atm = c.calls.reduce((a, b) => Math.abs(b.strike - c.spot) < Math.abs(a.strike - c.spot) ? b : a);
        optState.legs.push({ type: "call", qty: 1, strike: atm.strike });
        optState.preset = null;
        optAnalyze();
    });
    document.getElementById("opt-clear-legs").addEventListener("click", () => {
        optState.legs = [];
        optState.analysis = null;
        presetSel.value = "";
        optRenderStrategy();
    });
    document.getElementById("opt-legs").addEventListener("change", optLegEdit);
    document.getElementById("opt-legs").addEventListener("click", e => {
        const btn = e.target.closest("[data-remove]");
        if (!btn) return;
        optState.legs.splice(Number(btn.dataset.remove), 1);
        optState.preset = null;
        optState.legs.length ? optAnalyze() : (optState.analysis = null, optRenderStrategy());
    });
    const days = document.getElementById("opt-days");
    days.addEventListener("input", () => {
        optState.daysForward = Number(days.value);
        document.getElementById("opt-days-label").textContent = optDaysLabel();
    });
    days.addEventListener("change", () => { if (optState.legs.length) optAnalyze(); });
    document.getElementById("opt-ask-ski").addEventListener("click", optAskSki);

    document.getElementById("opt-scan-symbols").value = OPT_SCAN_DEFAULT;
    document.getElementById("opt-scan-run").addEventListener("click", optRunScan);
    document.querySelectorAll("#opt-scan-table th.sortable").forEach(th =>
        th.addEventListener("click", () => {
            const s = optState.scanSort;
            s.dir = s.col === th.dataset.col ? -s.dir : -1;
            s.col = th.dataset.col;
            optRenderScan();
        }));
    document.getElementById("opt-scan-body").addEventListener("click", optScanClick);

    const start = optParseQuery(location.search);
    optState.wantExpiry = start.expiry;
    optShowTab(start.tab);
    optLoadSymbol(start.symbol);
}

function optShowTab(tab) {
    optState.tab = tab;
    document.querySelectorAll(".opt-tab").forEach(b => {
        const on = b.dataset.tab === tab;
        b.classList.toggle("active", on);
        b.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".opt-pane").forEach(p => { p.hidden = p.id !== `opt-pane-${tab}`; });
    optSyncUrl();
    if (tab === "strategy" && optState.analysis) optDrawPayoff(optState.analysis);
    if (tab === "chain" && optState.chain) optDrawSmile(optState.chain);
}

function optStatus(msg, isError) {
    const el = document.getElementById("opt-status");
    el.textContent = msg || "";
    el.classList.toggle("opt-error", !!isError);
}

async function optLoadSymbol(sym) {
    optState.symbol = sym;
    document.querySelectorAll(".opt-quick-btn").forEach(b => b.classList.toggle("active", b.dataset.symbol === sym));
    optState.chain = null;
    optState.legs = [];
    optState.analysis = null;
    document.getElementById("opt-symbol").value = sym;
    document.getElementById("opt-preset").value = "";
    optRenderStrategy();
    const sel = document.getElementById("opt-expiry");
    sel.innerHTML = "<option>Loading…</option>";
    optStatus(`Loading ${sym} options…`);
    try {
        const data = await optFetch(`/options/expirations?symbol=${encodeURIComponent(sym)}`);
        optState.expirations = data.expirations;
        if (!data.expirations.length) {
            sel.innerHTML = "";
            optStatus(`No option data came back for ${sym}. Either it has no listed options, or the data source isn't answering right now.`, true);
            optRenderChain();
            return;
        }
        sel.innerHTML = data.expirations.map(e =>
            `<option value="${e.date}">${e.date} (${e.dte}d)</option>`).join("");
        // An expiry from a shared link wins if it is still listed (only once, for the first symbol).
        const wanted = optState.wantExpiry;
        optState.wantExpiry = "";
        const expiry = wanted && data.expirations.some(e => e.date === wanted) ? wanted : data.default;
        sel.value = expiry;
        await optLoadChain(expiry);
    } catch (e) {
        sel.innerHTML = "";
        optStatus(`Options are unavailable right now (${e.message}). They need the live backend.`, true);
    }
}

async function optLoadChain(expiry) {
    const id = ++optState.reqId;
    optState.expiry = expiry;
    optSyncUrl();
    optStatus(`Loading the ${expiry} chain…`);
    document.getElementById("opt-chain-body").innerHTML =
        `<tr><td colspan="13" class="screener-loading"><div class="loading-spinner"></div> Fetching quotes…</td></tr>`;
    try {
        const chain = await optFetch(`/options/chain?symbol=${encodeURIComponent(optState.symbol)}&expiry=${expiry}`);
        if (id !== optState.reqId) return;
        optState.chain = chain;
        const days = document.getElementById("opt-days");
        days.max = Math.max(chain.dte - 1, 0);
        optState.daysForward = Math.min(optState.daysForward, Number(days.max));
        days.value = optState.daysForward;
        document.getElementById("opt-days-label").textContent = optDaysLabel();
        optStatus("");
        optRenderSummary();
        optRenderChain();
        if (optState.legs.length) {
            // Same structure at the new expiry: rebuild a preset, else keep only legs that still exist.
            if (optState.preset) optBuildPreset(optState.preset);
            else {
                const strikes = new Set(chain.calls.map(c => c.strike));
                optState.legs = optState.legs.filter(l => l.type === "stock" || strikes.has(l.strike));
                optState.legs.length ? optAnalyze() : (optState.analysis = null, optRenderStrategy());
            }
        }
    } catch (e) {
        if (id !== optState.reqId) return;
        optStatus(`Could not load the chain: ${e.message}`, true);
        document.getElementById("opt-chain-body").innerHTML = "";
    }
}

// The recorded IV history is a static file deployed with the site, so reading
// it costs the backend nothing.
async function optLoadIvHistory() {
    if (optState.ivHistory !== undefined) return;
    try {
        const res = await fetch("/data/iv_history.json", { cache: "no-cache" });
        optState.ivHistory = res.ok ? await res.json() : null;
    } catch (_) {
        optState.ivHistory = null;
    }
    if (optState.chain) optRenderSummary();
}

function optIvRankStat(c) {
    const h = optState.ivHistory;
    const rows = h && h.symbols ? h.symbols[c.symbol || optState.symbol] : null;
    if (!rows || !c.atm_iv) return "";
    const today = new Date().toISOString().slice(0, 10);
    const r = optIvRank(rows, c.atm_iv, today, OPT_IV_MIN_DAYS);
    if (!r.n) return "";
    const range = `between ${optPct(r.low)} and ${optPct(r.high)}`;
    if (r.pct === null) {
        return `<div class="opt-stat" title="Tradeski records the ATM IV after each close; a percentile needs ${OPT_IV_MIN_DAYS} days">
            <span class="opt-stat-label">IV percentile</span>
            <span class="opt-stat-val opt-dim">${r.n} of ${OPT_IV_MIN_DAYS} days recorded</span></div>`;
    }
    return `<div class="opt-stat" title="Share of the ${r.n} daily readings since ${r.since} below today's ATM IV (they ranged ${range}). A short history, not a full year.">
        <span class="opt-stat-label">IV percentile (${r.n}d)</span>
        <span class="opt-stat-val">${r.pct}th</span></div>`;
}

function optRenderSummary() {
    const c = optState.chain;
    const el = document.getElementById("opt-summary");
    if (!c) { el.innerHTML = ""; return; }
    optLoadIvHistory();
    const movePct = c.expected_move ? (c.expected_move / c.spot * 100).toFixed(1) : null;
    const ivVsHv = c.atm_iv && c.realized_vol_30d
        ? (c.atm_iv > c.realized_vol_30d * 1.15 ? "above" : c.atm_iv < c.realized_vol_30d * 0.85 ? "below" : "close to")
        : null;
    const closed = c.market_state && c.market_state !== "REGULAR";
    el.innerHTML = `
        <div class="opt-stat"><span class="opt-stat-label">${escapeHtml(c.symbol || optState.symbol)}</span>
            <span class="opt-stat-val">$${c.spot.toFixed(2)}</span></div>
        <div class="opt-stat" title="Implied volatility of the at-the-money call and put, averaged">
            <span class="opt-stat-label">ATM implied vol</span><span class="opt-stat-val">${optPct(c.atm_iv)}</span></div>
        <div class="opt-stat" title="Annualised volatility of the last 30 daily closes">
            <span class="opt-stat-label">30-day realised vol</span><span class="opt-stat-val">${optPct(c.realized_vol_30d)}</span></div>
        <div class="opt-stat" title="One standard deviation, from the ATM implied vol: about a 68% range under the model">
            <span class="opt-stat-label">Expected move by ${c.expiry}</span>
            <span class="opt-stat-val">${c.expected_move ? `±$${c.expected_move.toFixed(2)} (${movePct}%)` : "—"}</span></div>
        <div class="opt-stat" title="Put volume ÷ call volume, and put open interest ÷ call open interest">
            <span class="opt-stat-label">Put/call (vol · OI)</span>
            <span class="opt-stat-val">${c.put_call_volume ?? "—"} · ${c.put_call_oi ?? "—"}</span></div>
        ${optIvRankStat(c)}
        <p class="opt-note">${ivVsHv ? `Options are pricing volatility ${ivVsHv} what the stock has actually done lately. ` : ""}
            ${c.source === "end_of_day"
                ? `These are <strong>end-of-day quotes</strong> saved at ${escapeHtml((c.quotes_as_of || "").slice(0, 10))}: the live option feed doesn't answer this server, so the chain updates once a day, after the close.`
                : `Quotes are delayed about 15 minutes${closed ? "; the market is closed, so these are the last session's" : ""}.`}
            IV and Greeks are computed from each bid/ask midpoint with Black-Scholes, at a ${optPct(c.rate, 2)}
            interest rate (${escapeHtml(c.rate_source || "")}).</p>`;
}

function optFilters() {
    const w = document.getElementById("opt-f-window").value;
    return {
        windowPct: w === "all" ? null : Number(w),
        side: document.getElementById("opt-f-side").value,
        deltaMin: optNum(document.getElementById("opt-f-dmin").value),
        deltaMax: optNum(document.getElementById("opt-f-dmax").value),
        minOi: optNum(document.getElementById("opt-f-oi").value),
        minVol: optNum(document.getElementById("opt-f-vol").value),
        maxSpread: optNum(document.getElementById("opt-f-spread").value),
    };
}

function optCells(c, side) {
    if (!c) return `<td class="opt-empty" colspan="6"></td>`;
    const q = (v, cls, act) => v === null || v === undefined ? `<td class="${cls}">—</td>`
        : `<td class="${cls} opt-quote" data-side="${side}" data-strike="${c.strike}" data-act="${act}"
              title="${act === "buy" ? "Buy" : "Sell"} 1 at $${v.toFixed(2)}">${v.toFixed(2)}</td>`;
    const iv = `<td class="opt-num" title="IV from ${escapeHtml(c.iv_source || "no quote")}">${optPct(c.iv)}</td>`;
    const delta = `<td class="opt-num">${c.delta === null ? "—" : c.delta.toFixed(2)}</td>`;
    const vol = `<td class="opt-num opt-dim">${c.volume.toLocaleString()}</td>`;
    const oi = `<td class="opt-num opt-dim">${c.open_interest.toLocaleString()}</td>`;
    const bid = q(c.bid, "opt-num opt-bid", "sell");
    const ask = q(c.ask, "opt-num opt-ask", "buy");
    return side === "call" ? oi + vol + iv + delta + bid + ask : bid + ask + delta + iv + vol + oi;
}

function optRenderChain() {
    const body = document.getElementById("opt-chain-body");
    const count = document.getElementById("opt-chain-count");
    const c = optState.chain;
    if (!c) { body.innerHTML = ""; count.textContent = ""; return; }
    const rows = optChainRows(c, optFilters());
    count.textContent = `${rows.length} strike${rows.length === 1 ? "" : "s"}`;
    if (!rows.length) {
        body.innerHTML = `<tr><td colspan="13" class="feed-empty">No contracts match the filters</td></tr>`;
        return;
    }
    let spotDone = false;
    body.innerHTML = rows.map(r => {
        let line = "";
        if (!spotDone && r.strike >= c.spot) {
            spotDone = true;
            line = `<tr class="opt-spot-row"><td colspan="13">Stock $${c.spot.toFixed(2)}</td></tr>`;
        }
        const itmC = r.strike < c.spot ? " opt-itm-call" : "";
        const itmP = r.strike > c.spot ? " opt-itm-put" : "";
        return line + `<tr class="opt-row${itmC}${itmP}">${optCells(r.call, "call")}
            <td class="opt-strike">${r.strike}</td>${optCells(r.put, "put")}</tr>`;
    }).join("") + (spotDone ? "" : `<tr class="opt-spot-row"><td colspan="13">Stock $${c.spot.toFixed(2)}</td></tr>`);
    if (optState.tab === "chain") optDrawSmile(c);
}

function optPlotTheme(extra) {
    const font = { color: "#9BA2AD", size: 11, family: "-apple-system, BlinkMacSystemFont, Inter, 'Segoe UI', system-ui, sans-serif" };
    return Object.assign({
        paper_bgcolor: "#1C1E22", plot_bgcolor: "#1C1E22", font,
        margin: { l: 56, r: 16, t: 12, b: 36 },
        xaxis: { gridcolor: "rgba(255,255,255,0.05)", zeroline: false, tickfont: font },
        yaxis: { gridcolor: "rgba(255,255,255,0.05)", zeroline: false, tickfont: font },
        showlegend: false, hovermode: "x unified",
        hoverlabel: { bgcolor: "#111214", bordercolor: "#2A2D33", font: { color: "#E5E7EB" } },
    }, extra || {});
}

// IV by strike, using the out-of-the-money side at each strike (puts below the
// spot, calls above): in-the-money quotes are mostly intrinsic value, so their
// IV is noisy.
function optDrawSmile(c) {
    const el = document.getElementById("opt-smile");
    if (!el || typeof Plotly === "undefined") return;
    const pts = [...c.puts.filter(p => p.strike < c.spot), ...c.calls.filter(x => x.strike >= c.spot)]
        .filter(x => x.iv && x.iv_source === "mid" && Math.abs(x.strike / c.spot - 1) < 0.3);
    if (pts.length < 3) { el.innerHTML = `<div class="feed-empty">Not enough quotes to draw the volatility curve</div>`; return; }
    Plotly.react(el, [{
        x: pts.map(p => p.strike), y: pts.map(p => p.iv * 100), mode: "lines+markers", type: "scatter",
        line: { color: "#60A5FA", width: 2 }, marker: { size: 4 },
        hovertemplate: "Strike %{x}<br>IV %{y:.1f}%<extra></extra>",
    }], optPlotTheme({
        yaxis: { title: { text: "IV %", font: { size: 11 } }, gridcolor: "rgba(255,255,255,0.05)", zeroline: false },
        shapes: [{ type: "line", x0: c.spot, x1: c.spot, yref: "paper", y0: 0, y1: 1,
                   line: { color: "rgba(255,255,255,0.35)", width: 1, dash: "dot" } }],
    }), { responsive: true, displayModeBar: false });
}

function optChainClick(e) {
    const cell = e.target.closest(".opt-quote");
    if (!cell) return;
    optState.legs.push({ type: cell.dataset.side, qty: cell.dataset.act === "buy" ? 1 : -1,
                         strike: Number(cell.dataset.strike) });
    optState.preset = null;
    document.getElementById("opt-preset").value = "";
    optShowTab("strategy");
    optAnalyze();
}

// ---------- strategy builder ----------

async function optBuildPreset(preset) {
    if (!optState.chain) return;
    optState.preset = preset;
    await optAnalyze({ preset });
}

async function optAnalyze(extra) {
    if (!optState.chain) return;
    const id = ++optState.reqId;
    const body = { symbol: optState.symbol, expiry: optState.expiry, days_forward: optState.daysForward || null };
    if (extra && extra.preset) body.preset = extra.preset;
    else body.legs = optState.legs;
    document.getElementById("opt-strategy-msg").textContent = "Calculating…";
    try {
        const res = await optFetch("/options/strategy", body);
        if (id !== optState.reqId) return;
        optState.analysis = res;
        optState.legs = res.legs.map(l => ({ type: l.type, qty: l.qty, strike: l.strike }));
        document.getElementById("opt-strategy-msg").textContent = "";
    } catch (e) {
        if (id !== optState.reqId) return;
        document.getElementById("opt-strategy-msg").textContent = optOffline()
            ? "The strategy builder needs the live backend, which is asleep right now. The chain is from the offline snapshot."
            : e.message;
    }
    optRenderStrategy();
}

function optDaysLabel() {
    const d = optState.daysForward;
    return d ? `in ${d} day${d === 1 ? "" : "s"}` : "today only";
}

function optRenderStrategy() {
    const a = optState.analysis;
    const legsEl = document.getElementById("opt-legs");
    const c = optState.chain;
    const strikes = c ? [...new Set([...c.calls, ...c.puts].map(x => x.strike))].sort((x, y) => x - y) : [];
    const priced = a ? a.legs : [];
    legsEl.innerHTML = optState.legs.length ? optState.legs.map((l, i) => {
        const p = priced[i];
        const strikeSel = l.type === "stock" ? `<span class="opt-dim">—</span>` :
            `<select class="filter-select opt-leg-strike" data-i="${i}">${strikes.map(s =>
                `<option value="${s}"${s === l.strike ? " selected" : ""}>${s}</option>`).join("")}</select>`;
        return `<tr>
            <td><select class="filter-select opt-leg-act" data-i="${i}">
                <option value="buy"${l.qty > 0 ? " selected" : ""}>Buy</option>
                <option value="sell"${l.qty < 0 ? " selected" : ""}>Sell</option></select></td>
            <td><input type="number" class="filter-input opt-leg-qty" data-i="${i}" min="1" max="100" step="1"
                       value="${Math.abs(l.qty)}" aria-label="Quantity"></td>
            <td><select class="filter-select opt-leg-type" data-i="${i}">
                ${["call", "put", "stock"].map(t => `<option value="${t}"${t === l.type ? " selected" : ""}>${
                    t === "stock" ? "100 shares" : t}</option>`).join("")}</select></td>
            <td>${strikeSel}</td>
            <td class="opt-num">${p ? "$" + p.price.toFixed(2) : "—"}</td>
            <td class="opt-num opt-dim">${p && p.iv ? optPct(p.iv) : "—"}</td>
            <td><button class="btn-icon" data-remove="${i}" aria-label="Remove leg">✕</button></td></tr>`;
    }).join("") : `<tr><td colspan="7" class="feed-empty">Pick a strategy above, or click a bid (sell) or ask (buy) in the chain.</td></tr>`;

    const stats = document.getElementById("opt-stats");
    const sum = document.getElementById("opt-strategy-summary");
    document.getElementById("opt-ask-ski").hidden = !a;
    if (!a) {
        stats.innerHTML = "";
        sum.textContent = "";
        const chart = document.getElementById("opt-payoff");
        if (typeof Plotly !== "undefined") Plotly.purge(chart);
        chart.innerHTML = "";
        return;
    }
    const g = a.greeks;
    const stat = (label, val, title, cls) =>
        `<div class="opt-stat"${title ? ` title="${title}"` : ""}><span class="opt-stat-label">${label}</span>
         <span class="opt-stat-val ${cls || ""}">${val}</span></div>`;
    stats.innerHTML =
        stat(a.net_debit >= 0 ? "Net cost" : "Net credit", optMoney(Math.abs(a.net_debit)), "At bid/ask midpoints") +
        stat("Max profit", a.unlimited_profit ? "Unlimited" : optMoney(a.max_profit, true), "", "positive") +
        stat("Max loss", a.unlimited_loss ? "Unlimited" : optMoney(a.max_loss, true), "", "negative") +
        stat("Break-even", a.breakevens.length ? a.breakevens.map(b => "$" + b.toFixed(2)).join(" · ") : "—") +
        stat("Chance of profit", optPct(a.prob_profit, 0),
             "At expiry, from a lognormal at the ATM implied vol: what option prices imply, not a forecast") +
        stat("Reward / risk", a.return_on_risk === null ? "—" : a.return_on_risk.toFixed(2) + "×",
             "Max profit ÷ max loss") +
        stat("Delta", `${g.delta.toFixed(0)} sh`, "Moves like this many shares of the stock") +
        stat("Theta", `${optMoney(g.theta, true)}/day`, "P/L from one day passing, all else equal") +
        stat("Vega", `${optMoney(g.vega, true)}/vol pt`, "P/L if implied vol rises one percentage point") +
        stat("Spread cost", optMoney(a.spread_cost),
             "Extra paid if you buy at the ask and sell at the bid instead of the midpoint");
    sum.textContent = a.summary;
    if (optState.tab === "strategy") optDrawPayoff(a);
}

function optLegEdit(e) {
    const i = Number(e.target.dataset.i);
    const leg = optState.legs[i];
    if (!leg) return;
    if (e.target.classList.contains("opt-leg-act")) leg.qty = Math.abs(leg.qty) * (e.target.value === "buy" ? 1 : -1);
    if (e.target.classList.contains("opt-leg-qty")) {
        const n = Math.max(1, Math.min(100, Math.round(Number(e.target.value) || 1)));
        leg.qty = n * Math.sign(leg.qty || 1);
    }
    if (e.target.classList.contains("opt-leg-type")) {
        leg.type = e.target.value;
        if (leg.type === "stock") leg.strike = null;
        else if (leg.strike === null) leg.strike = optState.chain.calls.reduce((a, b) =>
            Math.abs(b.strike - optState.chain.spot) < Math.abs(a.strike - optState.chain.spot) ? b : a).strike;
    }
    if (e.target.classList.contains("opt-leg-strike")) leg.strike = Number(e.target.value);
    optState.preset = null;
    document.getElementById("opt-preset").value = "";
    optAnalyze();
}

function optDrawPayoff(a) {
    const el = document.getElementById("opt-payoff");
    if (!el || typeof Plotly === "undefined") return;
    const cv = a.curves;
    const pos = cv.expiry.map(v => (v > 0 ? v : 0));
    const neg = cv.expiry.map(v => (v < 0 ? v : 0));
    const traces = [
        { x: cv.prices, y: pos, type: "scatter", mode: "none", fill: "tozeroy", fillcolor: "rgba(22,163,74,0.18)", hoverinfo: "skip", showlegend: false },
        { x: cv.prices, y: neg, type: "scatter", mode: "none", fill: "tozeroy", fillcolor: "rgba(239,68,68,0.18)", hoverinfo: "skip", showlegend: false },
        { x: cv.prices, y: cv.expiry, name: `At expiry (${a.expiry})`, type: "scatter", mode: "lines",
          line: { color: "#E5E7EB", width: 2 }, hovertemplate: "At expiry: %{y:$,.0f}<extra></extra>" },
        { x: cv.prices, y: cv.today, name: "Today", type: "scatter", mode: "lines",
          line: { color: "#60A5FA", width: 1.5, dash: "dash" }, hovertemplate: "Today: %{y:$,.0f}<extra></extra>" },
    ];
    if (cv.at_date) traces.push({ x: cv.prices, y: cv.at_date, name: `In ${cv.at_date_days} days`, type: "scatter",
        mode: "lines", line: { color: "#F59E0B", width: 1.5, dash: "dot" },
        hovertemplate: `In ${cv.at_date_days}d: %{y:$,.0f}<extra></extra>` });
    const shapes = [
        { type: "line", xref: "x", x0: a.spot, x1: a.spot, yref: "paper", y0: 0, y1: 1,
          line: { color: "rgba(255,255,255,0.35)", width: 1, dash: "dot" } },
        { type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: "rgba(255,255,255,0.25)", width: 1 } },
    ];
    Plotly.react(el, traces, optPlotTheme({
        showlegend: true, legend: { orientation: "h", y: 1.08, x: 0, font: { size: 11, color: "#9BA2AD" } },
        margin: { l: 64, r: 16, t: 28, b: 40 },
        xaxis: { title: { text: `${a.symbol} price`, font: { size: 11 } }, gridcolor: "rgba(255,255,255,0.05)",
                 zeroline: false, tickprefix: "$", hoverformat: "$.2f" },
        yaxis: { title: { text: "Profit / loss", font: { size: 11 } }, gridcolor: "rgba(255,255,255,0.05)",
                 zeroline: false, tickprefix: "$", tickformat: ",.0f" },
        shapes,
        annotations: [{ x: a.spot, y: 1, yref: "paper", text: "now", showarrow: false, yanchor: "bottom",
                        font: { size: 10, color: "#9BA2AD" } }],
    }), { responsive: true, displayModeBar: false });
}

// Ski lives on the dashboard: hand the question over and go there; dashboard.js
// opens Ski with it filled in (not sent, so the user can edit it first).
function optAskSki() {
    const a = optState.analysis;
    if (!a) return;
    const legs = a.legs.map(l => optLegText(l, a.symbol)).join(", ");
    try {
        sessionStorage.setItem(OPT_SKI_KEY, `I'm looking at this ${a.symbol} options position expiring ${a.expiry}: ` +
            `${legs}. Explain how it makes and loses money, and what the main risks are.`);
    } catch (_) { /* storage blocked: still go to the dashboard */ }
    location.href = `/app?symbol=${encodeURIComponent(a.symbol)}`;
}

// ---------- scanner ----------

async function optRunScan() {
    const kind = document.getElementById("opt-scan-kind").value;
    const params = new URLSearchParams({
        kind,
        symbols: document.getElementById("opt-scan-symbols").value.replace(/\s+/g, ""),
        max_delta: document.getElementById("opt-scan-delta").value || "0.30",
        min_dte: document.getElementById("opt-scan-dmin").value || "20",
        max_dte: document.getElementById("opt-scan-dmax").value || "50",
        min_oi: document.getElementById("opt-scan-oi").value || "100",
        max_spread: document.getElementById("opt-scan-spread").value || "10",
    });
    const body = document.getElementById("opt-scan-body");
    body.innerHTML = `<tr><td colspan="11" class="screener-loading"><div class="loading-spinner"></div>
        Scanning chains (the first run can take a while)…</td></tr>`;
    document.getElementById("opt-scan-skipped").textContent = "";
    try {
        optState.scan = await optFetch(`/options/scan?${params}`);
        optRenderScan();
    } catch (e) {
        body.innerHTML = `<tr><td colspan="11" class="feed-empty">${optOffline()
            ? "The scanner needs the live backend, which is asleep right now."
            : `Scan failed: ${escapeHtml(e.message)}`}</td></tr>`;
    }
}

function optRenderScan() {
    const s = optState.scan;
    const body = document.getElementById("opt-scan-body");
    if (!s) return;
    const { col, dir } = optState.scanSort;
    const rows = [...s.results].sort((a, b) =>
        typeof a[col] === "string" ? dir * a[col].localeCompare(b[col]) : dir * ((a[col] ?? -Infinity) - (b[col] ?? -Infinity)));
    document.querySelectorAll("#opt-scan-table th.sortable").forEach(th => {
        const on = th.dataset.col === col;
        th.classList.toggle("sorted", on);
        th.querySelector(".sort-icon").textContent = on ? (dir === 1 ? "↑" : "↓") : "↕";
    });
    body.innerHTML = rows.length ? rows.map((r, i) => `
        <tr class="screener-row opt-scan-row" data-i="${s.results.indexOf(r)}" title="Open in the strategy builder">
            <td class="sc-symbol">${escapeHtml(r.symbol)}</td>
            <td class="opt-num">${r.expiry} <span class="opt-dim">(${r.dte}d)</span></td>
            <td class="opt-num">${r.strike}</td>
            <td class="opt-num">${r.delta.toFixed(2)}</td>
            <td class="opt-num">${optPct(r.iv)}</td>
            <td class="opt-num">${optMoney(r.premium)}</td>
            <td class="opt-num">${optMoney(r.capital)}</td>
            <td class="opt-num">${r.return_pct.toFixed(2)}%</td>
            <td class="opt-num positive">${r.annualized_pct.toFixed(1)}%</td>
            <td class="opt-num">${r.breakeven === null ? "—" : "$" + r.breakeven.toFixed(2)}</td>
            <td class="opt-num">${optPct(r.prob_profit, 0)}</td>
        </tr>`).join("")
        : `<tr><td colspan="11" class="feed-empty">Nothing passes these filters. Try a wider delta, DTE or spread.</td></tr>`;
    document.getElementById("opt-scan-skipped").textContent = s.skipped.length
        ? "Skipped: " + s.skipped.map(x => `${x.symbol} (${x.skipped})`).join(", ") : "";
}

async function optScanClick(e) {
    const tr = e.target.closest(".opt-scan-row");
    if (!tr || !optState.scan) return;
    const r = optState.scan.results[Number(tr.dataset.i)];
    if (!r) return;
    if (optState.symbol !== r.symbol) await optLoadSymbol(r.symbol);
    if (optState.expiry !== r.expiry) {
        document.getElementById("opt-expiry").value = r.expiry;
        await optLoadChain(r.expiry);
    }
    optState.legs = r.kind === "covered_call"
        ? [{ type: "stock", qty: 1, strike: null }, { type: "call", qty: -1, strike: r.strike }]
        : [{ type: "put", qty: -1, strike: r.strike }];
    optState.preset = null;
    document.getElementById("opt-preset").value = "";
    optShowTab("strategy");
    optAnalyze();
}

document.addEventListener("DOMContentLoaded", initOptions);
