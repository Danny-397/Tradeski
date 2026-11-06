"""Tests for fundamentals computed from SEC filings (tracker/sec_fundamentals.py).

No network: the XBRL facts are built here in the shape EDGAR's
companyconcept API returns them.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tracker import sec_fundamentals as sec  # noqa: E402


def fact(start, end, val, filed="2026-10-30", form="10-Q"):
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form}


# Fiscal year = calendar year. 10-Qs give Q1-Q3; the 10-K gives only the year.
EPS = [
    fact("2025-01-01", "2025-03-31", 1.0), fact("2025-04-01", "2025-06-30", 1.1),
    fact("2025-07-01", "2025-09-30", 1.2), fact("2025-01-01", "2025-12-31", 4.6, "2026-02-01", "10-K"),
    fact("2026-01-01", "2026-03-31", 1.3), fact("2026-04-01", "2026-06-30", 1.4),
    fact("2026-07-01", "2026-09-30", 1.5),
    # A 10-Q also repeats year-to-date figures; those 6- and 9-month spans are ignored.
    fact("2026-01-01", "2026-09-30", 4.2),
]
REVENUE = [fact(e["start"], e["end"], e["val"] * 1e9, e["filed"], e["form"]) for e in EPS] + [
    fact("2024-01-01", "2024-03-31", 0.9e9), fact("2024-04-01", "2024-06-30", 0.9e9),
    fact("2024-07-01", "2024-09-30", 0.9e9), fact("2024-01-01", "2024-12-31", 3.6e9, "2025-02-01", "10-K"),
]
NET_INCOME = [fact(e["start"], e["end"], e["val"] * 0.25e9, e["filed"], e["form"]) for e in EPS]


def test_fourth_quarter_is_the_year_minus_three_quarters():
    q = dict(sec.quarters(EPS))
    assert round(q[sec._date("2025-12-31")], 6) == 1.3  # 4.6 - (1.0 + 1.1 + 1.2)


def test_trailing_sums_the_last_four_quarters():
    end, total = sec.trailing(sec.quarters(EPS))
    assert end.isoformat() == "2026-09-30"
    assert round(total, 6) == 5.5  # Q4 1.3 + 1.3 + 1.4 + 1.5


def test_trailing_refuses_a_window_with_a_missing_quarter():
    gappy = [f for f in EPS if f["end"] != "2026-06-30"]
    assert sec.trailing(sec.quarters(gappy)) is None


def test_restatement_uses_the_latest_filing():
    restated = EPS + [fact("2026-07-01", "2026-09-30", 2.5, filed="2026-12-01")]
    assert dict(sec.quarters(restated))[sec._date("2026-09-30")] == 2.5


def test_shares_sum_the_classes_on_the_latest_cover():
    shares = [
        {"end": "2026-07-20", "val": 100, "filed": "2026-07-25"},
        {"end": "2026-10-20", "val": 300, "filed": "2026-10-30"},  # class A
        {"end": "2026-10-20", "val": 200, "filed": "2026-10-30"},  # class C
    ]
    end, total = sec.latest_shares(shares)
    assert end.isoformat() == "2026-10-20" and total == 500


def test_compute_and_price_give_pe_market_cap_growth_and_margin():
    shares = [{"end": "2026-10-20", "val": 1_000_000, "filed": "2026-10-30"}]
    base = sec.compute(EPS, REVENUE, NET_INCOME, shares)
    assert base["eps_trailing_4q"] == 5.5
    assert base["revenue_trailing_4q_usd"] == 5_500_000_000
    # The four quarters a year earlier (to 2025-09-30): 0.9 (derived 2024 Q4) + 1.0 + 1.1 + 1.2 = 4.2
    assert base["revenue_growth_yoy_pct"] == round((5.5 / 4.2 - 1) * 100, 1)
    assert base["net_margin_trailing_pct"] == 25.0
    assert "pe_trailing" not in base  # price-dependent fields come from with_price

    priced = sec.with_price(base, 110.0)
    assert priced["pe_trailing"] == 20.0
    assert priced["market_cap_usd"] == 110_000_000


def test_negative_earnings_give_no_pe():
    losses = [fact(f["start"], f["end"], -abs(f["val"]), f["filed"], f["form"]) for f in EPS]
    priced = sec.with_price(sec.compute(losses, [], [], []), 50.0)
    assert "pe_trailing" not in priced and "pe_note" in priced


def test_disabled_without_a_contact_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    assert sec.user_agent() is None
    assert sec.fundamentals("AAPL") is None
    monkeypatch.setenv("SEC_USER_AGENT", "Tradeski")  # no contact email: SEC would refuse it
    assert sec.user_agent() is None
