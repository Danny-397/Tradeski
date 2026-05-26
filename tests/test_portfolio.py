"""Tests for portfolio CRUD operations in tracker/database.py."""

import os
import pytest

import tracker.database as db


_TEST_DB = "data/test_portfolio.db"


def setup_function():
    db.DB_PATH = _TEST_DB
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)
    db.init_db()


def teardown_function():
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)


def test_add_holding_and_fetch():
    db.upsert_holding("AAPL", 10.0, avg_cost=150.0)
    holdings = db.get_portfolio()
    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "AAPL"
    assert holdings[0]["shares"] == 10.0
    assert holdings[0]["avg_cost"] == 150.0


def test_upsert_updates_existing_symbol():
    db.upsert_holding("AAPL", 10.0, avg_cost=150.0)
    db.upsert_holding("AAPL", 15.0, avg_cost=160.0)  # update same symbol
    holdings = db.get_portfolio()
    assert len(holdings) == 1
    assert holdings[0]["shares"] == 15.0
    assert holdings[0]["avg_cost"] == 160.0


def test_multiple_different_symbols():
    db.upsert_holding("AAPL", 10.0)
    db.upsert_holding("MSFT", 5.0, avg_cost=300.0)
    db.upsert_holding("NVDA", 2.5)
    holdings = db.get_portfolio()
    assert len(holdings) == 3
    symbols = [h["symbol"] for h in holdings]
    assert "AAPL" in symbols
    assert "MSFT" in symbols
    assert "NVDA" in symbols


def test_delete_holding():
    hid = db.upsert_holding("TSLA", 3.0, avg_cost=200.0)
    assert len(db.get_portfolio()) == 1
    db.delete_holding(hid)
    assert len(db.get_portfolio()) == 0


def test_holding_without_avg_cost():
    db.upsert_holding("AMZN", 4.0)
    holdings = db.get_portfolio()
    assert holdings[0]["avg_cost"] is None


def test_symbol_case_insensitive():
    db.upsert_holding("aapl", 10.0)
    db.upsert_holding("AAPL", 20.0)   # same symbol, different case → upsert
    holdings = db.get_portfolio()
    assert len(holdings) == 1
    assert holdings[0]["shares"] == 20.0


def test_get_portfolio_returns_empty_list():
    holdings = db.get_portfolio()
    assert holdings == []
