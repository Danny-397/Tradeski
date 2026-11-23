// Unit tests for the pure helpers in frontend/dashboard.js: ticker search,
// CSV import parsing and Ski reply formatting.
//
// dashboard.js is a browser script with no exports, so each test loads the
// functions it needs straight out of the shipped file into a sandbox. That
// way the tests always exercise the code that is deployed, not a copy.
//
//   node --test tests/js/*.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const root = new URL("../../", import.meta.url);
const src = readFileSync(new URL("frontend/dashboard.js", root), "utf8");

// The source of one top-level declaration. dashboard.js is formatted so a
// top-level function ends with "}" in column 0 and a top-level const ends on
// the first line that ends with ";". Using that layout, rather than counting
// brackets, keeps regex literals such as /[^\]]/ from confusing the slice.
function declaration(head) {
    const start = src.indexOf(head);
    assert.ok(start >= 0, `not found in dashboard.js: ${head}`);
    const rest = src.slice(start);
    const end = head.startsWith("function")
        ? rest.search(/\n}\s*(\n|$)/) + 2
        : rest.search(/;[ \t]*(\r?\n|$)/) + 1;
    assert.ok(end > 1, `unterminated: ${head}`);
    return rest.slice(0, end);
}

// Values made inside the sandbox come from another realm, so compare them as
// plain data.
const plain = (v) => JSON.parse(JSON.stringify(v));

function load(heads, globals = {}) {
    const ctx = vm.createContext({ ...globals });
    vm.runInContext(heads.map(declaration).join("\n") +
        "\nthis.__exports = { " + heads.map(h => h.match(/(?:function|const)\s+(\w+)/)[1]).join(", ") + " };", ctx);
    return ctx.__exports;
}

// ---- ticker search -----------------------------------------------------------

const symbolsJs = readFileSync(new URL("frontend/symbols.js", root), "utf8");
const SYMBOLS = JSON.parse(symbolsJs.match(/window\.TRADESKI_SYMBOLS\s*=\s*(\[.*\]);/s)[1]);
const search = () => load(
    ["const TICKER_SYMS = [", "const POPULAR_SYMS = new Set(", "function searchSymbols("],
    { window: { TRADESKI_SYMBOLS: SYMBOLS } },
).searchSymbols;

test("company names find their ticker", () => {
    const s = search();
    assert.equal(s("apple")[0].sym, "AAPL");
    assert.equal(s("nvid")[0].sym, "NVDA");
});

test("an exact symbol ranks first, and popular names win ties", () => {
    const s = search();
    assert.equal(s("F")[0].sym, "F");
    assert.equal(s("micro")[0].sym, "MSFT");
});

test("empty and unknown queries return nothing", () => {
    const s = search();
    assert.deepEqual(plain(s("")), []);
    assert.deepEqual(plain(s("zzzzqqq")), []);
});

// ---- CSV import ----------------------------------------------------------------

const csv = () => load(
    ["const CSV_IMPORT_MAX", "const CSV_COLS = {", "function parseCsvLine(", "function csvNumber(", "function parseHoldingsCsv("],
).parseHoldingsCsv;

test("reads a broker export: dollars, thousands, quoted fields, BRK.B", () => {
    const text =
        "Account,Symbol,Quantity,Cost Basis Total,Average Cost Basis\n" +
        'Z1,AAPL,12,"$2,220.00",$185.00\n' +
        "Z1,BRK.B,3,$1200,\n" +
        'Z1,MSFT,"1,000",,\n';
    const { rows, skipped, error } = csv()(text);
    assert.equal(error, null);
    assert.deepEqual(plain(rows), [
        { symbol: "AAPL", shares: 12, avg_cost: 185 },
        { symbol: "BRK-B", shares: 3, avg_cost: 400 },
        { symbol: "MSFT", shares: 1000, avg_cost: null },
    ]);
    assert.equal(skipped.length, 0);
});

test("skips cash and blank rows with a reason", () => {
    const { rows, skipped } = csv()("Symbol,Shares\nSPAXX**,\n,5\nNVDA,2\n");
    assert.deepEqual(plain(rows.map(r => r.symbol)), ["NVDA"]);
    assert.equal(skipped.length, 2);
    assert.match(skipped[0].reason, /no positive share count/);
});

test("rejects a file without symbol and share columns", () => {
    assert.match(csv()("name,amount\nx,1").error, /Symbol and Shares/);
    assert.match(csv()("").error, /empty/);
});

test("caps an import at 100 rows", () => {
    const body = Array.from({ length: 101 }, (_, i) => `T${i},1`).join("\n");
    assert.match(csv()("Symbol,Shares\n" + body).error, /up to 100/);
});

