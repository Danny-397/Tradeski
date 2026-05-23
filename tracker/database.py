import sqlite3
import os
from datetime import datetime
from typing import List, Tuple, Optional

DB_PATH = os.path.join("data", "prices.db")


def init_db() -> None:
    """
    Initialize the SQLite database and create required tables if they do not exist.
    """
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            price REAL NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            type TEXT NOT NULL,
            message TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def insert_price(symbol: str, price: float) -> None:
    """
    Insert a new price record into the database.

    Args:
        symbol: Stock ticker symbol.
        price: Latest price value.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO prices (symbol, timestamp, price) VALUES (?, ?, ?)",
        (symbol, datetime.utcnow().isoformat(), price),
    )
    conn.commit()
    conn.close()


def insert_alert(symbol: str, alert_type: str, message: str) -> None:
    """
    Insert a new alert record into the database.

    Args:
        symbol: Stock ticker symbol.
        alert_type: Type/category of alert.
        message: Human-readable alert message.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO alerts (symbol, timestamp, type, message) VALUES (?, ?, ?, ?)",
        (symbol, datetime.utcnow().isoformat(), alert_type, message),
    )
    conn.commit()
    conn.close()


def get_recent_prices(symbol: str, limit: int = 200) -> List[Tuple[str, float]]:
    """
    Retrieve the most recent price records for a given symbol.

    Args:
        symbol: Stock ticker symbol.
        limit: Maximum number of records to return.

    Returns:
        A list of (timestamp, price) tuples ordered from oldest to newest.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT timestamp, price
        FROM prices
        WHERE symbol = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (symbol, limit),
    )
    rows = cur.fetchall()
    conn.close()

    # Reverse so the earliest record is first
    return list(reversed(rows))


def get_recent_alerts(
    symbol: Optional[str] = None,
    limit: int = 50
) -> List[Tuple[str, str, str]]:
    """
    Retrieve recent alerts, optionally filtered by symbol.

    Args:
        symbol: Stock ticker symbol to filter by, or None for all alerts.
        limit: Maximum number of alerts to return.

    Returns:
        A list of alert tuples. Format differs depending on filter:
            If symbol is provided: (timestamp, type, message)
            If symbol is None:     (timestamp, symbol, type, message)
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if symbol:
        cur.execute(
            """
            SELECT timestamp, type, message
            FROM alerts
            WHERE symbol = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (symbol, limit),
        )
        rows = cur.fetchall()
    else:
        cur.execute(
            """
            SELECT timestamp, symbol, type, message
            FROM alerts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()

    conn.close()
    return rows

def get_recent_volumes(self, symbol, limit=50):
    cursor = self.conn.cursor()
    cursor.execute("""
        SELECT volume FROM prices
        WHERE symbol = ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (symbol, limit))
    rows = cursor.fetchall()
    return [r[0] for r in rows]

