"""Tests for the options maths (tracker/options.py), the /options endpoints
and Ski's options tools.

No network: chains are built here by pricing every strike with
Black-Scholes, so the right answers are known.
"""

import datetime as dt
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tracker import options as opt  # noqa: E402
from tracker import ski_tools as st  # noqa: E402

S, R, Q, SIGMA = 100.0, 0.04, 0.0, 0.25


def _expiry(days=30):
    # Days count in New York, as the code does: in the evening there, UTC is already tomorrow.
    return (dt.datetime.now(opt._ET).date() + dt.timedelta(days=days)).isoformat()


def raw_chain(days=30, sigma=SIGMA, spot=S, half_spread=0.05, oi=500):
    """A chain in the data source's shape, every strike priced at ``sigma``."""
    expiry = _expiry(days)
    T = opt.year_fraction(expiry)
    rows = {"calls": [], "puts": []}
    for i in range(25):
        K = 70.0 + 2.5 * i
        for kind in ("call", "put"):
            p = opt.bs_price(kind, spot, K, T, R, sigma, Q)
            rows[kind + "s"].append({
                "contractSymbol": f"TEST{kind[0].upper()}{K:g}", "strike": K,
                "bid": max(round(p - half_spread, 2), 0.0), "ask": round(p + half_spread, 2),
                "lastPrice": round(p, 2), "volume": 10, "openInterest": oi,
                "impliedVolatility": 0.9, "lastTradeDate": "2026-11-06 19:00:00",
            })
    return expiry, {"symbol": "TEST", "spot": spot, "dividend_yield": Q, "market_state": "REGULAR", **rows}


def chain(days=30, **kw):
    expiry, raw = raw_chain(days, **kw)
    return opt.clean_chain(raw, expiry, R)


# ── Black-Scholes ───────────────────────────────────────────

def test_black_scholes_matches_textbook_values():
    # Hull's standard example: S=K=100, T=1, r=5%, sigma=20%.
    assert opt.bs_price("call", 100, 100, 1.0, 0.05, 0.2) == pytest.approx(10.4506, abs=1e-4)
    assert opt.bs_price("put", 100, 100, 1.0, 0.05, 0.2) == pytest.approx(5.5735, abs=1e-4)


@pytest.mark.parametrize("K", [80, 100, 125])
def test_put_call_parity_with_dividends(K):
    T, r, q, sig = 0.5, 0.03, 0.02, 0.3
    c = opt.bs_price("call", S, K, T, r, sig, q)
    p = opt.bs_price("put", S, K, T, r, sig, q)
    assert c - p == pytest.approx(S * math.exp(-q * T) - K * math.exp(-r * T), abs=1e-9)


@pytest.mark.parametrize("kind", ["call", "put"])
def test_greeks_match_finite_differences(kind):
    K, T, r, sig, q, h = 105.0, 0.25, 0.04, 0.3, 0.01, 1e-3
    g = opt.greeks(kind, S, K, T, r, sig, q)
    price = lambda s=S, t=T, v=sig: opt.bs_price(kind, s, K, t, r, v, q)  # noqa: E731
    assert g["delta"] == pytest.approx((price(S + h) - price(S - h)) / (2 * h), abs=1e-5)
    assert g["gamma"] == pytest.approx((price(S + h) - 2 * price() + price(S - h)) / h ** 2, abs=1e-4)
    assert g["vega"] == pytest.approx((price(v=sig + h) - price(v=sig - h)) / (2 * h) / 100, abs=1e-6)
    one_day = 1 / 365
    assert g["theta"] == pytest.approx(price(t=T - one_day) - price(), abs=2e-4)


@pytest.mark.parametrize("kind,K,sig", [("call", 90, 0.15), ("put", 110, 0.6), ("call", 130, 1.2)])
def test_implied_vol_recovers_the_volatility_used(kind, K, sig):
    p = opt.bs_price(kind, S, K, 0.2, R, sig, Q)
    assert opt.implied_vol(p, kind, S, K, 0.2, R, Q) == pytest.approx(sig, abs=1e-5)


