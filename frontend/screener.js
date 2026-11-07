// screener.js — the stock screener: every US-listed common stock, filterable.
//
// The data is built after each US close by .github/workflows/screener.yml
// (scripts/build_screener.py) and read here as one static file, so screening
// never touches the backend. Uses globals from dashboard.js: escapeHtml,
// switchSymbol.

const SCREENER_URL = "https://raw.githubusercontent.com/Danny-397/Tradeski/screener-data/screener.json";
const SCR_PAGE = 50;

// Field metadata: label, how to show it, and (for range filters) the unit the
// inputs use and the factor from that unit to the stored value.
const SCR_FIELDS = {
    symbol:           { label: "Symbol",          kind: "text" },
    name:             { label: "Company",         kind: "text" },
    exchange:         { label: "Exchange",        kind: "text" },
    sector:           { label: "Sector",          kind: "text" },
    industry:         { label: "Industry",        kind: "text" },
    country:          { label: "Country",         kind: "text" },
    price:            { label: "Price",           kind: "money",  unit: "$" },
    change:           { label: "Change",          kind: "signed", unit: "%" },
    volume:           { label: "Volume",          kind: "vol" },
    avg_volume:       { label: "Avg volume",      kind: "vol",    unit: "K shares", scale: 1e3 },
    rel_volume:       { label: "Rel. volume",     kind: "x",      unit: "×" },
    market_cap:       { label: "Market cap",      kind: "cap",    unit: "$B", scale: 1e9 },
    pe:               { label: "P/E",             kind: "ratio" },
    forward_pe:       { label: "Fwd P/E",         kind: "ratio" },
    peg:              { label: "PEG",             kind: "ratio" },
    ps:               { label: "P/S",             kind: "ratio" },
    pb:               { label: "P/B",             kind: "ratio" },
    dividend_yield:   { label: "Div. yield",      kind: "pct",    unit: "%" },
    eps:              { label: "EPS (ttm)",       kind: "money",  unit: "$" },
    revenue_growth:   { label: "Revenue growth",  kind: "signed", unit: "%" },
    eps_growth:       { label: "EPS growth",      kind: "signed", unit: "%" },
    gross_margin:     { label: "Gross margin",    kind: "signed", unit: "%" },
    operating_margin: { label: "Oper. margin",    kind: "signed", unit: "%" },
    profit_margin:    { label: "Net margin",      kind: "signed", unit: "%" },
    roe:              { label: "ROE",             kind: "signed", unit: "%" },
    debt_equity:      { label: "Debt/Equity",     kind: "ratio",  unit: "×" },
    current_ratio:    { label: "Current ratio",   kind: "ratio",  unit: "×" },
    rating:           { label: "Analyst rating",  kind: "rating", unit: "1 buy – 5 sell" },
    upside:           { label: "Target upside",   kind: "signed", unit: "%" },
    analysts:         { label: "Analysts",        kind: "int" },
    short_float:      { label: "Short float",     kind: "pct",    unit: "%" },
    institutional:    { label: "Institutional",   kind: "pct",    unit: "%" },
    earnings_date:    { label: "Earnings",        kind: "date" },
    perf_1w:          { label: "1W",              kind: "signed", unit: "%" },
    perf_1m:          { label: "1M",              kind: "signed", unit: "%" },
    perf_3m:          { label: "3M",              kind: "signed", unit: "%" },
    perf_6m:          { label: "6M",              kind: "signed", unit: "%" },
    perf_ytd:         { label: "YTD",             kind: "signed", unit: "%" },
    perf_1y:          { label: "1Y",              kind: "signed", unit: "%" },
    high_52w:         { label: "52W high",        kind: "money" },
    low_52w:          { label: "52W low",         kind: "money" },
    from_high:        { label: "From 52W high",   kind: "signed", unit: "%" },
    from_low:         { label: "From 52W low",    kind: "signed", unit: "%" },
    rsi:              { label: "RSI (14)",        kind: "num" },
    sma20:            { label: "vs SMA20",        kind: "signed", unit: "%" },
    sma50:            { label: "vs SMA50",        kind: "signed", unit: "%" },
    sma200:           { label: "vs SMA200",       kind: "signed", unit: "%" },
    volatility:       { label: "Volatility (1M)", kind: "pct",    unit: "%" },
    beta:             { label: "Beta",            kind: "ratio" },
    atr:              { label: "ATR",             kind: "pct",    unit: "% of price" },
};

const SCR_GROUPS = [
    { id: "descriptive", label: "Descriptive", selects: ["exchange", "sector", "industry", "country"],
      ranges: ["market_cap", "price", "avg_volume", "rel_volume"], earnings: true },
    { id: "valuation", label: "Valuation", ranges: ["pe", "forward_pe", "peg", "ps", "pb", "dividend_yield"] },
    { id: "financial", label: "Growth & profitability",
      ranges: ["revenue_growth", "eps_growth", "gross_margin", "operating_margin", "profit_margin", "roe",
               "debt_equity", "current_ratio"] },
    { id: "performance", label: "Performance",
      ranges: ["change", "perf_1w", "perf_1m", "perf_3m", "perf_6m", "perf_ytd", "perf_1y"] },
    { id: "technical", label: "Technical",
      ranges: ["rsi", "sma20", "sma50", "sma200", "from_high", "from_low", "volatility", "beta", "atr"] },
    { id: "analysts", label: "Analysts & ownership",
      ranges: ["rating", "upside", "analysts", "short_float", "institutional"] },
];

