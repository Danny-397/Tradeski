// Unit tests for the pure helpers in frontend/options.js: chain filters,
// money formatting and the leg descriptions sent to Ski.
//
// Like dashboard.test.mjs, each helper is loaded straight out of the shipped
// file, so the tests exercise the deployed code, not a copy.
//
//   node --test tests/js/*.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(new URL("../../frontend/options.js", import.meta.url), "utf8");

// A top-level function in options.js ends with "}" in column 0.
function declaration(name) {
    const start = src.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `not found in options.js: ${name}`);
    const rest = src.slice(start);
    return rest.slice(0, rest.search(/\n}\s*(\n|$)/) + 2);
}

function load(names) {
    const ctx = vm.createContext({});
    vm.runInContext(names.map(declaration).join("\n") + `\nthis.__x = { ${names.join(", ")} };`, ctx);
    return ctx.__x;
}

const plain = (v) => JSON.parse(JSON.stringify(v));
const { optChainRows, optPasses, optMoney, optPct, optLegText, optNum, optIvRank } =
    load(["optNum", "optPasses", "optChainRows", "optMoney", "optPct", "optLegText", "optIvRank"]);

const NO_FILTERS = { windowPct: null, side: "both", deltaMin: null, deltaMax: null,
                     minOi: null, minVol: null, maxSpread: null };

function contract(strike, type, extra = {}) {
    return { strike, type, delta: type === "call" ? 0.5 : -0.5, open_interest: 500, volume: 50,
             spread_pct: 5, ...extra };
}

const chain = {
    spot: 100,
    calls: [contract(80, "call", { delta: 0.95 }), contract(100, "call"), contract(120, "call", { delta: 0.1, open_interest: 20 })],
    puts:  [contract(80, "put", { delta: -0.05 }), contract(100, "put", { spread_pct: null }), contract(120, "put", { delta: -0.9 })],
};

test("optNum treats blanks as no filter and rejects non-numbers", () => {
    assert.equal(optNum(""), null);
    assert.equal(optNum(null), null);
    assert.equal(optNum("0.3"), 0.3);
    assert.equal(optNum("abc"), null);
});

test("with no filters every strike is shown with both sides", () => {
    const rows = optChainRows(chain, NO_FILTERS);
    assert.deepEqual(plain(rows.map(r => r.strike)), [80, 100, 120]);
    assert.ok(rows.every(r => r.call && r.put));
});

test("strike window is a percentage around the spot", () => {
    const rows = optChainRows(chain, { ...NO_FILTERS, windowPct: 10 });
    assert.deepEqual(plain(rows.map(r => r.strike)), [100]);
});

test("delta filter uses absolute delta and blanks the failing side", () => {
    const rows = optChainRows(chain, { ...NO_FILTERS, deltaMin: 0.2, deltaMax: 0.6 });
    assert.deepEqual(plain(rows.map(r => [r.strike, !!r.call, !!r.put])), [[100, true, true]]);
});

test("open interest, spread and side filters", () => {
    let rows = optChainRows(chain, { ...NO_FILTERS, minOi: 100 });
    assert.equal(rows.find(r => r.strike === 120).call, null);          // OI 20
    rows = optChainRows(chain, { ...NO_FILTERS, maxSpread: 10 });
    assert.equal(rows.find(r => r.strike === 100).put, null);           // no quote, no spread
    rows = optChainRows(chain, { ...NO_FILTERS, side: "puts" });
    assert.ok(rows.every(r => r.call === null && r.put));
    assert.equal(optPasses(null, NO_FILTERS), false);
});

test("money and percent formatting", () => {
    assert.equal(optMoney(32430.5), "$32,431");
    assert.equal(optMoney(-755), "-$755");
    assert.equal(optMoney(12.5, true), "+$12.50");
    assert.equal(optMoney(null), "—");
    assert.equal(optPct(0.2646), "26.5%");
    assert.equal(optPct(0.71, 0), "71%");
});