def test_implied_vol_rejects_prices_outside_arbitrage_bounds():
    T = 0.1
    intrinsic = S - 80 * math.exp(-R * T)
    assert opt.implied_vol(intrinsic - 0.5, "call", S, 80, T, R) is None   # below intrinsic
    assert opt.implied_vol(S + 1, "call", S, 80, T, R) is None             # above the stock
    assert opt.implied_vol(0, "put", S, 80, T, R) is None


# ── chains ──────────────────────────────────────────────────

def test_clean_chain_solves_iv_from_the_midpoint_not_the_data_source():
    c = chain()
    atm = next(x for x in c["calls"] if x["strike"] == 100)
    assert atm["iv_source"] == "mid"
    assert atm["iv"] == pytest.approx(SIGMA, abs=0.005)       # not the 0.9 the "data source" says
    assert atm["delta"] == pytest.approx(0.53, abs=0.03)
    assert c["atm_iv"] == pytest.approx(SIGMA, abs=0.005)
    assert c["expected_move"] == pytest.approx(S * SIGMA * math.sqrt(c["years"]), rel=0.02)
    assert c["dte"] == 30


def test_unquoted_contract_falls_back_to_the_data_source_iv_and_says_so():
    expiry, raw = raw_chain()
    raw["calls"][0].update(bid=0.0, ask=0.0, impliedVolatility=0.31)
    raw["calls"][1].update(bid=float("nan"), ask=None, impliedVolatility=float("nan"))
    c = opt.clean_chain(raw, expiry, R)
    first, second = c["calls"][0], c["calls"][1]
    assert first["mid"] is None and first["iv"] == 0.31 and first["iv_source"] == "data source"
    assert second["iv"] is None and second["delta"] is None and second["spread_pct"] is None


def test_year_fraction_counts_to_4pm_new_york():
    now = dt.datetime(2026, 11, 6, 21, 0, tzinfo=dt.timezone.utc)          # 4pm EST
    assert opt.year_fraction("2026-11-06", now) == pytest.approx(0.0, abs=1e-9)
    assert opt.year_fraction("2026-11-13", now) == pytest.approx(7 / 365, abs=1e-6)


def test_realized_vol_of_constant_daily_moves():
    closes = [100.0] * 5
    assert opt.realized_vol(closes, 30) is None                  # not enough data
    closes = [100.0]
    for i in range(40):
        closes.append(closes[-1] * (1.01 if i % 2 else 1 / 1.01))
    assert opt.realized_vol(closes, 30) == pytest.approx(math.log(1.01) * math.sqrt(252), rel=0.05)


# ── strategy analysis ───────────────────────────────────────

def _call(K, qty, price, iv=SIGMA):
    return {"type": "call", "qty": qty, "strike": K, "price": price, "iv": iv, "bid": price - 0.1, "ask": price + 0.1}


def _put(K, qty, price, iv=SIGMA):
    return {"type": "put", "qty": qty, "strike": K, "price": price, "iv": iv, "bid": price - 0.1, "ask": price + 0.1}


def test_long_call_payoff():
    res = opt.analyze([_call(100, 1, 3.0)], S, 30 / 365, R, sigma=SIGMA)
    assert res["net_debit"] == 300
    assert res["unlimited_profit"] and res["max_profit"] is None
    assert res["max_loss"] == -300
    assert res["breakevens"] == [103.0]
    assert res["profit_zones"] == [[103.0, None]]
    assert res["spread_cost"] == pytest.approx(10.0)            # half of a $0.20 spread x 100
    assert "above $103.00" in res["summary"]


def test_bull_call_spread_has_capped_profit_and_loss():
    legs = [_call(100, 1, 4.0), _call(110, -1, 1.0)]
    res = opt.analyze(legs, S, 30 / 365, R, sigma=SIGMA)
    assert res["net_debit"] == 300
    assert res["max_profit"] == 700 and res["max_loss"] == -300
    assert res["return_on_risk"] == pytest.approx(7 / 3, abs=1e-3)
    assert res["breakevens"] == [103.0]