const SCR_VIEWS = {
    overview:    ["symbol", "name", "sector", "industry", "market_cap", "pe", "price", "change", "volume"],
    valuation:   ["symbol", "market_cap", "pe", "forward_pe", "peg", "ps", "pb", "dividend_yield", "eps", "upside"],
    financial:   ["symbol", "revenue_growth", "eps_growth", "gross_margin", "operating_margin", "profit_margin",
                  "roe", "debt_equity", "current_ratio"],
    performance: ["symbol", "change", "perf_1w", "perf_1m", "perf_3m", "perf_6m", "perf_ytd", "perf_1y", "volatility"],
    technical:   ["symbol", "price", "rsi", "sma20", "sma50", "sma200", "from_high", "from_low", "rel_volume",
                  "beta", "atr"],
    analysts:    ["symbol", "price", "rating", "upside", "analysts", "short_float", "institutional", "earnings_date"],
};

// Ready-made screens. Ranges are in the filter inputs' units (market cap in $B).
const SCR_PRESETS = [
    { id: "near-highs",  label: "Large caps near 52-week highs", ranges: { market_cap: [10, null], from_high: [-3, null] } },
    { id: "oversold",    label: "Oversold large caps (RSI < 30)", ranges: { market_cap: [10, null], rsi: [null, 30] } },
    { id: "pullback",    label: "Pullbacks in uptrends", ranges: { sma200: [0, null], sma50: [null, 0], rsi: [null, 45], market_cap: [2, null] } },
    { id: "momentum",    label: "Momentum leaders", ranges: { perf_6m: [25, null], sma50: [0, null], sma200: [0, null], avg_volume: [500, null] } },
    { id: "gainers",     label: "Today's top gainers", ranges: { change: [5, null], avg_volume: [300, null] }, sort: ["change", -1] },
    { id: "losers",      label: "Today's top losers", ranges: { change: [null, -5], avg_volume: [300, null] }, sort: ["change", 1] },
    { id: "volume",      label: "Unusual volume (2× average)", ranges: { rel_volume: [2, null], avg_volume: [300, null] }, sort: ["rel_volume", -1] },
    { id: "value",       label: "Value (P/E < 15, P/B < 3)", ranges: { pe: [0, 15], pb: [null, 3], market_cap: [2, null] } },
    { id: "dividends",   label: "Dividend payers (yield > 3%)", ranges: { dividend_yield: [3, null], market_cap: [2, null] }, sort: ["dividend_yield", -1] },
    { id: "growth",      label: "Fast growers (revenue & EPS > 20%)", ranges: { revenue_growth: [20, null], eps_growth: [20, null] } },
    { id: "quality",     label: "Quality (ROE > 15%, margin > 15%, low debt)", ranges: { roe: [15, null], profit_margin: [15, null], debt_equity: [null, 1] } },
    { id: "analysts",    label: "Analyst favourites (≥ 20% upside)", ranges: { rating: [null, 2], upside: [20, null], analysts: [5, null] }, sort: ["upside", -1] },
    { id: "squeeze",     label: "Heavily shorted (short float > 20%)", ranges: { short_float: [20, null], avg_volume: [300, null] }, sort: ["short_float", -1] },
];

const scrState = {
    rows: null,          // all stocks (objects), once loaded
    meta: null,
    filters: { ranges: {}, selects: {}, earnings: "", search: "" },
    view: "overview",
    sort: { col: "market_cap", dir: -1 },
    page: 0,
    filtered: [],
    loading: false,
    screens: [],         // saved screens (account when signed in, else this browser)
    active: null,        // name of the saved screen on show
    fresh: new Set(),    // symbols new to the active screen since it was last opened
    onlyNew: false,
};
const SCR_SCREENS_KEY = "tradeski-saved-screens";
const SCR_SEEN_MAX = 3000;   // broader screens aren't tracked for new matches (server limit too)
const SCR_SCREENS_MAX = 10;

// ---------- pure helpers (unit-tested in tests/js/screener.test.mjs) ----------

// Columnar file -> one object per stock.
function scrRows(data) {
    const f = data.fields || [];
    return (data.rows || []).map(r => {
        const o = {};
        for (let i = 0; i < f.length; i++) o[f[i]] = r[i];
        return o;
    });
}

// Days from `today` (YYYY-MM-DD) to `date`, or null.
function scrDaysUntil(date, today) {
    if (!date) return null;
    return Math.round((Date.parse(date + "T00:00:00Z") - Date.parse(today + "T00:00:00Z")) / 86400000);
}

