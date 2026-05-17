import os
import sqlite3
from tracker import database

TEST_DB = "data/test_prices.db"


def setup_function():
    # Use a separate test database
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    os.makedirs("data", exist_ok=True)
    database.DB_PATH = TEST_DB
    database.init_db()


def test_insert_and_fetch_prices():
    database.insert_price("AAPL", 150.0)
    database.insert_price("AAPL", 151.0)

    rows = database.get_recent_prices("AAPL", limit=10)

    assert len(rows) == 2
    assert rows[0][1] == 150.0
    assert rows[1][1] == 151.0


def test_insert_and_fetch_alerts():
    database.insert_alert("AAPL", "drop", "Price dropped")

    rows = database.get_recent_alerts("AAPL", limit=10)

    assert len(rows) == 1
    ts, alert_type, msg = rows[0]
    assert alert_type == "drop"
    assert msg == "Price dropped"