def test_naked_short_call_has_unlimited_loss():
    res = opt.analyze([_call(110, -1, 1.5)], S, 30 / 365, R, sigma=SIGMA)
    assert res["unlimited_loss"] and res["max_loss"] is None
    assert res["max_profit"] == 150
    assert "unlimited loss" in res["summary"]


def test_iron_condor_profits_between_its_breakevens():
    legs = [_put(85, 1, 0.3), _put(90, -1, 1.0), _call(110, -1, 1.0), _call(115, 1, 0.3)]
    res = opt.analyze(legs, S, 30 / 365, R, sigma=SIGMA)
    assert res["net_debit"] == -140                              # a credit
    assert res["max_profit"] == 140 and res["max_loss"] == -360
    assert res["breakevens"] == [88.6, 111.4]
    assert res["profit_zones"] == [[88.6, 111.4]]
    assert "between $88.60 and $111.40" in res["summary"]


def test_straddle_profits_outside_its_breakevens():
    legs = [_call(100, 1, 3.0), _put(100, 1, 3.0)]
    res = opt.analyze(legs, S, 30 / 365, R, sigma=SIGMA)
    assert res["breakevens"] == [94.0, 106.0]
    assert res["profit_zones"] == [[0.0, 94.0], [106.0, None]]
    assert "below $94.00 or above $106.00" in res["summary"]


def test_covered_call_loss_is_bounded_by_the_stock():
    legs = [opt.stock_leg(S), _call(105, -1, 2.0)]
    res = opt.analyze(legs, S, 30 / 365, R, sigma=SIGMA)
    assert res["max_profit"] == 700                              # (105 - 100 + 2) x 100
    assert res["max_loss"] == -9800                              # stock to zero, keep the premium
    assert res["greeks"]["delta"] < 100


def test_probability_of_profit_matches_the_lognormal():
    T = 30 / 365
    res = opt.analyze([_call(100, 1, 3.0)], S, T, R, sigma=SIGMA)
    d2 = (math.log(S / 103.0) + (R - 0.5 * SIGMA ** 2) * T) / (SIGMA * math.sqrt(T))
    assert res["prob_profit"] == pytest.approx(opt.norm_cdf(d2), abs=1e-4)
    # Complementary positions: a long and a short call at the same price split the outcomes.
    short = opt.analyze([_call(100, -1, 3.0)], S, T, R, sigma=SIGMA)
    assert res["prob_profit"] + short["prob_profit"] == pytest.approx(1.0, abs=1e-6)


def test_curves_today_and_at_expiry():
    T = 30 / 365
    price = opt.bs_price("call", S, 100, T, R, SIGMA)
    res = opt.analyze([_call(100, 1, price)], S, T, R, sigma=SIGMA, days_forward=10)
    c = res["curves"]
    assert len(c["prices"]) == len(c["expiry"]) == len(c["today"]) == len(c["at_date"]) == 121
    i = min(range(len(c["prices"])), key=lambda j: abs(c["prices"][j] - S))
    assert abs(c["today"][i]) < 30                               # fairly priced: ~0 today at the spot
    assert c["at_date"][i] < c["today"][i]                       # time decay
    assert c["at_date_days"] == 10
    assert "at_date" not in opt.analyze([_call(100, 1, price)], S, T, R, days_forward=60)["curves"]


def test_analyze_rejects_empty_legs():
    with pytest.raises(ValueError):
        opt.analyze([], S, 0.1, R)


# ── presets and legs from a chain ───────────────────────────

@pytest.mark.parametrize("name", list(opt.PRESETS))
def test_every_preset_builds_and_is_sensible(name):
    c = chain()
    legs = opt.build_preset(name, c)
    res = opt.analyze(legs, c["spot"], c["years"], R, sigma=c["atm_iv"])
    assert 0 < res["prob_profit"] < 1
    assert res["breakevens"]
    if name in ("bull_call_spread", "bear_put_spread", "iron_condor"):
        assert res["max_profit"] is not None and res["max_loss"] is not None