// Does a stock pass every active filter? Ranges are in the inputs' units; a
// stock with no value for a filtered field does not pass (an unknown P/E is
// not "under 15").
function scrMatches(row, filters, today) {
    for (const [field, [lo, hi]] of Object.entries(filters.ranges || {})) {
        if (lo === null && hi === null) continue;
        const v = row[field];
        if (v === null || v === undefined) return false;
        const scale = (SCR_FIELDS[field] && SCR_FIELDS[field].scale) || 1;
        if (lo !== null && v < lo * scale) return false;
        if (hi !== null && v > hi * scale) return false;
    }
    for (const [field, want] of Object.entries(filters.selects || {})) {
        if (!want) continue;
        if (field === "country" && want === "__non_us") {
            if (!row.country || row.country === "United States") return false;
        } else if (row[field] !== want) return false;
    }
    if (filters.earnings) {
        const d = scrDaysUntil(row.earnings_date, today);
        const max = { week: 7, two_weeks: 14, month: 31 }[filters.earnings];
        if (d === null || d < 0 || d > max) return false;
    }
    const q = (filters.search || "").trim().toLowerCase();
    if (q && !(row.symbol.toLowerCase().startsWith(q) || (row.name || "").toLowerCase().includes(q))) return false;
    return true;
}

// Sorted copy; missing values always last, whichever the direction.
function scrSort(rows, col, dir) {
    return [...rows].sort((a, b) => {
        const av = a[col], bv = b[col];
        const am = av === null || av === undefined, bm = bv === null || bv === undefined;
        if (am || bm) return am && bm ? 0 : am ? 1 : -1;
        if (typeof av === "string") return dir * av.localeCompare(bv);
        return dir * (av - bv);
    });
}

function scrFormat(v, kind) {
    if (v === null || v === undefined || v === "") return "—";
    switch (kind) {
        case "money":  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        case "signed": return (v > 0 ? "+" : "") + v.toFixed(Math.abs(v) >= 100 ? 0 : 2) + "%";
        case "pct":    return v.toFixed(2) + "%";
        case "x":      return v.toFixed(2) + "×";
        case "ratio":  return v.toFixed(2);
        case "rating": return v.toFixed(1);
        case "num":    return v.toFixed(1);
        case "int":    return String(Math.round(v));
        case "cap":
            if (v >= 1e12) return "$" + (v / 1e12).toFixed(2) + "T";
            if (v >= 1e9)  return "$" + (v / 1e9).toFixed(1) + "B";
            if (v >= 1e6)  return "$" + (v / 1e6).toFixed(0) + "M";
            return "$" + Math.round(v).toLocaleString("en-US");
        case "vol":
            if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
            if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
            if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
            return String(v);
        default:       return String(v);
    }
}

