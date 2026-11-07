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

// What each preset is for, in plain words, shown on its card.
const OPT_PRESET_INFO = {
    long_call:        { view: "Bullish",            kind: "bull",  text: "Profit if the stock rises past the strike plus what you paid.", risk: "Most you can lose: what you pay" },
    long_put:         { view: "Bearish",            kind: "bear",  text: "Profit if the stock falls below the strike minus what you paid.", risk: "Most you can lose: what you pay" },
    bull_call_spread: { view: "Moderately bullish", kind: "bull",  text: "Buy a call, sell a higher one. Cheaper than a call; profit is capped.", risk: "Limited risk, limited reward" },
    bear_put_spread:  { view: "Moderately bearish", kind: "bear",  text: "Buy a put, sell a lower one. Cheaper than a put; profit is capped.", risk: "Limited risk, limited reward" },
    covered_call:     { view: "Neutral to bullish", kind: "neutral", text: "Own 100 shares and sell a call: collect income, give up gains above the strike.", risk: "Risk: the stock falling" },
    cash_secured_put: { view: "Neutral to bullish", kind: "neutral", text: "Sell a put with cash set aside: get paid now, maybe buy the stock cheaper.", risk: "Risk: buying the stock as it falls" },
    iron_condor:      { view: "Neutral",            kind: "neutral", text: "Collect premium if the stock stays inside a range until expiry.", risk: "Limited risk, limited reward" },
    long_straddle:    { view: "Big move, either way", kind: "move", text: "Buy a call and a put at one strike: profit from a large move up or down.", risk: "Most you can lose: both premiums" },
    long_strangle:    { view: "Big move, either way", kind: "move", text: "Like a straddle but cheaper; the stock has to move further.", risk: "Most you can lose: both premiums" },
};
const OPT_INTRO_KEY = "tradeski-options-intro-hidden";

const OPT_SCAN_DEFAULT = "AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, JPM, SPY, QQQ";
const OPT_API = "https://tradeski.onrender.com";
// Quick picks: the symbols whose closing chains are always saved (see capture_snapshot.py).
const OPT_QUICK = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ", "JPM", "SOFI", "RDW"];
const OPT_TABS = ["chain", "strategy", "compare", "scan", "paper"];
const OPT_PAPER_KEY = "tradeski-paper-trades";
const OPT_PAPER_MAX = 50;
const OPT_COMPARE_COLORS = ["#60A5FA", "#F59E0B", "#C084FC"];
const OPT_COMPARE_DEFAULT = ["long_call", "bull_call_spread", "covered_call"];
const OPT_COMPARE_MAX = 3;
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
    ivShift: 0,             // volatility points added to every option's IV before expiry
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
// Which strategies to compare when the list (re)loads: the user's picks if
// still available, else the top three for a target, else a starter set.
function optCompareSelection(rows, previous, target) {
    const have = new Set(rows.map(r => r.preset));
    const kept = (previous || []).filter(p => have.has(p));
    if (kept.length) return kept.slice(0, OPT_COMPARE_MAX);
    if (target) return rows.filter(r => r.pnl_at_target > 0).slice(0, OPT_COMPARE_MAX).map(r => r.preset);
    return OPT_COMPARE_DEFAULT.filter(p => have.has(p));
}

// The price window for the comparison chart: spot ± max(2.5 expected moves, 12%), capped at ±40%,
// and always wide enough to show the target.
function optCompareWindow(spot, expectedMove, target) {
    const w = Math.min(Math.max(expectedMove ? 2.5 * expectedMove / spot : 0, 0.12), 0.4);
    let lo = spot * (1 - w), hi = spot * (1 + w);
    if (target) { lo = Math.min(lo, target * 0.95); hi = Math.max(hi, target * 1.05); }
    return [lo, hi];
}

// The part of a curve inside [lo, hi], with the end points interpolated onto the edges.
function optClipCurve(xs, ys, lo, hi) {
    const at = x => {
        for (let i = 1; i < xs.length; i++) {
            if (xs[i] >= x) return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / ((xs[i] - xs[i - 1]) || 1);
        }
        return ys[ys.length - 1];
    };
    const x = [lo], y = [at(lo)];
    xs.forEach((v, i) => { if (v > lo && v < hi) { x.push(v); y.push(ys[i]); } });
    x.push(hi); y.push(at(hi));
    return { x, y };
}

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

// ---- paper trades: pure helpers ----