def test_preset_strike_rules():
    c = chain()
    csp = opt.build_preset("cash_secured_put", c)
    assert len(csp) == 1 and csp[0]["qty"] == -1 and csp[0]["strike"] < S
    put = next(p for p in c["puts"] if p["strike"] == csp[0]["strike"])
    assert put["delta"] == pytest.approx(-0.30, abs=0.08)
    ic = opt.build_preset("iron_condor", c)
    strikes = [leg["strike"] for leg in ic]
    assert strikes == sorted(strikes) and [leg["qty"] for leg in ic] == [1, -1, -1, 1]
    cc = opt.build_preset("covered_call", c)
    assert cc[0]["type"] == "stock" and cc[1]["strike"] > S


def test_preset_errors():
    with pytest.raises(ValueError, match="unknown strategy"):
        opt.build_preset("yolo", chain())
    empty = {**chain(), "calls": [], "puts": []}
    with pytest.raises(ValueError, match="no quoted options"):
        opt.build_preset("long_call", empty)


def test_legs_from_request_prices_from_the_chain_and_validates():
    c = chain()
    legs = opt.legs_from_request([{"type": "call", "qty": 2, "strike": 105}, {"type": "stock", "qty": -1}], c)
    call = next(x for x in c["calls"] if x["strike"] == 105)
    assert legs[0]["price"] == call["mid"] and legs[0]["qty"] == 2
    assert legs[1] == opt.stock_leg(S, -1)
    for bad, msg in [([{"type": "call", "qty": 1, "strike": 101}], "no call at strike"),
                     ([{"type": "swap", "qty": 1, "strike": 100}], "call, put or stock"),
                     ([{"type": "put", "qty": 0, "strike": 100}], "not 0"),
                     ([{"type": "put", "qty": "x", "strike": 100}], "integer"),
                     ([{"type": "put", "qty": 1, "strike": 100}] * 7, "at most"),
                     ([], "non-empty")]:
        with pytest.raises(ValueError, match=msg):
            opt.legs_from_request(bad, c)


# ── scanner ─────────────────────────────────────────────────

def test_pick_expiry_prefers_the_target_inside_the_window():
    today = dt.date(2026, 11, 6)
    exp = ["2026-11-13", "2026-11-27", "2026-12-04", "2026-12-18", "2027-01-15"]
    assert opt.pick_expiry(exp, 20, 50, 30, today) == "2026-12-04"
    assert opt.pick_expiry(exp, 100, 200, 150, today) is None


def test_scan_candidate_respects_filters():
    c = chain(half_spread=0.02)
    best = opt.scan_candidate("cash_secured_put", c, max_delta=0.30)
    assert best["strike"] < S and abs(best["delta"]) <= 0.30
    assert best["capital"] == best["strike"] * 100
    assert best["return_pct"] == pytest.approx(best["premium"] / best["capital"] * 100, abs=0.01)
    assert best["annualized_pct"] == pytest.approx(best["return_pct"] * 365 / 30, abs=0.2)
    assert 0.5 < best["prob_profit"] < 1
    # Same chance of profit as the strategy builder shows for that trade.
    built = opt.analyze([opt._leg(next(p for p in c["puts"] if p["strike"] == best["strike"]), -1)],
                        S, c["years"], R, sigma=c["atm_iv"])
    assert best["prob_profit"] == built["prob_profit"]
    cc = opt.scan_candidate("covered_call", c, max_delta=0.30)
    assert cc["strike"] > S and cc["capital"] == S * 100
    assert opt.scan_candidate("cash_secured_put", chain(oi=5), min_oi=100) is None
    assert opt.scan_candidate("cash_secured_put", chain(half_spread=2.0), max_spread_pct=10) is None
    with pytest.raises(ValueError):
        opt.scan_candidate("naked_call", c)


# ── endpoints ───────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "Plotly dashboard"))
    import app
    from cache import SimpleCache
    monkeypatch.setattr(app, "_cache", SimpleCache())
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    expiries = [_expiry(d) for d in (3, 30, 60)]
    chains = {e: raw_chain(d)[1] for e, d in zip(expiries, (3, 30, 60))}
    monkeypatch.setattr(app, "get_option_expirations", lambda s: list(expiries) if s == "TEST" else [])
    monkeypatch.setattr(app, "get_option_chain", lambda s, e: chains.get(e) if s == "TEST" else None)
    monkeypatch.setattr(app, "get_eod_options", lambda s, base: None)
    monkeypatch.setattr(app, "_cached_bars", lambda s, p: [])
    app.app.config["TESTING"] = True
    app.limiter.enabled = False
    client = app.app.test_client()
    client.expiries = expiries
    return client