function scrCsv(rows, fields) {
    const cell = v => {
        if (v === null || v === undefined) return "";
        const s = String(v);
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    return [fields.join(","), ...rows.map(r => fields.map(f => cell(r[f])).join(","))].join("\n");
}

// A filter bound in its unit, for the chips: 10 with "$B" -> "$10B", 2 with "×" -> "2×".
function scrUnitValue(v, meta) {
    const u = (meta && meta.unit) || "";
    if (u.startsWith("$")) return `$${v}${u.slice(1)}`;
    if (u === "%" || u === "×") return `${v}${u}`;
    if (u === "K shares") return `${v}K`;
    return String(v);
}

function scrActiveCount(filters) {
    let n = Object.values(filters.ranges || {}).filter(([lo, hi]) => lo !== null || hi !== null).length;
    n += Object.values(filters.selects || {}).filter(Boolean).length;
    return n + (filters.earnings ? 1 : 0);
}

// The current filters as a saved screen (deep-copied, so later edits don't leak into it).
function scrScreenFrom(name, filters, sort, view) {
    return {
        name: name.trim().slice(0, 60),
        filters: JSON.parse(JSON.stringify({ ranges: filters.ranges || {}, selects: filters.selects || {},
            earnings: filters.earnings || "", search: filters.search || "" })),
        sort: { col: sort.col, dir: sort.dir === 1 ? 1 : -1 },
        view: view || "overview",
        seen: null,
        seen_at: null,
    };
}

// Which stocks a saved screen matches now, and which of them it didn't match last time.
// A screen that has never been looked at (seen null) has nothing "new" yet.
function scrScreenStatus(rows, screen, today) {
    const matches = rows.filter(r => scrMatches(r, screen.filters, today)).map(r => r.symbol);
    if (!Array.isArray(screen.seen)) return { matches, fresh: [] };
    const seen = new Set(screen.seen);
    return { matches, fresh: matches.filter(s => !seen.has(s)) };
}

// The screen after it has been looked at: today's matches become the baseline.
function scrMarkSeen(screen, matches, asOf) {
    return { ...screen, seen: matches.length <= SCR_SEEN_MAX ? [...matches].sort() : null, seen_at: asOf || null };
}

// ---------- window ----------

function initScreener() {
    const modal = document.getElementById("screener-modal");
    if (!modal) return;
    document.getElementById("open-screener-btn").addEventListener("click", openScreener);
    document.getElementById("close-screener-btn").addEventListener("click", closeScreener);
    modal.addEventListener("click", e => { if (e.target.id === "screener-modal") closeScreener(); });
    document.addEventListener("keydown", e => {
        if (e.key === "Escape" && modal.style.display === "flex") closeScreener();
    });

    const presets = document.getElementById("scr-preset");
    presets.innerHTML = `<option value="">Preset screens…</option>` +
        SCR_PRESETS.map(p => `<option value="${p.id}">${escapeHtml(p.label)}</option>`).join("");
    presets.addEventListener("change", () => { scrApplyPreset(presets.value); });

    document.getElementById("scr-search").addEventListener("input", e => {
        scrState.filters.search = e.target.value;
        scrRefresh(true);
    });
    document.getElementById("scr-reset").addEventListener("click", scrReset);
    scrInitSaved();
    document.getElementById("scr-export").addEventListener("click", scrExport);
    document.getElementById("scr-filters-toggle").addEventListener("click", () => {
        document.getElementById("scr-body").classList.toggle("scr-filters-open");
    });
    document.querySelectorAll(".scr-view").forEach(b => b.addEventListener("click", () => {
        scrState.view = b.dataset.view;
        document.querySelectorAll(".scr-view").forEach(x => x.classList.toggle("active", x === b));
        scrRenderTable();
    }));
    document.getElementById("scr-prev").addEventListener("click", () => { scrState.page--; scrRenderTable(); });
    document.getElementById("scr-next").addEventListener("click", () => { scrState.page++; scrRenderTable(); });
    document.getElementById("scr-head").addEventListener("click", e => {
        const th = e.target.closest("th[data-col]");
        if (!th) return;
        const col = th.dataset.col;
        const s = scrState.sort;
        if (s.col === col) s.dir = -s.dir;
        else { s.col = col; s.dir = SCR_FIELDS[col].kind === "text" ? 1 : -1; }
        scrRefresh(false);
    });
    document.getElementById("scr-body-rows").addEventListener("click", e => {
        const cell = e.target.closest("[data-symbol]");
        if (!cell) return;
        closeScreener();
        if (typeof switchSymbol === "function") switchSymbol(cell.dataset.symbol);
    });
    document.getElementById("scr-chips").addEventListener("click", e => {
        const chip = e.target.closest("[data-clear]");
        if (!chip) return;
        const [type, field] = chip.dataset.clear.split(":");
        if (type === "range") delete scrState.filters.ranges[field];
        if (type === "select") delete scrState.filters.selects[field];
        if (type === "earnings") scrState.filters.earnings = "";
        scrSyncInputs();
        scrRefresh(true);
    });
    scrBuildFilterPanel();
}

function openScreener() {
    document.getElementById("screener-modal").style.display = "flex";
    if (!scrState.loading && !document.getElementById("scr-asof").textContent) scrLoad();
}

function closeScreener() {
    document.getElementById("screener-modal").style.display = "none";
}

let scrDataPromise = null;
function scrFetchData() {
    if (!scrDataPromise) {
        scrDataPromise = fetch(SCREENER_URL, { cache: "no-cache" }).then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }).then(data => {
            scrState.meta = data;
            scrState.rows = scrRows(data);
            return data;
        }).catch(e => { scrDataPromise = null; throw e; });
    }
    return scrDataPromise;
}

async function scrLoad() {
    scrState.loading = true;
    const body = document.getElementById("scr-body-rows");
    body.innerHTML = `<tr><td colspan="12" class="screener-loading"><div class="loading-spinner"></div>
        Loading every US-listed stock…</td></tr>`;
    try {
        const data = await scrFetchData();
        scrPopulateSelects();
        scrRenderSaved();
        const asOf = data.prices_as_of ? new Date(data.prices_as_of + "T12:00:00Z")
            .toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
        document.getElementById("scr-asof").textContent =
            `${scrState.rows.length.toLocaleString()} stocks · prices as of the ${asOf} close`;
        scrRefresh(true);
    } catch (e) {
        body.innerHTML = `<tr><td colspan="12" class="feed-empty">The screener data could not be loaded (${escapeHtml(e.message)}). Try again in a moment.</td></tr>`;
    } finally {
        scrState.loading = false;
    }
}

function scrRangeInput(field) {
    const m = SCR_FIELDS[field];
    return `<div class="scr-filter">
        <label class="filter-label" title="${escapeHtml(m.unit || "")}">${escapeHtml(m.label)}${m.unit ? ` <span class="scr-unit">${escapeHtml(m.unit)}</span>` : ""}</label>
        <div class="filter-range">
            <input type="number" class="filter-input scr-range" data-field="${field}" data-end="0" placeholder="Min" step="any" aria-label="${escapeHtml(m.label)} minimum">
            <span class="filter-sep">–</span>
            <input type="number" class="filter-input scr-range" data-field="${field}" data-end="1" placeholder="Max" step="any" aria-label="${escapeHtml(m.label)} maximum">
        </div></div>`;
}

