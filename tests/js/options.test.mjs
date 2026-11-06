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
const { optChainRows, optPasses, optMoney, optPct, optLegText, optNum } =
    load(["optNum", "optPasses", "optChainRows", "optMoney", "optPct", "optLegText"]);

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

test("leg descriptions for Ski", () => {
    assert.equal(optLegText({ type: "put", qty: -1, strike: 170 }, "NVDA"), "sell 1 NVDA 170 put");
    assert.equal(optLegText({ type: "call", qty: 2, strike: 350 }, "AAPL"), "buy 2 AAPL 350 calls");
    assert.equal(optLegText({ type: "stock", qty: 1, strike: null }, "AAPL"), "buy 100 AAPL shares");
});