def test_expirations_endpoint(client):
    data = client.get("/options/expirations?symbol=test").get_json()
    assert [e["dte"] for e in data["expirations"]] == [3, 30, 60]
    assert data["default"] == client.expiries[1]
    assert client.get("/options/expirations").status_code == 400


def test_chain_endpoint(client):
    res = client.get(f"/options/chain?symbol=TEST&expiry={client.expiries[2]}")
    data = res.get_json()
    assert res.status_code == 200 and data["expiry"] == client.expiries[2]
    assert data["rate"] == 0.04 and "assumed" in data["rate_source"]
    assert len(data["calls"]) == 25 and data["calls"][0]["delta"] is not None
    # Unknown expiry falls back to the one nearest 20-60 days out.
    assert client.get("/options/chain?symbol=TEST&expiry=1999-01-01").get_json()["expiry"] == client.expiries[1]
    assert client.get("/options/chain?symbol=NONE").status_code == 404


def test_strategy_endpoint_preset_and_custom_legs(client):
    res = client.post("/options/strategy", json={"symbol": "TEST", "preset": "iron_condor"})
    data = res.get_json()
    assert res.status_code == 200 and len(data["legs"]) == 4 and data["max_loss"] < 0
    assert data["summary"].startswith("Collects")
    legs = [{"type": leg["type"], "qty": leg["qty"], "strike": leg["strike"]} for leg in data["legs"][:2]]
    res = client.post("/options/strategy", json={"symbol": "TEST", "expiry": data["expiry"],
                                                 "legs": legs, "days_forward": 5})
    assert res.status_code == 200 and "at_date" in res.get_json()["curves"]
    one_dollar_call = [{"type": "call", "qty": 1, "strike": 1}]
    bad = client.post("/options/strategy", json={"symbol": "TEST", "legs": one_dollar_call})
    assert bad.status_code == 400 and "no call at strike" in bad.get_json()["error"]
    assert client.post("/options/strategy", json={"symbol": "TEST", "preset": "nope"}).status_code == 400


def test_scan_endpoint(client):
    url = "/options/scan?symbols=TEST,NONE&kind=cash_secured_put&min_dte=20&max_dte=50&max_spread=25"
    data = client.get(url).get_json()
    assert [r["symbol"] for r in data["results"]] == ["TEST"]
    assert data["results"][0]["expiry"] == client.expiries[1]
    assert data["skipped"][0]["symbol"] == "NONE"
    assert client.get("/options/scan?symbols=TEST&kind=naked").status_code == 400
    assert client.get("/options/scan?kind=covered_call").status_code == 400


def _eod_file(days=(30,)):
    """A saved end-of-day file, as capture_snapshot.capture_eod_chains writes it."""
    # Saved an hour ago, so a clock measured from "now" would differ measurably.
    saved_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(hours=1)
    out = {"symbol": "EODX", "captured_at": saved_at.isoformat(), "chains": {}}
    for d in days:
        expiry, raw = raw_chain(d)
        out["spot"], out["dividend_yield"] = raw["spot"], raw["dividend_yield"]
        out["chains"][expiry] = {"calls": opt.compact_rows(raw["calls"], raw["spot"]),
                                 "puts": opt.compact_rows(raw["puts"], raw["spot"])}
    return out


def test_compact_rows_keeps_the_band_and_the_fields_the_maths_needs():
    _, raw = raw_chain()
    rows = opt.compact_rows(raw["calls"], S, band=0.10)
    assert [r["strike"] for r in rows] == [90.0, 92.5, 95.0, 97.5, 100.0, 102.5, 105.0, 107.5, 110.0]
    assert set(rows[0]) == {"strike", "bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility"}
    assert opt.compact_rows([{"strike": float("nan")}], S) == []