function scrBuildFilterPanel() {
    const panel = document.getElementById("scr-filters");
    panel.innerHTML = SCR_GROUPS.map((g, i) => `
        <details class="scr-group" data-group="${g.id}"${i === 0 ? " open" : ""}>
            <summary>${escapeHtml(g.label)} <span class="badge scr-group-count" data-group-count="${g.id}"></span></summary>
            <div class="scr-group-body">
                ${(g.selects || []).map(f => `<div class="scr-filter">
                    <label class="filter-label">${escapeHtml(SCR_FIELDS[f].label)}</label>
                    <select class="filter-select scr-select" data-field="${f}"><option value="">Any</option></select></div>`).join("")}
                ${g.earnings ? `<div class="scr-filter"><label class="filter-label">Earnings</label>
                    <select class="filter-select" id="scr-earnings"><option value="">Any time</option>
                    <option value="week">Within a week</option><option value="two_weeks">Within two weeks</option>
                    <option value="month">Within a month</option></select></div>` : ""}
                ${g.ranges.map(scrRangeInput).join("")}
            </div>
        </details>`).join("");
    panel.addEventListener("input", e => {
        const el = e.target;
        if (!el.classList.contains("scr-range")) return;
        const field = el.dataset.field;
        const cur = scrState.filters.ranges[field] || [null, null];
        const v = el.value === "" ? null : Number(el.value);
        cur[Number(el.dataset.end)] = Number.isFinite(v) ? v : null;
        scrState.filters.ranges[field] = cur;
        document.getElementById("scr-preset").value = "";
        scrRefresh(true);
    });
    panel.addEventListener("change", e => {
        const el = e.target;
        if (el.classList.contains("scr-select")) {
            scrState.filters.selects[el.dataset.field] = el.value;
            if (el.dataset.field === "sector") {
                delete scrState.filters.selects.industry;
                scrPopulateIndustries();
            }
        } else if (el.id === "scr-earnings") {
            scrState.filters.earnings = el.value;
        } else return;
        document.getElementById("scr-preset").value = "";
        scrRefresh(true);
    });
}

function scrOptions(values) {
    return [...new Set(values.filter(Boolean))].sort().map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("");
}

function scrPopulateSelects() {
    const rows = scrState.rows;
    for (const field of ["exchange", "sector"]) {
        document.querySelector(`.scr-select[data-field="${field}"]`).innerHTML =
            `<option value="">Any</option>` + scrOptions(rows.map(r => r[field]));
    }
    document.querySelector(`.scr-select[data-field="country"]`).innerHTML =
        `<option value="">Any</option><option value="United States">United States</option>` +
        `<option value="__non_us">Outside the US</option>` +
        scrOptions(rows.map(r => r.country).filter(c => c !== "United States"));
    scrPopulateIndustries();
}

function scrPopulateIndustries() {
    const sector = scrState.filters.selects.sector;
    const rows = sector ? scrState.rows.filter(r => r.sector === sector) : scrState.rows;
    document.querySelector(`.scr-select[data-field="industry"]`).innerHTML =
        `<option value="">Any</option>` + scrOptions(rows.map(r => r.industry));
}

// Put the inputs back in step with scrState.filters (after a preset or chip removal).
function scrSyncInputs() {
    document.querySelectorAll(".scr-range").forEach(el => {
        const r = scrState.filters.ranges[el.dataset.field];
        const v = r ? r[Number(el.dataset.end)] : null;
        el.value = v === null || v === undefined ? "" : v;
    });
    document.querySelectorAll(".scr-select").forEach(el => {
        el.value = scrState.filters.selects[el.dataset.field] || "";
    });
    const e = document.getElementById("scr-earnings");
    if (e) e.value = scrState.filters.earnings || "";
}

function scrApplyPreset(id) {
    const p = SCR_PRESETS.find(x => x.id === id);
    scrState.filters = { ranges: {}, selects: {}, earnings: "", search: scrState.filters.search };
    if (p) {
        for (const [f, r] of Object.entries(p.ranges)) scrState.filters.ranges[f] = [...r];
        if (p.sort) scrState.sort = { col: p.sort[0], dir: p.sort[1] };
        // Show the columns the preset is about.
        const fields = Object.keys(p.ranges);
        const view = Object.keys(SCR_VIEWS).find(v => fields.every(f => SCR_VIEWS[v].includes(f) || f === "market_cap" || f === "avg_volume")) || "overview";
        scrState.view = view;
        document.querySelectorAll(".scr-view").forEach(x => x.classList.toggle("active", x.dataset.view === view));
    }
    scrPopulateIndustries();
    scrSyncInputs();
    scrRefresh(true);
}