// A saved trade from a strategy analysis (prices are the entry mids).
function optPaperFrom(analysis, presetName, now) {
    return {
        id: `${now.getTime().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
        symbol: analysis.symbol, expiry: analysis.expiry, name: presetName || "Custom",
        legs: analysis.legs.map(l => ({ type: l.type, qty: l.qty, strike: l.strike, price: l.price })),
        entry: analysis.net_debit, spot: analysis.spot, saved_at: now.toISOString(),
    };
}

// How much of a capped best case is locked in: {pct, close: pct >= 50%}, or null
// when the profit has no cap or isn't known.
function optPaperProgress(pnl, maxProfit) {
    if (maxProfit === null || maxProfit === undefined || !(maxProfit > 0)) return null;
    const pct = pnl / maxProfit;
    return { pct, close: pct >= 0.5 };
}

// Newest first, at most OPT_PAPER_MAX.
function optPaperAdd(list, trade) {
    return [trade, ...(list || []).filter(t => t.id !== trade.id)].slice(0, OPT_PAPER_MAX);
}

// P/L of closing now: today's value of the legs (net debit to open them now)
// minus what they cost when saved. Works for debits and credits alike.
function optPaperPnl(entry, nowDebit) {
    const pnl = Math.round((nowDebit - entry) * 100) / 100;
    return { pnl, pct: entry > 0 ? pnl / entry : null };
}

function optPaperLoad() {
    try {
        const list = JSON.parse(localStorage.getItem(OPT_PAPER_KEY) || "[]");
        return Array.isArray(list) ? list : [];
    } catch (_) { return []; }
}

function optPaperStore(list) {
    try { localStorage.setItem(OPT_PAPER_KEY, JSON.stringify(list)); } catch (_) { /* storage full or blocked */ }
    const n = document.getElementById("paper-count");
    if (n) n.textContent = list.length ? String(list.length) : "";
}

// Why a priced leg is hard to trade near its mid, or "" if it isn't:
// a bid-ask spread over 10% of the mid, or fewer than 100 contracts open.
const OPT_THIN_SPREAD = 10;
const OPT_THIN_OI = 100;
function optThinReason(leg, chain) {
    if (!leg || leg.type === "stock" || !chain) return "";
    const side = leg.type === "call" ? chain.calls : chain.puts;
    const c = (side || []).find(x => x.strike === leg.strike);
    if (!c) return "";
    const why = [];
    if (c.spread_pct === null || c.spread_pct === undefined) why.push("no two-sided quote");
    else if (c.spread_pct > OPT_THIN_SPREAD) why.push(`bid-ask spread ${c.spread_pct.toFixed(0)}% of the price`);
    if (c.open_interest < OPT_THIN_OI) why.push(`only ${c.open_interest} contracts open`);
    return why.join("; ");
}

// The time-decay verdict: does waiting help or hurt if the stock stays put?
function optDecayNote(decay, thetaPerDay, symbol, spot) {
    if (!decay || decay.length < 2) return "";
    const total = decay[decay.length - 1].pnl - decay[0].pnl;
    const day = optMoney(Math.abs(thetaPerDay));
    const at = `if ${symbol} stays at $${spot.toFixed(2)}`;
    if (Math.abs(total) < 1) return `Time barely matters here: ${at}, the value hardly changes by expiry.`;
    return total > 0
        ? `Time is on your side: ${at}, this position gains about ${optMoney(total)} by expiry (about ${day} a day now).`
        : `Time works against you: ${at}, this position loses about ${optMoney(-total)} by expiry (about ${day} a day now).`;
}

// The IV slider's label: 0 -> "unchanged", -15 -> "15 points lower".
function optIvShiftLabel(shift) {
    if (!shift) return "unchanged";
    return `${Math.abs(shift)} point${Math.abs(shift) === 1 ? "" : "s"} ${shift < 0 ? "lower" : "higher"}`;
}

// "(IV -15)" after a line or column name when the slider is off zero.
function optIvTag(shift) {
    return shift ? ` (IV ${shift > 0 ? "+" : "−"}${Math.abs(shift)})` : "";
}

// "Jan 28, 2027" from "2027-01-28" (no time-zone shift).
function optDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

// Whole days from `today` to `iso` (both YYYY-MM-DD).
function optDaysBetween(today, iso) {
    return Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(today + "T00:00:00Z")) / 86400000);
}

// The market's expected range by expiry (one standard deviation, about 68%), or null.
function optExpectedRange(chain) {
    if (!chain || !chain.expected_move) return null;
    return { lo: chain.spot - chain.expected_move, hi: chain.spot + chain.expected_move };
}

// Where a position makes money at expiry, from analyze()'s profit_zones:
// [[348.7, null]] -> "above $348.70"; [[0, 94], [106, null]] -> "below $94.00 or above $106.00".
function optZoneText(zones) {
    if (!zones || !zones.length) return "at no price";
    const usd = v => "$" + Number(v).toFixed(2);
    return zones.map(([lo, hi]) => {
        if (lo <= 0 && hi === null) return "at any price";
        if (lo <= 0) return `below ${usd(hi)}`;
        if (hi === null) return `above ${usd(lo)}`;
        return `between ${usd(lo)} and ${usd(hi)}`;
    }).join(" or ");
}

// One leg as a sentence: "Buy 1 AAPL $340 call at $11.78 a share: you pay $1,178".
function optLegPlain(leg, symbol) {
    const n = Math.abs(leg.qty);
    const buy = leg.qty > 0;
    const total = n * 100 * leg.price;
    const money = optMoney(total);
    if (leg.type === "stock") {
        return `${buy ? "Buy" : "Sell"} ${n * 100} ${symbol} shares at $${leg.price.toFixed(2)}: ${buy ? "you pay" : "you receive"} ${money}`;
    }
    return `${buy ? "Buy" : "Sell"} ${n} ${symbol} $${leg.strike} ${leg.type}${n > 1 ? "s" : ""} at $${leg.price.toFixed(2)} a share: ` +
        `${buy ? "you pay" : "you collect"} ${money}`;
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

    const presets = document.getElementById("opt-presets");
    presets.innerHTML = OPT_PRESETS.map(([k, label]) => {
        const info = OPT_PRESET_INFO[k];
        return `<button class="opt-preset-card" data-preset="${k}" type="button">
            <span class="opt-view opt-view-${info.kind}">${escapeHtml(info.view)}</span>
            <span class="opt-preset-name">${escapeHtml(label)}</span>
            <span class="opt-preset-text">${escapeHtml(info.text)}</span>
            <span class="opt-preset-risk">${escapeHtml(info.risk)}</span></button>`;
    }).join("");
    presets.addEventListener("click", e => {
        const card = e.target.closest("[data-preset]");
        if (card) optBuildPreset(card.dataset.preset);
    });
    const intro = document.getElementById("opt-intro");
    let introHidden = false;
    try { introHidden = localStorage.getItem(OPT_INTRO_KEY) === "1"; } catch (_) { introHidden = false; }
    intro.hidden = introHidden;
    document.getElementById("opt-intro-close").addEventListener("click", () => {
        intro.hidden = true;
        try { localStorage.setItem(OPT_INTRO_KEY, "1"); } catch (_) { /* storage blocked */ }
    });
    document.querySelectorAll("[data-goto-tab]").forEach(b =>
        b.addEventListener("click", () => optShowTab(b.dataset.gotoTab)));
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
        optSetPreset(null);
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
    const iv = document.getElementById("opt-ivshift");
    iv.addEventListener("input", () => {
        optState.ivShift = Number(iv.value);
        document.getElementById("opt-ivshift-label").textContent = optIvShiftLabel(optState.ivShift);
    });
    iv.addEventListener("change", () => { if (optState.legs.length) optAnalyze(); });
    document.getElementById("opt-ivshift-crush").addEventListener("click", () => {
        iv.value = -15;
        iv.dispatchEvent(new Event("input"));
        iv.dispatchEvent(new Event("change"));
    });
    document.getElementById("opt-ask-ski").addEventListener("click", optAskSki);
    document.getElementById("opt-save-paper").addEventListener("click", optSavePaper);
    document.getElementById("paper-refresh").addEventListener("click", optRefreshPaper);
    document.getElementById("paper-table").addEventListener("click", optPaperClick);
    optPaperStore(optPaperLoad());

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
    document.getElementById("cmp-table").addEventListener("click", optCompareClick);
    document.getElementById("cmp-rank").addEventListener("click", () => optSetTarget(document.getElementById("cmp-target").value));
    document.getElementById("cmp-target").addEventListener("keydown", e => {
        if (e.key === "Enter") optSetTarget(e.target.value);
    });
    document.getElementById("cmp-clear-target").addEventListener("click", () => optSetTarget(null));
    document.getElementById("cmp-quick").addEventListener("click", e => {
        const b = e.target.closest("[data-move]");
        if (b && optState.chain) optSetTarget(optState.chain.spot * (1 + Number(b.dataset.move) / 100));
    });

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
    if (tab === "strategy" && optState.analysis) { optDrawPayoff(optState.analysis); optDrawDecay(optState.analysis); }
    if (tab === "chain" && optState.chain) optDrawSmile(optState.chain);
    if (tab === "compare") optEnsureCompare();
    if (tab === "paper") optRenderPaper();
}

// ---------- paper trades ----------

function optSavePaper() {
    const a = optState.analysis;
    if (!a) return;
    const name = optState.preset ? (OPT_PRESETS.find(([k]) => k === optState.preset) || [])[1] : null;
    const list = optPaperAdd(optPaperLoad(), optPaperFrom(a, name, new Date()));
    optPaperStore(list);
    document.getElementById("opt-strategy-msg").textContent =
        `Saved. Track it under Paper trades (${list.length} saved in this browser).`;
}

function optRenderPaper() {
    const list = optPaperLoad();
    const table = document.getElementById("paper-table");
    const today = new Date().toISOString().slice(0, 10);
    if (!list.length) {
        table.innerHTML = `<tbody><tr><td class="feed-empty">No paper trades yet. Build a strategy, then press "Save as paper trade" to
            follow how it would have done.</td></tr></tbody>`;
        document.getElementById("paper-total").textContent = "";
        return;
    }
    let total = 0, priced = 0;
    table.innerHTML = `<thead><tr><th>Position</th><th>Opened</th><th>Expiry</th><th class="opt-num">At open</th>
        <th class="opt-num">Now</th><th class="opt-num">P/L</th>
        <th title="How much of the best case you have locked in, if you closed now">Progress</th>
        <th class="opt-num" title="Chance the position ends profitable from what you paid, implied by today's option prices">Chance now</th>
        <th></th></tr></thead><tbody>${list.map(t => {
        const left = optDaysBetween(today, t.expiry);
        const expired = left < 0;
        const has = !expired && t.now !== undefined && t.now !== null;
        const r = has ? optPaperPnl(t.entry, t.now) : null;
        if (r) { total += r.pnl; priced++; }
        const legs = t.legs.map(l => optLegText(l, t.symbol)).join(", ");
        return `<tr>
            <td><span class="cmp-name">${escapeHtml(t.symbol)} · ${escapeHtml(t.name)}</span>
                <span class="paper-legs">${escapeHtml(legs)}</span></td>
            <td>${optDate(t.saved_at.slice(0, 10))}<span class="paper-sub">stock $${Number(t.spot).toFixed(2)}</span></td>
            <td>${optDate(t.expiry)}<span class="paper-sub">${expired ? "expired" : left === 0 ? "today" : left + " days left"}</span></td>
            <td class="opt-num">${t.entry >= 0 ? "paid " + optMoney(t.entry) : "collected " + optMoney(-t.entry)}</td>
            <td class="opt-num">${has ? (t.now >= 0 ? "worth " + optMoney(t.now) : "costs " + optMoney(-t.now) + " to close")
                : expired ? "—" : (t.error ? `<span class="opt-dim">${escapeHtml(t.error)}</span>` : "—")}</td>
            <td class="opt-num ${r ? (r.pnl > 0 ? "positive" : r.pnl < 0 ? "negative" : "") : ""}">${r
                ? `${optMoney(r.pnl, true)}${r.pct !== null ? `<span class="paper-sub">${r.pct >= 0 ? "+" : ""}${(r.pct * 100).toFixed(1)}%</span>` : ""}`
                : expired ? `<span class="opt-dim">Expired: the result depends on the ${optDate(t.expiry)} close</span>` : "—"}</td>
            <td class="paper-progress">${(() => {
                const pr = r ? optPaperProgress(r.pnl, t.max_profit) : null;
                if (!pr) return `<span class="opt-dim">${r && t.max_profit === null ? "no cap on profit" : "—"}</span>`;
                return `<span class="opt-meter"><span style="width:${Math.max(0, Math.min(100, pr.pct * 100))}%"></span></span>
                    <span class="paper-sub">${Math.round(pr.pct * 100)}% of max profit</span>${pr.close
                    ? `<span class="paper-take" title="A common rule of thumb for trades with capped profit">Many traders close at 50%+</span>` : ""}`;
            })()}</td>
            <td class="opt-num">${r && t.pop !== undefined && t.pop !== null ? optPct(t.pop, 0) : "—"}</td>
            <td class="paper-actions"><button class="btn-secondary" data-open="${t.id}" type="button"${expired ? " disabled" : ""}>Open</button>
                <button class="btn-icon" data-remove-paper="${t.id}" aria-label="Remove">✕</button></td></tr>`;
    }).join("")}</tbody>`;
    document.getElementById("paper-total").innerHTML = priced
        ? `Total P/L on ${priced} open trade${priced === 1 ? "" : "s"}: <strong class="${total >= 0 ? "positive" : "negative"}">${optMoney(total, true)}</strong>`
        : "";
    if (list.some(t => t.now === undefined && optDaysBetween(today, t.expiry) >= 0) && !optState.paperBusy) optRefreshPaper();
}

// Price every open trade at today's mids (three at a time).
async function optRefreshPaper() {
    if (optState.paperBusy) return;
    optState.paperBusy = true;
    const status = document.getElementById("paper-status");
    const today = new Date().toISOString().slice(0, 10);
    const list = optPaperLoad();
    const open = list.filter(t => optDaysBetween(today, t.expiry) >= 0);
    let done = 0;
    status.textContent = open.length ? `Pricing ${open.length} trade${open.length === 1 ? "" : "s"}…` : "";
    const work = open.map(t => async () => {
        try {
            const res = await optFetch("/options/strategy", { symbol: t.symbol, expiry: t.expiry,
                legs: t.legs.map(l => ({ type: l.type, qty: l.qty, strike: l.strike, price: l.price })),
                entry_prices: true });
            // Analysed as held: from the entry prices, with today's value alongside.
            t.now = res.value_now !== undefined ? res.value_now : res.net_debit;
            t.pop = res.prob_profit;
            t.max_profit = res.unlimited_profit ? null : res.max_profit;
            t.error = null;
        } catch (e) {
            t.now = null;
            t.error = optOffline() ? "needs the live backend" : "can't be priced right now";
        }
        t.checked_at = new Date().toISOString();
        status.textContent = `Priced ${++done} of ${open.length}…`;
    });
    for (let i = 0; i < work.length; i += 3) await Promise.all(work.slice(i, i + 3).map(f => f()));
    optPaperStore(list);
    optState.paperBusy = false;
    status.textContent = open.length ? `Prices as of ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "";
    if (optState.tab === "paper") optRenderPaper();
}

async function optPaperClick(e) {
    const rm = e.target.closest("[data-remove-paper]");
    if (rm) {
        optPaperStore(optPaperLoad().filter(t => t.id !== rm.dataset.removePaper));
        optRenderPaper();
        return;
    }
    const open = e.target.closest("[data-open]");
    if (!open) return;
    const t = optPaperLoad().find(x => x.id === open.dataset.open);
    if (!t) return;
    if (optState.symbol !== t.symbol) await optLoadSymbol(t.symbol);
    if (optState.expiry !== t.expiry) {
        document.getElementById("opt-expiry").value = t.expiry;
        await optLoadChain(t.expiry);
    }
    optState.legs = t.legs.map(l => ({ type: l.type, qty: l.qty, strike: l.strike }));
    optSetPreset(null);
    optShowTab("strategy");
    optAnalyze();
}

// ---------- compare & choose ----------

function optCompareKey() {
    return `${optState.symbol}|${optState.expiry}|${optState.compareTarget || ""}`;
}

function optEnsureCompare() {
    const c = optState.chain;
    if (!c) return;
    document.getElementById("cmp-sym").textContent = c.symbol || optState.symbol;
    document.getElementById("cmp-exp").textContent = optDate(c.expiry);
    const moves = [[-10, "Down 10%"], [-5, "Down 5%"], [0, "Unchanged"], [5, "Up 5%"], [10, "Up 10%"]];
    document.getElementById("cmp-quick").innerHTML = moves.map(([m, label]) =>
        `<button class="opt-quick-btn" type="button" data-move="${m}">${label}</button>`).join("");
    if (optState.compare && optState.compareKey === optCompareKey()) { optRenderCompare(); return; }
    optLoadCompare();
}

async function optLoadCompare() {
    const id = ++optState.reqId;
    const key = optCompareKey();
    document.getElementById("cmp-table").innerHTML =
        `<tbody><tr><td class="screener-loading"><div class="loading-spinner"></div> Pricing every strategy…</td></tr></tbody>`;
    try {
        const body = { symbol: optState.symbol, expiry: optState.expiry };
        if (optState.compareTarget) body.target = optState.compareTarget;
        const data = await optFetch("/options/compare", body);
        if (id !== optState.reqId) return;
        optState.compare = data;
        optState.compareKey = key;
        optState.compareSel = optCompareSelection(data.strategies, optState.compareSel, data.target);
        optRenderCompare();
    } catch (e) {
        if (id !== optState.reqId) return;
        document.getElementById("cmp-table").innerHTML = `<tbody><tr><td class="feed-empty">${optOffline()
            ? "Comparing needs the live backend, which is asleep right now." : escapeHtml(e.message)}</td></tr></tbody>`;
    }
}

function optRenderCompare() {
    const d = optState.compare;
    if (!d) return;
    const sym = escapeHtml(d.symbol);
    const t = d.target;
    const help = document.getElementById("cmp-help");
    document.getElementById("cmp-clear-target").hidden = !t;
    if (t) {
        const winners = d.strategies.filter(r => r.pnl_at_target > 0).length;
        const move = (t / d.spot - 1) * 100;
        const o = d.target_odds;
        const odds = o ? ` Option prices imply a <strong>${Math.round((t >= d.spot ? o.above : o.below) * 100)}% chance</strong> ` +
            `${sym} ends ${t >= d.spot ? "above" : "below"} $${t.toFixed(2)} by then, and about ${Math.round(o.touch * 100)}% ` +
            "that it trades there at some point before." : "";
        help.innerHTML = `Ranked for <strong>${sym} at $${t.toFixed(2)}</strong> on ${optDate(d.expiry)} ` +
            `(${move >= 0 ? "+" : ""}${move.toFixed(1)}% from $${d.spot.toFixed(2)}). ${winners} of ${d.strategies.length} strategies ` +
            "make money there. Best fit first: the most profit at your target for each dollar it can lose. " +
            "If you're wrong, the worst case still applies." + odds;
    } else {
        help.textContent = `Type a price (or pick a move) to rank all ${d.strategies.length} strategies for it. ` +
            "Without one, you can still compare any of them below.";
    }
    const sel = new Set(optState.compareSel || []);
    const money = (v, unlimited) => unlimited ? "Unlimited" : optMoney(v, true);
    document.getElementById("cmp-table").innerHTML = `<thead><tr>
        <th>Compare</th><th>Strategy</th><th class="opt-num">Cost</th>
        ${t ? `<th class="opt-num">If ${sym} is $${t.toFixed(2)}</th><th class="opt-num" title="Profit at your target divided by the most it can lose">Reward ÷ risk</th>` : ""}
        <th class="opt-num">Best case</th><th class="opt-num">Worst case</th><th class="opt-num">Chance of profit</th><th></th></tr></thead>
        <tbody>${d.strategies.map((r, i) => {
            const info = OPT_PRESET_INFO[r.preset];
            const loses = t && r.pnl_at_target <= 0;
            return `<tr class="${loses ? "cmp-loses" : ""}">
                <td><input type="checkbox" class="cmp-pick" data-preset="${r.preset}"${sel.has(r.preset) ? " checked" : ""}
                     aria-label="Compare ${escapeHtml(r.name)}"></td>
                <td><span class="cmp-name">${escapeHtml(r.name)}</span>
                    ${t && i === 0 && !loses ? `<span class="cmp-best">Best fit</span>` : ""}
                    <span class="opt-view opt-view-${info.kind}">${escapeHtml(info.view)}</span></td>
                <td class="opt-num">${r.net_debit >= 0 ? "pay " + optMoney(r.net_debit) : "collect " + optMoney(-r.net_debit)}</td>
                ${t ? `<td class="opt-num ${r.pnl_at_target > 0 ? "positive" : "negative"}">${optMoney(r.pnl_at_target, true)}</td>
                       <td class="opt-num">${r.reward_risk_at_target === null || r.reward_risk_at_target === undefined ? "—" : r.reward_risk_at_target.toFixed(2) + "×"}</td>` : ""}
                <td class="opt-num positive">${money(r.max_profit, r.unlimited_profit)}</td>
                <td class="opt-num negative">${money(r.max_loss, r.unlimited_loss)}</td>
                <td class="opt-num">${optPct(r.prob_profit, 0)}</td>
                <td><button class="btn-secondary cmp-open" data-preset="${r.preset}" type="button">Open</button></td></tr>`;
        }).join("")}</tbody>`;
    optRenderCompareSide();
}

function optRenderCompareSide() {
    const d = optState.compare;
    const rows = (optState.compareSel || []).map(p => d.strategies.find(r => r.preset === p)).filter(Boolean);
    document.getElementById("cmp-results").hidden = !rows.length;
    if (!rows.length) return;
    const t = d.target;
    const sym = escapeHtml(d.symbol);
    const at = (r, m) => { const s = (r.scenarios || []).find(x => x.move_pct === m); return s ? s.expiry : null; };
    const cell = v => v === null || v === undefined ? "<td class=\"opt-num\">—</td>"
        : `<td class="opt-num ${v > 0 ? "positive" : v < 0 ? "negative" : ""}">${optMoney(v, true)}</td>`;
    const metric = (label, fn) => `<tr><th scope="row">${label}</th>${rows.map(fn).join("")}</tr>`;
    document.getElementById("cmp-side").innerHTML = `<thead><tr><th></th>${rows.map((r, i) =>
        `<th class="opt-num"><span class="cmp-swatch" style="background:${OPT_COMPARE_COLORS[i]}"></span>${escapeHtml(r.name)}</th>`).join("")}</tr></thead>
        <tbody>
        ${metric("You pay / collect", r => `<td class="opt-num">${r.net_debit >= 0 ? "pay " + optMoney(r.net_debit) : "collect " + optMoney(-r.net_debit)}</td>`)}
        ${metric("Best case", r => r.unlimited_profit ? `<td class="opt-num positive">Unlimited</td>` : cell(r.max_profit))}
        ${metric("Worst case", r => r.unlimited_loss ? `<td class="opt-num negative">Unlimited</td>` : cell(r.max_loss))}
        ${metric("Break-even", r => `<td class="opt-num">${r.breakevens.length ? r.breakevens.map(b => "$" + b.toFixed(2)).join(" / ") : "—"}</td>`)}
        ${metric("Makes money if", r => `<td class="opt-num cmp-zone">${escapeHtml(optZoneText(r.profit_zones))}</td>`)}
        ${metric("Chance of profit", r => `<td class="opt-num">${optPct(r.prob_profit, 0)}</td>`)}
        ${t ? metric(`If ${sym} is $${t.toFixed(2)}`, r => cell(r.pnl_at_target)) : ""}
        ${metric(`If ${sym} drops 10%`, r => cell(at(r, -10)))}
        ${metric("If it doesn't move", r => cell(at(r, 0)))}
        ${metric(`If ${sym} rises 10%`, r => cell(at(r, 10)))}
        </tbody>`;
    optDrawCompare(rows);
}

function optDrawCompare(rows) {
    const el = document.getElementById("cmp-chart");
    if (!el || typeof Plotly === "undefined") return;
    const d = optState.compare;
    const narrow = el.clientWidth < 640;
    // A window that matters: ±2.5 expected moves (at least ±12%), widened to include the target.
    // Without it an unlimited-profit line stretches the scale and flattens the others.
    const [lo, hi] = optCompareWindow(d.spot, d.expected_move, d.target);
    const traces = rows.map((r, i) => ({
        ...optClipCurve(r.curve.prices, r.curve.expiry, lo, hi), name: r.name, type: "scatter", mode: "lines",
        line: { color: OPT_COMPARE_COLORS[i], width: 2.5 },
        hovertemplate: `${r.name}: %{y:$,.0f}<extra></extra>`,
    }));
    const range = optExpectedRange(optState.chain && optState.chain.expiry === d.expiry ? optState.chain : null);
    const shapes = [
        ...(range ? [{ type: "rect", xref: "x", x0: range.lo, x1: range.hi, yref: "paper", y0: 0, y1: 1, layer: "below",
                       fillcolor: "rgba(96,165,250,0.07)", line: { width: 1, color: "rgba(96,165,250,0.3)", dash: "dot" } }] : []),
        { type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: "rgba(255,255,255,0.35)", width: 1 } },
        { type: "line", xref: "x", x0: d.spot, x1: d.spot, yref: "paper", y0: 0, y1: 1,
          line: { color: "rgba(255,255,255,0.35)", width: 1, dash: "dot" } },
        ...(d.target ? [{ type: "line", xref: "x", x0: d.target, x1: d.target, yref: "paper", y0: 0, y1: 1,
                          line: { color: "#4ADE80", width: 1.5, dash: "dash" } }] : []),
    ];
    const notes = [
        { x: d.spot, y: 1, yref: "paper", text: narrow ? "Now" : `Now $${d.spot.toFixed(2)}`, showarrow: false,
          yanchor: "bottom", font: { size: 12, color: "#E5E7EB" } },
        ...(d.target ? [{ x: d.target, y: 0.92, yref: "paper", text: narrow ? "Target" : `Your target $${d.target.toFixed(2)}`,
                          showarrow: false, xanchor: d.target >= d.spot ? "left" : "right", font: { size: 12, color: "#4ADE80" },
                          bgcolor: "rgba(17,18,20,0.85)" }] : []),
    ];
    Plotly.react(el, traces, optPlotTheme({
        showlegend: true,
        legend: narrow ? { orientation: "h", y: -0.32, x: 0, font: { size: 11, color: "#E5E7EB" } }
                       : { orientation: "h", y: 1.1, x: 0, font: { size: 12, color: "#E5E7EB" } },
        hovermode: "x unified",
        hoverlabel: { bgcolor: "#111214", bordercolor: "#3B4048", font: { color: "#F3F4F6", size: 13 } },
        margin: narrow ? { l: 56, r: 12, t: 30, b: 96 } : { l: 70, r: 20, t: 52, b: 48 },
        xaxis: { title: { text: `${d.symbol} price at expiry`, font: { size: 12, color: "#C9CED6" } },
                 gridcolor: "rgba(255,255,255,0.06)", zeroline: false, tickprefix: "$", hoverformat: "$.2f",
                 tickfont: { size: 12, color: "#C9CED6" } },
        yaxis: { title: { text: "Profit or loss", font: { size: 12, color: "#C9CED6" } },
                 gridcolor: "rgba(255,255,255,0.06)", zeroline: false, tickprefix: "$", tickformat: ",.0f",
                 tickfont: { size: 12, color: "#C9CED6" } },
        shapes, annotations: notes,
    }), { responsive: true, displayModeBar: false });
}