def test_eod_raw_chain_prices_the_same_as_a_live_chain():
    eod = _eod_file()
    expiry = next(iter(eod["chains"]))
    live = chain()
    saved = opt.clean_chain(opt.eod_raw_chain(eod, expiry), expiry, R)
    assert saved["atm_iv"] == pytest.approx(live["atm_iv"], abs=1e-6)
    assert opt.eod_raw_chain(eod, "1999-01-01") is None
    assert opt.eod_raw_chain({"chains": eod["chains"]}, expiry) is None    # no spot saved


def test_endpoints_fall_back_to_end_of_day_chains_when_the_live_source_is_empty(client, monkeypatch):
    import app
    eod = _eod_file(days=(10, 30))
    calls = []
    monkeypatch.setattr(app, "get_eod_options", lambda s, base: (calls.append(s), eod)[1] if s == "EODX" else None)
    exp = client.get("/options/expirations?symbol=EODX").get_json()
    assert [e["date"] for e in exp["expirations"]] == list(eod["chains"])
    data = client.get("/options/chain?symbol=EODX").get_json()
    assert data["source"] == "end_of_day" and data["quotes_as_of"] == eod["captured_at"]
    assert data["atm_iv"] == pytest.approx(SIGMA, abs=0.01)
    # Time to expiry runs from when the quotes were saved, not from now.
    saved = dt.datetime.fromisoformat(eod["captured_at"])
    assert data["years"] == pytest.approx(opt.year_fraction(data["expiry"], saved), abs=1e-9)
    res = client.post("/options/strategy", json={"symbol": "EODX", "preset": "iron_condor"})
    assert res.status_code == 200 and len(res.get_json()["legs"]) == 4
    assert calls == ["EODX"]                                    # the file is fetched once and cached
    assert client.get("/options/chain?symbol=TEST").get_json()["source"] == "live"
    missing = client.get("/options/chain?symbol=NOPE")
    assert missing.status_code == 404 and "not answering" in missing.get_json()["error"]


# ── Ski tools ───────────────────────────────────────────────

def _ski(options):
    return st.SkiData(bars=lambda s, p: [], fundamentals=lambda s: None, news=lambda s: [],
                      macro_history=lambda sid, n: [], holdings=lambda: [], risk=lambda raw: (None, ""),
                      options=options)


def test_ski_options_overview():
    c = {**chain(), "realized_vol_30d": 0.20}
    out = st.run_tool("get_options_overview", {"symbol": "test", "days_to_expiry": 30}, _ski(lambda s, d: c))
    assert out["symbol"] == "TEST" and out["days_to_expiry"] == 30
    assert out["atm_implied_vol_pct"] == pytest.approx(25.0, abs=0.5)
    assert out["implied_minus_realized_pct_points"] == pytest.approx(5.0, abs=0.5)
    assert out["expected_move_pct"] == pytest.approx(25 * math.sqrt(c["years"]), abs=0.3)
    assert len(out["most_open_interest_calls"]) == 3


def test_ski_strategy_tool_and_missing_data():
    c = chain()
    out = st.run_tool("analyze_option_strategy", {"symbol": "TEST", "strategy": "bull_call_spread",
                                                  "days_to_expiry": 30}, _ski(lambda s, d: c))
    assert [leg["action"] for leg in out["legs"]] == ["buy", "sell"]
    assert out["max_profit"] > 0 > out["max_loss"] and out["summary"]
    assert "curves" not in out
    none = st.run_tool("get_options_overview", {"symbol": "X", "days_to_expiry": 30}, _ski(lambda s, d: None))
    assert "error" in none
    assert "error" in st.run_tool("get_options_overview", {"symbol": "X", "days_to_expiry": 30}, _ski(None))
    with pytest.raises(ValueError):
        st.run_tool("analyze_option_strategy", {"symbol": "X", "strategy": "yolo", "days_to_expiry": 30},
                    _ski(lambda s, d: c))
    assert st.describe_call("analyze_option_strategy", {"symbol": "nvda", "strategy": "iron_condor"}) \
        == "NVDA iron condor"