function scrReset() {
    scrState.filters = { ranges: {}, selects: {}, earnings: "", search: "" };
    scrState.sort = { col: "market_cap", dir: -1 };
    document.getElementById("scr-search").value = "";
    document.getElementById("scr-preset").value = "";
    scrSetActive(null);
    if (scrState.rows) scrPopulateIndustries();
    scrSyncInputs();
    scrRefresh(true);
}

function scrRefresh(resetPage) {
    if (!scrState.rows) return;
    const today = new Date().toISOString().slice(0, 10);
    let matched = scrState.rows.filter(r => scrMatches(r, scrState.filters, today));
    if (scrState.onlyNew && scrState.fresh.size) matched = matched.filter(r => scrState.fresh.has(r.symbol));
    scrState.filtered = scrSort(matched, scrState.sort.col, scrState.sort.dir);
    if (resetPage) scrState.page = 0;
    document.getElementById("screener-count").textContent =
        `${scrState.filtered.length.toLocaleString()} of ${scrState.rows.length.toLocaleString()}`;
    for (const g of SCR_GROUPS) {
        const n = scrActiveCount({
            ranges: Object.fromEntries(Object.entries(scrState.filters.ranges).filter(([f]) => g.ranges.includes(f))),
            selects: Object.fromEntries(Object.entries(scrState.filters.selects).filter(([f]) => (g.selects || []).includes(f))),
            earnings: g.earnings ? scrState.filters.earnings : "",
        });
        const el = document.querySelector(`[data-group-count="${g.id}"]`);
        if (el) el.textContent = n ? String(n) : "";
    }
    scrRenderChips();
    scrRenderTable();
}

function scrRenderChips() {
    const f = scrState.filters;
    const chips = [];
    for (const [field, [lo, hi]] of Object.entries(f.ranges)) {
        if (lo === null && hi === null) continue;
        const m = SCR_FIELDS[field];
        const txt = lo !== null && hi !== null ? `${scrUnitValue(lo, m)}–${scrUnitValue(hi, m)}`
            : lo !== null ? `≥ ${scrUnitValue(lo, m)}` : `≤ ${scrUnitValue(hi, m)}`;
        chips.push(`<button class="scr-chip" data-clear="range:${field}">${escapeHtml(m.label)} ${escapeHtml(txt)} <span aria-hidden="true">✕</span></button>`);
    }
    for (const [field, v] of Object.entries(f.selects)) {
        if (!v) continue;
        chips.push(`<button class="scr-chip" data-clear="select:${field}">${escapeHtml(SCR_FIELDS[field].label)}: ${escapeHtml(v === "__non_us" ? "outside the US" : v)} <span aria-hidden="true">✕</span></button>`);
    }
    if (f.earnings) chips.push(`<button class="scr-chip" data-clear="earnings:">Earnings ${escapeHtml({ week: "within a week", two_weeks: "within two weeks", month: "within a month" }[f.earnings])} <span aria-hidden="true">✕</span></button>`);
    document.getElementById("scr-chips").innerHTML = chips.join("");
}

function scrRenderTable() {
    if (!scrState.rows) return;
    const cols = SCR_VIEWS[scrState.view];
    const { col: sortCol, dir } = scrState.sort;
    document.getElementById("scr-head").innerHTML = `<tr>${cols.map(c => {
        const on = c === sortCol;
        const num = SCR_FIELDS[c].kind !== "text";
        return `<th data-col="${c}" class="sortable${on ? " sorted" : ""}${num ? " scr-num" : ""}">${escapeHtml(SCR_FIELDS[c].label)} <span class="sort-icon">${on ? (dir === 1 ? "↑" : "↓") : "↕"}</span></th>`;
    }).join("")}</tr>`;

    const rows = scrState.filtered;
    const pages = Math.max(1, Math.ceil(rows.length / SCR_PAGE));
    scrState.page = Math.min(Math.max(scrState.page, 0), pages - 1);
    const slice = rows.slice(scrState.page * SCR_PAGE, (scrState.page + 1) * SCR_PAGE);
    const body = document.getElementById("scr-body-rows");
    body.innerHTML = slice.length ? slice.map(r => `<tr class="screener-row">${cols.map(c => {
        const m = SCR_FIELDS[c];
        const v = r[c];
        if (c === "symbol") return `<td class="sc-symbol" data-symbol="${escapeHtml(r.symbol)}" title="Open ${escapeHtml(r.symbol)} on the chart">${escapeHtml(r.symbol)}${scrState.fresh.has(r.symbol) ? ` <span class="scr-new-tag">New</span>` : ""}</td>`;
        if (m.kind === "text") return `<td class="scr-text" title="${escapeHtml(v || "")}">${escapeHtml(v || "—")}</td>`;
        const cls = m.kind === "signed" && v !== null && v !== undefined ? (v > 0 ? " positive" : v < 0 ? " negative" : "") : "";
        return `<td class="scr-num${cls}">${scrFormat(v, m.kind)}</td>`;
    }).join("")}</tr>`).join("")
        : `<tr><td colspan="${cols.length}" class="feed-empty">No stocks match these filters.</td></tr>`;
    document.getElementById("scr-page").textContent = `Page ${scrState.page + 1} of ${pages}`;
    document.getElementById("scr-prev").disabled = scrState.page === 0;
    document.getElementById("scr-next").disabled = scrState.page >= pages - 1;
}

