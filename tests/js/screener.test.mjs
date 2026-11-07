// Unit tests for the pure helpers in frontend/screener.js: turning the data
// file into rows, filters, sorting, formatting and CSV export. Loaded straight
// out of the shipped file, like dashboard.test.mjs.
//
//   node --test tests/js/*.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(new URL("../../frontend/screener.js", import.meta.url), "utf8");

function declaration(head) {
    const start = src.indexOf(head);
    assert.ok(start >= 0, `not found in screener.js: ${head}`);
    const rest = src.slice(start);
    const end = head.startsWith("function") ? rest.search(/\n}\s*(\n|$)/) + 2 : rest.search(/\n};\s*(\n|$)/) + 3;
    return rest.slice(0, end);
}

const heads = ["const SCR_FIELDS", "function scrRows", "function scrDaysUntil", "function scrMatches",
               "function scrSort", "function scrFormat", "function scrCsv", "function scrActiveCount",
               "function scrUnitValue", "function scrScreenFrom", "function scrScreenStatus", "function scrMarkSeen"];
const seenMax = src.match(/^const SCR_SEEN_MAX = \d+;/m)[0];
const ctx = vm.createContext({});
vm.runInContext(seenMax + "\n" + heads.map(declaration).join("\n") +
    "\nthis.__x = { scrRows, scrMatches, scrSort, scrFormat, scrCsv, scrActiveCount, scrUnitValue," +
    " scrScreenFrom, scrScreenStatus, scrMarkSeen, SCR_SEEN_MAX };", ctx);
const { scrRows, scrMatches, scrSort, scrFormat, scrCsv, scrActiveCount, scrUnitValue,
        scrScreenFrom, scrScreenStatus, scrMarkSeen, SCR_SEEN_MAX } = ctx.__x;
const plain = (v) => JSON.parse(JSON.stringify(v));

const data = {
    fields: ["symbol", "name", "sector", "country", "market_cap", "pe", "change", "earnings_date"],
    rows: [
        ["AAPL", "Apple Inc.", "Technology", "United States", 4.9e12, 38.1, -0.5, "2026-11-10"],
        ["TSM", "Taiwan Semiconductor", "Technology", "Taiwan", 1.1e12, 24.0, 1.2, null],
        ["XOM", "Exxon Mobil", "Energy", "United States", 4.5e11, 13.9, 2.1, "2026-12-30"],
        ["LOSS", "Loss Co", "Healthcare", "United States", 3e8, null, -7.5, "2026-11-20"],
    ],
};
const rows = scrRows(data);
const none = { ranges: {}, selects: {}, earnings: "", search: "" };
const pick = (f) => rows.filter(r => scrMatches(r, { ...none, ...f }, "2026-11-07")).map(r => r.symbol);

test("the columnar file becomes one object per stock", () => {
    assert.equal(rows.length, 4);
    assert.deepEqual(plain(rows[0]), { symbol: "AAPL", name: "Apple Inc.", sector: "Technology",
        country: "United States", market_cap: 4.9e12, pe: 38.1, change: -0.5, earnings_date: "2026-11-10" });
});

test("ranges use the input units, and a missing value never passes", () => {
    assert.deepEqual(plain(pick({ ranges: { market_cap: [1000, null] } })), ["AAPL", "TSM"]);   // $B
    assert.deepEqual(plain(pick({ ranges: { pe: [null, 15] } })), ["XOM"]);                     // not LOSS
    assert.deepEqual(plain(pick({ ranges: { change: [-1, 1.5] } })), ["AAPL", "TSM"]);
    assert.deepEqual(plain(pick({ ranges: { pe: [null, null] } })), ["AAPL", "TSM", "XOM", "LOSS"]);
});

test("selects, outside-the-US, earnings windows and search", () => {
    assert.deepEqual(plain(pick({ selects: { sector: "Technology" } })), ["AAPL", "TSM"]);
    assert.deepEqual(plain(pick({ selects: { country: "__non_us" } })), ["TSM"]);
    assert.deepEqual(plain(pick({ earnings: "week" })), ["AAPL"]);
    assert.deepEqual(plain(pick({ earnings: "two_weeks" })), ["AAPL", "LOSS"]);
    assert.deepEqual(plain(pick({ search: "ex" })), ["XOM"]);       // company name
    assert.deepEqual(plain(pick({ search: "ts" })), ["TSM"]);       // symbol prefix
});

