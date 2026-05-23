import os

from tracker import database

TEST_DB = "data/test_prices.db"


def setup_function() -> None:
    """
    Set up a clean test database before each test.
    """
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    os.makedirs("data", exist_ok=True)

    database.DB_PATH = TEST_DB
    database.init_db()


def test_insert_and_fetch_prices() -> None:
    """
    Test inserting and retrieving stock prices.
    """
    database.insert_price("AAPL", 150.0)
    database.insert_price("AAPL", 151.0)

    rows = database.get_recent_prices(
        "AAPL",
        limit=10,
    )

    assert len(rows) == 2
    assert rows[0][1] == 150.0
    assert rows[1][1] == 151.0


def test_insert_and_fetch_alerts() -> None:
    """
    Test inserting and retrieving alerts.
    """
    database.insert_alert(
        "AAPL",
        "drop",
        "Price dropped",
    )

    rows = database.get_recent_alerts(
        "AAPL",
        limit=10,
    )

    assert len(rows) == 1

    _, alert_type, message = rows[0]

    assert alert_type == "drop"
    assert message == "Price dropped"

cursor.execute("""
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    threshold REAL,
    multiplier REAL,
    zscore REAL,
    active INTEGER DEFAULT 1,
    created_at REAL
)
""")