function scrExport() {
    if (!scrState.filtered.length) return;
    const csv = scrCsv(scrState.filtered, scrState.meta.fields);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `tradeski-screener-${scrState.meta.prices_as_of || "export"}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.addEventListener("DOMContentLoaded", initScreener);


// ---------- saved screens ----------
// Signed in: stored on the account (GET/PUT /screens). Signed out: this browser.
// Each screen keeps the symbols it matched when last opened; after the nightly
// rebuild, anything outside that list is "new" (badge on the Screener button,
// "New" tag in the table).

function scrSignedIn() {
    return typeof getToken === "function" && !!getToken() && typeof CFG !== "undefined";
}

function scrLocalScreens() {
    try {
        const v = JSON.parse(localStorage.getItem(SCR_SCREENS_KEY) || "[]");
        return Array.isArray(v) ? v : [];
    } catch (_) { return []; }
}

async function scrLoadScreens() {
    const local = scrLocalScreens();
    if (!scrSignedIn()) return local;
    try {
        const res = await fetch(`${CFG.API}/screens`);
        if (!res.ok) return local;
        const server = (await res.json()).screens || [];
        if (!server.length && local.length) {
            // First sign-in on this browser: move its screens to the account.
            if (await scrPutScreens(local)) { localStorage.removeItem(SCR_SCREENS_KEY); return local; }
        }
        return server;
    } catch (_) { return local; }
}

async function scrPutScreens(list) {
    try {
        const res = await fetch(`${CFG.API}/screens`, {
            method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ screens: list }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            scrSavedMessage(err.error || `Couldn't save (HTTP ${res.status}).`, true);
            return false;
        }
        return true;
    } catch (_) {
        scrSavedMessage("Couldn't reach the server; your change isn't saved.", true);
        return false;
    }
}

async function scrStoreScreens(list) {
    scrState.screens = list;
    scrRenderSaved();
    if (scrSignedIn()) return scrPutScreens(list);
    try { localStorage.setItem(SCR_SCREENS_KEY, JSON.stringify(list)); return true; }
    catch (_) { scrSavedMessage("This browser wouldn't store the screen.", true); return false; }
}

function scrSavedMessage(html, isError) {
    const el = document.getElementById("scr-saved-note");
    if (!el) return;
    el.hidden = !html;
    el.classList.toggle("scr-saved-error", !!isError);
    el.innerHTML = html || "";
}

function scrToday() { return new Date().toISOString().slice(0, 10); }

function scrRenderSaved() {
    const sel = document.getElementById("scr-saved");
    if (!sel) return;
    const rows = scrState.rows;
    const today = scrToday();
    sel.innerHTML = `<option value="">${scrState.screens.length ? "Your saved screens…" : "No saved screens yet"}</option>` +
        scrState.screens.map(s => {
            const n = rows ? scrScreenStatus(rows, s, today).fresh.length : 0;
            return `<option value="${escapeHtml(s.name)}">${escapeHtml(s.name)}${n ? ` · ${n} new` : ""}</option>`;
        }).join("");
    sel.value = scrState.active || "";
    sel.disabled = !scrState.screens.length;
    document.getElementById("scr-delete").hidden = !scrState.active;
    scrUpdateBadge();
}

function scrUpdateBadge() {
    const badge = document.getElementById("scr-new-badge");
    if (!badge) return;
    const rows = scrState.rows;
    const today = scrToday();
    const n = rows ? scrState.screens.reduce((t, s) => t + scrScreenStatus(rows, s, today).fresh.length, 0) : 0;
    badge.hidden = !n;
    badge.textContent = n ? `${n > 99 ? "99+" : n} new` : "";
    const btn = document.getElementById("open-screener-btn");
    if (btn) btn.title = n ? `Stock screener: ${n} new match${n === 1 ? "" : "es"} in your saved screens` : "Stock Screener";
}

function scrSetActive(name) {
    scrState.active = name;
    scrState.fresh = new Set();
    scrState.onlyNew = false;
    scrSavedMessage("");
    const sel = document.getElementById("scr-saved");
    if (sel) sel.value = name || "";
    const del = document.getElementById("scr-delete");
    if (del) del.hidden = !name;
}