test("sorting puts missing values last in both directions", () => {
    assert.deepEqual(plain(scrSort(rows, "pe", 1).map(r => r.symbol)), ["XOM", "TSM", "AAPL", "LOSS"]);
    assert.deepEqual(plain(scrSort(rows, "pe", -1).map(r => r.symbol)), ["AAPL", "TSM", "XOM", "LOSS"]);
    assert.deepEqual(plain(scrSort(rows, "name", 1).map(r => r.symbol)), ["AAPL", "XOM", "LOSS", "TSM"]);
});

test("formatting", () => {
    assert.equal(scrFormat(4.9e12, "cap"), "$4.90T");
    assert.equal(scrFormat(4.5e11, "cap"), "$450.0B");
    assert.equal(scrFormat(2.5, "signed"), "+2.50%");
    assert.equal(scrFormat(-150, "signed"), "-150%");
    assert.equal(scrFormat(44676300, "vol"), "44.68M");
    assert.equal(scrFormat(342.37, "money"), "$342.37");
    assert.equal(scrFormat(null, "ratio"), "—");
});

test("CSV export quotes what needs quoting", () => {
    const csv = scrCsv([{ symbol: "BRK-B", name: 'Berkshire "B", Inc.', pe: null }], ["symbol", "name", "pe"]);
    assert.equal(csv, 'symbol,name,pe\nBRK-B,"Berkshire ""B"", Inc.",');
});

test("filter chips show bounds in their units", () => {
    assert.equal(scrUnitValue(10, { unit: "$B" }), "$10B");
    assert.equal(scrUnitValue(5, { unit: "$" }), "$5");
    assert.equal(scrUnitValue(30, { unit: "%" }), "30%");
    assert.equal(scrUnitValue(500, { unit: "K shares" }), "500K");
    assert.equal(scrUnitValue(40, {}), "40");
});

test("active filter count", () => {
    assert.equal(scrActiveCount({ ranges: { pe: [null, 15], rsi: [null, null] }, selects: { sector: "Energy", country: "" },
                                   earnings: "week" }), 3);
});

test("a saved screen copies the filters instead of sharing them", () => {
    const filters = { ranges: { pe: [null, 15] }, selects: { sector: "Energy" }, earnings: "", search: "" };
    const saved = scrScreenFrom("  Cheap energy ", filters, { col: "pe", dir: 1 }, "valuation");
    filters.ranges.pe[1] = 99;
    assert.equal(saved.name, "Cheap energy");
    assert.deepEqual(plain(saved.filters.ranges), { pe: [null, 15] });
    assert.deepEqual(plain(saved.sort), { col: "pe", dir: 1 });
    assert.equal(saved.seen, null);
});

test("new matches are the ones outside last time's list", () => {
    const tech = scrScreenFrom("Tech", { ...none, selects: { sector: "Technology" } }, { col: "market_cap", dir: -1 });
    // Never opened: nothing counts as new yet.
    assert.deepEqual(plain(scrScreenStatus(rows, tech, "2026-11-07")), { matches: ["AAPL", "TSM"], fresh: [] });
    const looked = scrMarkSeen(tech, ["AAPL"], "2026-11-06");
    assert.deepEqual(plain(looked.seen), ["AAPL"]);
    assert.equal(looked.seen_at, "2026-11-06");
    assert.deepEqual(plain(scrScreenStatus(rows, looked, "2026-11-07").fresh), ["TSM"]);
    // Opening it again makes today's matches the baseline.
    const again = scrMarkSeen(looked, ["TSM", "AAPL"], "2026-11-07");
    assert.deepEqual(plain(again.seen), ["AAPL", "TSM"]);
    assert.deepEqual(plain(scrScreenStatus(rows, again, "2026-11-07").fresh), []);
});

test("a screen too broad to track stores no baseline", () => {
    const many = Array.from({ length: SCR_SEEN_MAX + 1 }, (_, i) => `S${i}`);
    assert.equal(scrMarkSeen({ name: "All" }, many, "2026-11-07").seen, null);
});