function optCompareClick(e) {
    const open = e.target.closest(".cmp-open");
    if (open) {
        optShowTab("strategy");
        optBuildPreset(open.dataset.preset);
        return;
    }
    const box = e.target.closest(".cmp-pick");
    if (!box) return;
    let sel = (optState.compareSel || []).filter(p => p !== box.dataset.preset);
    if (box.checked) sel.push(box.dataset.preset);
    if (sel.length > OPT_COMPARE_MAX) {
        const dropped = sel.shift();
        const other = document.querySelector(`.cmp-pick[data-preset="${dropped}"]`);
        if (other) other.checked = false;
    }
    optState.compareSel = sel;
    optRenderCompareSide();
}

function optSetTarget(value) {
    const v = Number(value);
    optState.compareTarget = Number.isFinite(v) && v > 0 ? Math.round(v * 100) / 100 : null;
    optState.compareSel = null;          // a new view: start from its top three
    document.getElementById("cmp-target").value = optState.compareTarget || "";
    optLoadCompare();
}

function optStatus(msg, isError) {
    const el = document.getElementById("opt-status");
    el.textContent = msg || "";
    el.classList.toggle("opt-error", !!isError);
}

async function optLoadSymbol(sym) {
    optState.symbol = sym;
    optState.compareTarget = null;        // a target price belongs to one stock
    const t = document.getElementById("cmp-target");
    if (t) t.value = "";
    document.querySelectorAll(".opt-quick-btn").forEach(b => b.classList.toggle("active", b.dataset.symbol === sym));
    optState.chain = null;
    optState.legs = [];
    optState.analysis = null;
    document.getElementById("opt-symbol").value = sym;
    optSetPreset(null);
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
        optLabelExpiries(chain);
        if (optState.tab === "compare") optEnsureCompare();
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

function optEarningsStat(c) {
    if (!c.earnings) return "";
    const today = new Date().toISOString().slice(0, 10);
    const days = optDaysBetween(today, c.earnings.date);
    const when = days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`;
    return `<div class="opt-stat${c.earnings_before_expiry ? " opt-stat-warn" : ""}" title="${c.earnings.estimated ? "Yahoo's estimate; the company may not have confirmed it yet" : "Confirmed date"}">
        <span class="opt-stat-label">Next earnings${c.earnings.estimated ? " (est.)" : ""}</span>
        <span class="opt-stat-val">${optDate(c.earnings.date)} <span class="opt-dim">· ${when}</span></span></div>`;
}

// Mark the expiries that come after the next earnings report in the dropdown.
function optLabelExpiries(c) {
    const sel = document.getElementById("opt-expiry");
    if (!sel) return;
    for (const o of sel.options) {
        const e = optState.expirations.find(x => x.date === o.value);
        if (!e) continue;
        const after = c.earnings && e.date >= c.earnings.date;
        o.textContent = `${e.date} (${e.dte}d)${after ? " · after earnings" : ""}`;
    }
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
        ${optEarningsStat(c)}
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
    const font = { color: "#C9CED6", size: 12, family: "-apple-system, BlinkMacSystemFont, Inter, 'Segoe UI', system-ui, sans-serif" };
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
    optSetPreset(null);
    optShowTab("strategy");
    optAnalyze();
}

// ---------- strategy builder ----------

// The highlighted strategy card (null when the legs are custom).
function optSetPreset(name) {
    optState.preset = name;
    document.querySelectorAll(".opt-preset-card").forEach(c => c.classList.toggle("active", c.dataset.preset === name));
}

async function optBuildPreset(preset) {
    if (!optState.chain) return;
    optSetPreset(preset);
    await optAnalyze({ preset });
}

async function optAnalyze(extra) {
    if (!optState.chain) return;
    const id = ++optState.reqId;
    const body = { symbol: optState.symbol, expiry: optState.expiry, days_forward: optState.daysForward || null,
                   iv_shift: optState.ivShift || 0 };
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
    const thinLegs = priced.map(p => optThinReason(p, c));
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
            <td class="opt-leg-plain">${p ? escapeHtml(optLegPlain(p, a.symbol)) : ""}${
                thinLegs[i] ? ` <span class="opt-thin" title="${escapeHtml(thinLegs[i])}">thin market</span>` : ""}</td>
            <td><button class="btn-icon" data-remove="${i}" aria-label="Remove leg">✕</button></td></tr>`;
    }).join("") : `<tr><td colspan="7" class="feed-empty">Pick a strategy above, or click a bid (sell) or ask (buy) in the Chain tab.</td></tr>`;
    const thinCount = thinLegs.filter(Boolean).length;
    const thinNote = document.getElementById("opt-thin-note");
    thinNote.hidden = !thinCount;
    thinNote.textContent = thinCount
        ? `${thinCount === 1 ? "One leg trades" : thinCount + " legs trade"} thinly (a wide bid-ask spread or few open ` +
          "contracts). Real fills there are usually well away from the mid prices used here, so expect the cost to be worse."
        : "";

    const stats = document.getElementById("opt-stats");
    const sum = document.getElementById("opt-strategy-summary");
    const results = document.getElementById("opt-results");
    document.getElementById("opt-ask-ski").hidden = !a;
    document.getElementById("opt-save-paper").hidden = !a;
    results.hidden = !a;
    if (!a) {
        stats.innerHTML = "";
        sum.textContent = "";
        document.getElementById("opt-scenarios").innerHTML = "";
        document.getElementById("opt-greeks").innerHTML = "";
        const chart = document.getElementById("opt-payoff");
        if (typeof Plotly !== "undefined") Plotly.purge(chart);
        chart.innerHTML = "";
        return;
    }
    const g = a.greeks;
    const card = (label, val, sub, cls) => `<div class="opt-outcome ${cls || ""}">
        <span class="opt-outcome-label">${label}</span>
        <span class="opt-outcome-val">${val}</span>
        <span class="opt-outcome-sub">${sub}</span></div>`;
    const pop = a.prob_profit === null ? null : Math.round(a.prob_profit * 100);
    const debit = a.net_debit >= 0;
    stats.innerHTML =
        card(debit ? "You pay" : "You collect", optMoney(Math.abs(a.net_debit)),
             debit ? "up front, at mid prices" : "up front, yours to keep if it works", "") +
        card("Best case", a.unlimited_profit ? "Unlimited" : optMoney(a.max_profit, true),
             a.unlimited_profit ? "keeps growing the further the stock moves" : `at expiry, ${optZoneText(a.profit_zones)}`, "good") +
        card("Worst case", a.unlimited_loss ? "Unlimited" : optMoney(a.max_loss, true),
             a.unlimited_loss ? "losses grow without a cap" : "the most this position can lose", "bad") +
        card("Break-even", a.breakevens.length ? a.breakevens.map(b => "$" + b.toFixed(2)).join(" / ") : "—",
             `${escapeHtml(a.symbol)} at expiry (now $${a.spot.toFixed(2)})`, "") +
        `<div class="opt-outcome" title="What option prices imply (a lognormal at the at-the-money implied volatility), not a forecast">
            <span class="opt-outcome-label">Chance of profit</span>
            <span class="opt-outcome-val">${pop === null ? "—" : pop + "%"}</span>
            <span class="opt-meter" aria-hidden="true"><span style="width:${pop || 0}%"></span></span>
            <span class="opt-outcome-sub">implied by option prices, not a forecast</span></div>`;
    sum.innerHTML = `<strong>In plain words:</strong> ${escapeHtml(a.summary)}`;
    const warn = document.getElementById("opt-earnings-warning");
    if (c && c.earnings && c.earnings_before_expiry) {
        warn.hidden = false;
        warn.innerHTML = `<strong>Earnings before expiry.</strong> ${escapeHtml(a.symbol)} reports on ` +
            `${optDate(c.earnings.date)}${c.earnings.estimated ? " (estimated)" : ""}, before this position expires. ` +
            "The stock can jump either way on the news, and option prices usually drop sharply right after " +
            "(the \"IV crush\"), which hurts positions that bought options and helps those that sold them.";
    } else {
        warn.hidden = true;
    }
    const range = optExpectedRange(c);
    document.getElementById("opt-range-note").textContent = range
        ? `Shaded: the range the market expects by expiry, $${range.lo.toFixed(2)} to $${range.hi.toFixed(2)} ` +
          "(about a 2-in-3 chance the stock ends inside it)."
        : "";

    // What if the stock moves X%? (An older backend has no scenarios: hide the table.)
    const scenarios = a.scenarios || [];
    document.getElementById("opt-scenarios-block").hidden = !scenarios.length;
    const atDate = scenarios.length > 0 && scenarios[0].at_date !== undefined;
    const pl = v => `<td class="opt-num ${v > 0 ? "positive" : v < 0 ? "negative" : ""}">${optMoney(v, true)}</td>`;
    document.getElementById("opt-scenarios").innerHTML = `<thead><tr>
            <th>If ${escapeHtml(a.symbol)} moves</th><th class="opt-num">Price</th>
            <th class="opt-num">P/L at expiry</th>${atDate ? `<th class="opt-num">P/L in ${a.curves.at_date_days} days${optIvTag(a.iv_shift)}</th>` : ""}
            <th class="opt-num">P/L today${optIvTag(a.iv_shift)}</th></tr></thead><tbody>${scenarios.map(s => `
        <tr class="${s.move_pct === 0 ? "opt-scn-now" : ""}">
            <td>${s.move_pct === 0 ? "No change" : (s.move_pct > 0 ? "Up " : "Down ") + Math.abs(s.move_pct) + "%"}</td>
            <td class="opt-num">$${s.price.toFixed(2)}</td>${pl(s.expiry)}${atDate ? pl(s.at_date) : ""}${pl(s.today)}</tr>`).join("")}</tbody>`;

    document.getElementById("opt-greeks").innerHTML = [
        ["Delta", `${g.delta.toFixed(0)} shares`, "The position moves like this many shares of the stock right now."],
        ["Theta", `${optMoney(g.theta, true)} a day`, "What one day passing does to its value, all else equal (time decay)."],
        ["Vega", `${optMoney(g.vega, true)} per vol point`, "What a 1-point rise in implied volatility does to its value."],
        ["Gamma", `${g.gamma.toFixed(2)}`, "How fast delta changes as the stock moves."],
        ["Spread cost", optMoney(a.spread_cost), "Extra paid if you buy at the ask and sell at the bid instead of the midpoint."],
        ["Reward / risk", a.return_on_risk === null ? "—" : a.return_on_risk.toFixed(2) + "×", "Best case divided by worst case."],
    ].map(([k, v, d]) => `<div class="opt-greek"><span class="opt-outcome-label">${k}</span>
        <span class="opt-greek-val">${v}</span><span class="opt-greek-text">${d}</span></div>`).join("");
    document.getElementById("opt-decay-note").textContent =
        optDecayNote(a.decay, a.greeks.theta, a.symbol, a.spot);
    if (optState.tab === "strategy") { optDrawPayoff(a); optDrawDecay(a); }
}

