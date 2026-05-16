import sqlite3
import os
from datetime import datetime
from typing import List, Tuple, Optional

DB_PATH = os.path.join("data", "prices.db")


def init_db() -> None:
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
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO prices (symbol, timestamp, price) VALUES (?, ?, ?)",
        (symbol, datetime.utcnow().isoformat(), price),
    )
    conn.commit()
    conn.close()


def insert_alert(symbol: str, alert_type: str, message: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO alerts (symbol, timestamp, type, message) VALUES (?, ?, ?, ?)",
        (symbol, datetime.utcnow().isoformat(), alert_type, message),
    )
    conn.commit()
    conn.close()


def get_recent_prices(symbol: str, limit: int = 200) -> List[Tuple[str, float]]:
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
    return list(reversed(rows))


def get_recent_alerts(symbol: Optional[str] = None, limit: int = 50):
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