async function scrOpenSaved(name) {
    const i = scrState.screens.findIndex(s => s.name === name);
    if (i < 0 || !scrState.rows) { scrSetActive(null); return; }
    const screen = scrState.screens[i];
    scrState.filters = JSON.parse(JSON.stringify(screen.filters));
    scrState.sort = { ...screen.sort };
    scrState.view = SCR_VIEWS[screen.view] ? screen.view : "overview";
    document.querySelectorAll(".scr-view").forEach(x => x.classList.toggle("active", x.dataset.view === scrState.view));
    document.getElementById("scr-search").value = scrState.filters.search || "";
    document.getElementById("scr-preset").value = "";
    scrPopulateIndustries();
    scrSyncInputs();

    const { matches, fresh } = scrScreenStatus(scrState.rows, screen, scrToday());
    scrSetActive(name);
    scrState.fresh = new Set(fresh);
    const since = screen.seen_at ? new Date(screen.seen_at + "T12:00:00Z")
        .toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "";
    if (fresh.length) {
        scrSavedMessage(`<strong>${fresh.length} new</strong> since ${escapeHtml(since || "you last opened it")}.
            <button class="text-btn" id="scr-only-new" type="button">Show only new</button>`);
    } else if (matches.length > SCR_SEEN_MAX) {
        scrSavedMessage(`${matches.length.toLocaleString()} matches: too broad to track new ones. Narrow it to under ${SCR_SEEN_MAX.toLocaleString()}.`);
    } else if (Array.isArray(screen.seen)) {
        scrSavedMessage(`Nothing new since ${escapeHtml(since)}.`);
    }
    scrRefresh(true);

    // Today's matches become the baseline for next time.
    const asOf = scrState.meta && scrState.meta.prices_as_of;
    const updated = scrMarkSeen(screen, matches, asOf);
    if (JSON.stringify(updated.seen) !== JSON.stringify(screen.seen) || updated.seen_at !== screen.seen_at) {
        const list = scrState.screens.slice();
        list[i] = updated;
        await scrStoreScreens(list);
        // The tags stay up for this visit; the counts in the menu and badge drop to zero.
    }
}

async function scrSaveCurrent(name) {
    name = (name || "").trim();
    if (!name) return;
    if (!scrState.rows) return;
    const list = scrState.screens.slice();
    const existing = list.findIndex(s => s.name.toLowerCase() === name.toLowerCase());
    if (existing < 0 && list.length >= SCR_SCREENS_MAX) {
        scrSavedMessage(`You can save up to ${SCR_SCREENS_MAX} screens; delete one first.`, true);
        return;
    }
    const { matches } = scrScreenStatus(scrState.rows, { filters: scrState.filters, seen: null }, scrToday());
    const screen = scrMarkSeen(scrScreenFrom(name, scrState.filters, scrState.sort, scrState.view), matches,
        scrState.meta && scrState.meta.prices_as_of);
    if (existing >= 0) list[existing] = screen; else list.push(screen);
    if (await scrStoreScreens(list)) {
        scrSetActive(screen.name);
        const where = scrSignedIn() ? "to your account" : "in this browser (sign in to keep it across devices)";
        scrSavedMessage(`Saved ${where}. New matches will be flagged after each daily update.`);
    }
}

async function scrDeleteActive() {
    if (!scrState.active) return;
    const list = scrState.screens.filter(s => s.name !== scrState.active);
    scrSetActive(null);
    await scrStoreScreens(list);
    scrRefresh(false);
}

function scrInitSaved() {
    const form = document.getElementById("scr-save-form");
    const nameInput = document.getElementById("scr-save-name");
    const saveBtn = document.getElementById("scr-save");
    const closeForm = () => { form.hidden = true; saveBtn.hidden = false; };
    saveBtn.addEventListener("click", () => {
        form.hidden = false;
        saveBtn.hidden = true;
        nameInput.value = scrState.active || "";
        nameInput.focus();
    });
    document.getElementById("scr-save-cancel").addEventListener("click", closeForm);
    const submit = async () => { await scrSaveCurrent(nameInput.value); closeForm(); };
    document.getElementById("scr-save-ok").addEventListener("click", submit);
    nameInput.addEventListener("keydown", e => {
        if (e.key === "Enter") submit();
        if (e.key === "Escape") { e.stopPropagation(); closeForm(); }
    });
    document.getElementById("scr-saved").addEventListener("change", e => {
        if (e.target.value) scrOpenSaved(e.target.value); else { scrSetActive(null); scrRefresh(false); }
    });
    document.getElementById("scr-delete").addEventListener("click", scrDeleteActive);
    document.getElementById("scr-saved-note").addEventListener("click", e => {
        if (e.target.id !== "scr-only-new") return;
        scrState.onlyNew = !scrState.onlyNew;
        e.target.textContent = scrState.onlyNew ? "Show all matches" : "Show only new";
        scrRefresh(true);
    });
    scrOnAuthChange();
}

// Load the screens; if any are being tracked, fetch the data in the background
// so the Screener button can say how many new matches are waiting.
async function scrOnAuthChange() {
    scrState.screens = await scrLoadScreens();
    if (scrState.active && !scrState.screens.some(s => s.name === scrState.active)) scrSetActive(null);
    scrRenderSaved();
    if (!scrState.rows && scrState.screens.some(s => Array.isArray(s.seen))) {
        setTimeout(() => { scrFetchData().then(scrRenderSaved).catch(() => {}); }, 3000);
    }
}