function optDrawDecay(a) {
    const el = document.getElementById("opt-decay");
    if (!el || typeof Plotly === "undefined" || !a.decay) return;
    const start = new Date();
    const dates = a.decay.map(p => new Date(start.getTime() + p.days * 86400000).toISOString().slice(0, 10));
    const ys = a.decay.map(p => p.pnl);
    const up = ys[ys.length - 1] >= ys[0];
    Plotly.react(el, [{
        x: dates, y: ys, type: "scatter", mode: "lines", line: { color: up ? "#4ADE80" : "#F87171", width: 2.5 },
        fill: "tozeroy", fillcolor: up ? "rgba(22,163,74,0.12)" : "rgba(239,68,68,0.12)",
        hovertemplate: "%{x|%b %d}: %{y:$,.0f}<extra></extra>",
    }], optPlotTheme({
        margin: { l: 70, r: 20, t: 16, b: 40 },
        xaxis: { type: "date", tickformat: "%b %d", gridcolor: "rgba(255,255,255,0.06)", tickfont: { size: 12, color: "#C9CED6" } },
        yaxis: { title: { text: "P/L at today's price", font: { size: 12, color: "#C9CED6" } }, tickprefix: "$",
                 tickformat: ",.0f", gridcolor: "rgba(255,255,255,0.06)", zeroline: true,
                 zerolinecolor: "rgba(255,255,255,0.3)", tickfont: { size: 12, color: "#C9CED6" } },
        hovermode: "x unified",
        hoverlabel: { bgcolor: "#111214", bordercolor: "#3B4048", font: { color: "#F3F4F6", size: 13 } },
    }), { responsive: true, displayModeBar: false });
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
    optSetPreset(null);
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
          line: { color: "#F3F4F6", width: 2.5 }, hovertemplate: "At expiry: %{y:$,.0f}<extra></extra>" },
        { x: cv.prices, y: cv.today, name: "If it moved today" + optIvTag(a.iv_shift), type: "scatter", mode: "lines",
          line: { color: "#60A5FA", width: 2, dash: "dash" }, hovertemplate: "Today: %{y:$,.0f}<extra></extra>" },
    ];
    if (cv.at_date) traces.push({ x: cv.prices, y: cv.at_date, name: `In ${cv.at_date_days} days` + optIvTag(a.iv_shift), type: "scatter",
        mode: "lines", line: { color: "#F59E0B", width: 2, dash: "dot" },
        hovertemplate: `In ${cv.at_date_days}d: %{y:$,.0f}<extra></extra>` });
    const range = optExpectedRange(optState.chain && optState.chain.expiry === a.expiry ? optState.chain : null);
    const shapes = [
        ...(range ? [{ type: "rect", xref: "x", x0: range.lo, x1: range.hi, yref: "paper", y0: 0, y1: 1, layer: "below",
                       fillcolor: "rgba(96,165,250,0.08)", line: { width: 1, color: "rgba(96,165,250,0.35)", dash: "dot" } }] : []),
        { type: "line", xref: "x", x0: a.spot, x1: a.spot, yref: "paper", y0: 0, y1: 1,
          line: { color: "rgba(255,255,255,0.35)", width: 1, dash: "dot" } },
        { type: "line", xref: "paper", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: "rgba(255,255,255,0.25)", width: 1 } },
    ];
    // Narrow screens: legend under the chart, so it can't collide with the "Now" and break-even labels.
    const narrow = el.clientWidth < 640;
    Plotly.react(el, traces, optPlotTheme({
        showlegend: true,
        legend: narrow ? { orientation: "h", y: -0.32, x: 0, font: { size: 11, color: "#E5E7EB" } }
                       : { orientation: "h", y: 1.1, x: 0, font: { size: 12, color: "#E5E7EB" } },
        hovermode: "x unified",
        hoverlabel: { bgcolor: "#111214", bordercolor: "#3B4048", font: { color: "#F3F4F6", size: 13 } },
        margin: narrow ? { l: 56, r: 12, t: 30, b: 96 } : { l: 70, r: 20, t: 52, b: 48 },
        xaxis: { title: { text: `${a.symbol} price at expiry`, font: { size: 12, color: "#C9CED6" } }, gridcolor: "rgba(255,255,255,0.06)",
                 tickfont: { size: 12, color: "#C9CED6" },
                 zeroline: false, tickprefix: "$", hoverformat: "$.2f" },
        yaxis: { title: { text: "Your profit or loss", font: { size: 12, color: "#C9CED6" } }, gridcolor: "rgba(255,255,255,0.06)",
                 tickfont: { size: 12, color: "#C9CED6" },
                 zeroline: false, tickprefix: "$", tickformat: ",.0f" },
        shapes,
        annotations: [
            { x: a.spot, y: 1, yref: "paper", text: narrow ? "Now" : `Now $${a.spot.toFixed(2)}`, showarrow: false,
              yanchor: "bottom", font: { size: 12, color: "#E5E7EB" } },
            ...(range ? [{ x: range.hi, y: 1, yref: "paper", xanchor: "right", yanchor: "top", showarrow: false,
                           text: narrow ? "Expected range" : "Expected range (≈68%)", font: { size: 11, color: "#93C5FD" } }] : []),
            // Alternate heights so two close break-evens don't print on top of each other.
            ...a.breakevens.map((be, i) => ({ x: be, y: 0, text: narrow ? `$${be.toFixed(2)}` : `Break-even $${be.toFixed(2)}`,
              showarrow: true, arrowhead: 0, ax: 0, ay: i % 2 ? -58 : -32, arrowcolor: "#FBBF24",
              font: { size: narrow ? 11 : 12, color: "#FBBF24" },
              bgcolor: "rgba(17,18,20,0.85)", borderpad: 3 })),
        ],
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
        skip_earnings: document.getElementById("opt-scan-earnings").checked ? "1" : "0",
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
            <td class="opt-num" title="${escapeHtml(r.strikes || "")}: + bought, - sold; P put, C call">${escapeHtml(r.strikes || String(r.strike))}${
                r.earnings_before_expiry ? ` <span class="opt-earn-flag" title="Earnings before expiry">earnings</span>` : ""}</td>
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
    optState.legs = r.legs ? r.legs.map(l => ({ ...l }))
        : r.kind === "covered_call"
            ? [{ type: "stock", qty: 1, strike: null }, { type: "call", qty: -1, strike: r.strike }]
            : [{ type: "put", qty: -1, strike: r.strike }];
    optState.preset = null;
    optSetPreset(null);
    optShowTab("strategy");
    optAnalyze();
}

document.addEventListener("DOMContentLoaded", initOptions);