test("IV percentile ranks today against earlier readings only", () => {
    const rows = [];
    for (let i = 0; i < 25; i++) rows.push([`2026-10-${String(i + 1).padStart(2, "0")}`, 0.20 + i * 0.01, 30]);
    rows.push(["2026-11-06", 0.99, 30]);                         // today's own reading: ignored
    const r = optIvRank(rows, 0.30, "2026-11-06", 20);
    assert.equal(r.n, 25);
    assert.equal(r.since, "2026-10-01");
    assert.equal(r.pct, 40);                                      // 0.20 .. 0.29 are below 0.30
    assert.equal(r.low, 0.2);
    assert.ok(Math.abs(r.high - 0.44) < 1e-9);
});

test("IV percentile waits for enough history", () => {
    const r = optIvRank([["2026-11-03", 0.25, 30], ["2026-11-04", 0.27, 30]], 0.3, "2026-11-06", 20);
    assert.equal(r.n, 2);
    assert.equal(r.pct, null);
    assert.equal(optIvRank(null, 0.3, "2026-11-06", 20).n, 0);
    assert.equal(optIvRank([["2026-11-03", 0.25, 30]], undefined, "2026-11-06", 20).pct, null);
});

test("leg descriptions for Ski", () => {
    assert.equal(optLegText({ type: "put", qty: -1, strike: 170 }, "NVDA"), "sell 1 NVDA 170 put");
    assert.equal(optLegText({ type: "call", qty: 2, strike: 350 }, "AAPL"), "buy 2 AAPL 350 calls");
    assert.equal(optLegText({ type: "stock", qty: 1, strike: null }, "AAPL"), "buy 100 AAPL shares");
});

test("the Options page reads its starting state from the URL", () => {
    const ctx = vm.createContext({ URLSearchParams });
    vm.runInContext('const OPT_TABS = ["chain", "strategy", "scan"];\n' + declaration("optParseQuery") +
        "\nthis.__p = optParseQuery;", ctx);
    const parse = ctx.__p;
    assert.deepEqual(plain(parse("?symbol=nvda&tab=strategy&expiry=2026-12-18")),
                     { symbol: "NVDA", tab: "strategy", expiry: "2026-12-18" });
    assert.deepEqual(plain(parse("")), { symbol: "AAPL", tab: "chain", expiry: "" });
    assert.deepEqual(plain(parse("?symbol=<b>&tab=evil&expiry=soon")), { symbol: "AAPL", tab: "chain", expiry: "" });
});

test("where a position makes money, in words", () => {
    const { optZoneText } = load(["optZoneText"]);
    assert.equal(optZoneText([[348.7, null]]), "above $348.70");
    assert.equal(optZoneText([[0, 335.1]]), "below $335.10");
    assert.equal(optZoneText([[317.55, 367.45]]), "between $317.55 and $367.45");
    assert.equal(optZoneText([[0, 94], [106, null]]), "below $94.00 or above $106.00");
    assert.equal(optZoneText([]), "at no price");
});

test("each leg as a sentence", () => {
    const { optLegPlain } = load(["optMoney", "optLegPlain"]);
    assert.equal(optLegPlain({ type: "call", qty: 1, strike: 340, price: 11.78 }, "AAPL"),
                 "Buy 1 AAPL $340 call at $11.78 a share: you pay $1,178");
    assert.equal(optLegPlain({ type: "put", qty: -2, strike: 320, price: 3.25 }, "AAPL"),
                 "Sell 2 AAPL $320 puts at $3.25 a share: you collect $650");
    assert.equal(optLegPlain({ type: "stock", qty: 1, strike: null, price: 342.37 }, "AAPL"),
                 "Buy 100 AAPL shares at $342.37: you pay $34,237");
});

test("dates, day counts and the expected range", () => {
    const { optDate, optDaysBetween, optExpectedRange } = load(["optDate", "optDaysBetween", "optExpectedRange"]);
    assert.equal(optDate("2027-01-28"), "Jan 28, 2027");
    assert.equal(optDaysBetween("2026-11-07", "2027-01-28"), 82);
    assert.deepEqual(plain(optExpectedRange({ spot: 342.37, expected_move: 25.07 })), { lo: 317.3, hi: 367.44 });
    assert.equal(optExpectedRange({ spot: 100, expected_move: null }), null);
});