// ---- Ski reply formatting ----------------------------------------------------------

const fmt = () => load(["function escapeHtml(", "function formatSkiText("]).formatSkiText;

test("bottom line, bullets, bold and signed percentages render as a card", () => {
    const html = fmt()("**Bottom line:** Mostly NVDA.\n- NVDA is **27%** of it, up +12.5% and down -3%.");
    assert.match(html, /<div class="ski-summary">Mostly NVDA\.<\/div>/);
    assert.match(html, /<ul class="ski-list"><li>/);
    assert.match(html, /<strong>27%<\/strong>/);
    assert.match(html, /<span class="ski-up">\+12\.5%<\/span>/);
    assert.match(html, /<span class="ski-down">-3%<\/span>/);
});

test("reply text cannot inject markup; only http(s) links survive", () => {
    const html = fmt()('<img src=x onerror=alert(1)> [ok](https://example.com) [bad](javascript:alert(1))');
    assert.doesNotMatch(html, /<img/);
    assert.match(html, /&lt;img/);
    assert.match(html, /<a href="https:\/\/example\.com"/);
    assert.doesNotMatch(html, /href="javascript:/);
});

// ---- idle detection ---------------------------------------------------------

test("the page counts as idle when hidden or after 15 minutes untouched", () => {
    const { isIdle, IDLE_AFTER_MS } = load(["const IDLE_AFTER_MS =", "function isIdle("]);
    const now = 1_000_000_000;
    assert.equal(isIdle(false, now, now), false);
    assert.equal(isIdle(true, now, now), true);
    assert.equal(isIdle(false, now - IDLE_AFTER_MS + 1, now), false);
    assert.equal(isIdle(false, now - IDLE_AFTER_MS, now), true);
});

test("?symbol= opens the dashboard on that ticker, and junk is ignored", () => {
    const { symbolFromQuery } = load(["function symbolFromQuery("], { URLSearchParams });
    assert.equal(symbolFromQuery("?symbol=nvda"), "NVDA");
    assert.equal(symbolFromQuery("?symbol=BRK-B&x=1"), "BRK-B");
    assert.equal(symbolFromQuery(""), null);
    assert.equal(symbolFromQuery("?symbol=<script>"), null);
    assert.equal(symbolFromQuery("?symbol=TOOLONGSYMBOL1"), null);
});

// ---- macro ribbon ---------------------------------------------------------------

test("macro ribbon groups series in a fixed order whatever order the API sends", () => {
    const { orderedMacro } = load(["const MACRO_ORDER = [", "function orderedMacro("]);
    const api = { BAMLH0A0HYM2: 1, CES0500000003: 2, CPIAUCSL: 3, DCOILWTICO: 4, NEWSERIES: 5, UNRATE: 6 };
    assert.deepEqual(plain(orderedMacro(api).map(([sid]) => sid)),
        ["CPIAUCSL", "CES0500000003", "BAMLH0A0HYM2", "UNRATE", "DCOILWTICO", "NEWSERIES"]);
});

test("macro values stay short enough for the ribbon", () => {
    const { formatMacroValue } = load(["function formatMacroValue("]);
    assert.equal(formatMacroValue(3.121, "%"), "3.12%");
    assert.equal(formatMacroValue(4.1, "%"), "4.1%");
    assert.equal(formatMacroValue(89.53, "$"), "$89.53");
    assert.equal(formatMacroValue(165, "K"), "+165K");
    assert.equal(formatMacroValue(33010.036, "B"), "$33.0T");
    assert.equal(formatMacroValue(null, "%"), "—");
});

test("coins are found by ticker or name; a shared ticker lists the coin and the security", () => {
    const s = search();
    assert.deepEqual(plain(s("BTC").slice(0, 2).map(r => r.sym)), ["BTC-USD", "BTC"]);
    assert.equal(s("BTC")[0].score, 0);           // pre-selected, so Enter charts the coin
    assert.deepEqual(plain(s("LTC").slice(0, 2).map(r => r.sym)), ["LTC-USD", "LTC"]);
    assert.equal(s("bitcoin")[0].sym, "BTC-USD");
    assert.equal(s("ethereum")[0].sym, "ETH-USD");
    assert.equal(s("doge")[0].sym, "DOGE-USD");
});

test("crypto is recognised by its -USD spelling", () => {
    const { isCrypto } = load(["const isCrypto = "]);
    assert.equal(isCrypto("BTC-USD"), true);
    assert.equal(isCrypto("AAPL"), false);
    assert.equal(isCrypto("BRK-B"), false);
});