test("which strategies to compare when the list loads", () => {
    const ctx = vm.createContext({});
    vm.runInContext('const OPT_COMPARE_MAX = 3; const OPT_COMPARE_DEFAULT = ["long_call", "bull_call_spread", "covered_call"];\n' +
        declaration("optCompareSelection") + "\nthis.__f = optCompareSelection;", ctx);
    const pick = ctx.__f;
    const rows = [{ preset: "bull_call_spread", pnl_at_target: 900 }, { preset: "long_call", pnl_at_target: 600 },
                  { preset: "covered_call", pnl_at_target: 300 }, { preset: "long_strangle", pnl_at_target: 50 },
                  { preset: "long_put", pnl_at_target: -400 }];
    assert.deepEqual(plain(pick(rows, null, 110)), ["bull_call_spread", "long_call", "covered_call"]);   // top three
    assert.deepEqual(plain(pick(rows, ["long_put", "gone"], 110)), ["long_put"]);                          // keep picks
    assert.deepEqual(plain(pick(rows, null, null)), ["long_call", "bull_call_spread", "covered_call"]);   // starter set
    assert.deepEqual(plain(pick([{ preset: "long_put", pnl_at_target: -1 }], null, 90)), []);             // nothing wins
});

test("the comparison chart's window, and curves clipped to it", () => {
    const { optCompareWindow, optClipCurve } = load(["optCompareWindow", "optClipCurve"]);
    const r2 = a => plain(a).map(v => +v.toFixed(2));
    assert.deepEqual(r2(optCompareWindow(100, 5, null)), [87.5, 112.5]);               // 2.5 expected moves
    assert.deepEqual(r2(optCompareWindow(100, 1, null)), [88, 112]);                   // at least ±12%
    assert.deepEqual(r2(optCompareWindow(100, 30, null)), [60, 140]);                  // at most ±40%
    assert.deepEqual(plain(optCompareWindow(100, 5, 130)).map(v => +v.toFixed(2)), [87.5, 136.5]);  // shows the target
    const c = optClipCurve([0, 10, 20, 30], [0, 100, 200, 300], 5, 25);
    assert.deepEqual(plain(c), { x: [5, 10, 20, 25], y: [50, 100, 200, 250] });
});

test("IV slider labels", () => {
    const { optIvShiftLabel, optIvTag } = load(["optIvShiftLabel", "optIvTag"]);
    assert.equal(optIvShiftLabel(0), "unchanged");
    assert.equal(optIvShiftLabel(-15), "15 points lower");
    assert.equal(optIvShiftLabel(1), "1 point higher");
    assert.equal(optIvTag(0), "");
    assert.equal(optIvTag(-15), " (IV −15)");
    assert.equal(optIvTag(5), " (IV +5)");
});

test("paper trades: saving, capping and P/L for debits and credits", () => {
    const ctx = vm.createContext({});
    vm.runInContext("const OPT_PAPER_MAX = 3;\n" + ["optPaperFrom", "optPaperAdd", "optPaperPnl"].map(declaration).join("\n") +
        "\nthis.__p = { optPaperFrom, optPaperAdd, optPaperPnl };", ctx);
    const { optPaperFrom, optPaperAdd, optPaperPnl } = ctx.__p;
    const t = optPaperFrom({ symbol: "AAPL", expiry: "2026-12-04", net_debit: 488, spot: 342.37,
        legs: [{ type: "call", qty: 1, strike: 340, price: 11.78, iv: 0.27 }] }, "Bull call spread", new Date("2026-11-07T15:00:00Z"));
    assert.equal(t.name, "Bull call spread");
    assert.deepEqual(plain(t.legs), [{ type: "call", qty: 1, strike: 340, price: 11.78 }]);   // no IV kept
    assert.equal(t.saved_at, "2026-11-07T15:00:00.000Z");
    let list = [];
    for (let i = 0; i < 5; i++) list = optPaperAdd(list, { ...t, id: "t" + i });
    assert.deepEqual(plain(list.map(x => x.id)), ["t4", "t3", "t2"]);                         // newest first, capped
    assert.deepEqual(plain(optPaperPnl(488, 600)), { pnl: 112, pct: 112 / 488 });              // bought, now worth more
    assert.deepEqual(plain(optPaperPnl(-245, -150)), { pnl: 95, pct: null });                   // sold for 245, 150 to close
    assert.deepEqual(plain(optPaperPnl(-245, -400)), { pnl: -155, pct: null });
});
