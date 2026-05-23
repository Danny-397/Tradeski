# tracker/database.py
# SQLite database layer for prices, alerts, and analytics.

import os
import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional

DB_PATH = os.path.join("data", "prices.db")


def _connect() -> sqlite3.Connection:
    """Return a new SQLite connection."""
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    """Initialize the SQLite database and create required tables."""
    os.makedirs("data", exist_ok=True)
    conn = _connect()
    cur = conn.cursor()

    # Prices table (timestamp stored as ISO string)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            price REAL NOT NULL,
            volume REAL DEFAULT 0
        )
        """
    )

    # User-defined alerts table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            threshold REAL,
            multiplier REAL,
            zscore REAL,
            active INTEGER DEFAULT 1,
            created_at REAL
        )
        """
    )

    conn.commit()
    conn.close()


# Price storage + retrieval
def insert_price(symbol: str, price: float, volume: float = 0.0) -> None:
    """Insert a new price record."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO prices (symbol, timestamp, price, volume)
        VALUES (?, ?, ?, ?)
        """,
        (symbol, datetime.utcnow().isoformat(), price, volume),
    )
    conn.commit()
    conn.close()


def get_recent_prices(
    symbol: str, limit: int = 200
) -> List[Tuple[str, float]]:
    """Return recent (timestamp, price) rows, oldest → newest."""
    conn = _connect()
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


def get_recent_volumes(symbol: str, limit: int = 50) -> List[float]:
    """Return recent volume values, newest first."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT volume
        FROM prices
        WHERE symbol = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (symbol, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_prices_in_range(
    symbol: str, start_ts: float, end_ts: float
) -> List[Tuple[str, float, float]]:
    """Return (timestamp, price, volume) rows between two timestamps."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT timestamp, price, volume
        FROM prices
        WHERE symbol = ?
          AND strftime('%s', timestamp) BETWEEN ? AND ?
        ORDER BY timestamp ASC
        """,
        (symbol, int(start_ts), int(end_ts)),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


# User-defined alert CRUD
def create_alert(
    symbol: str,
    alert_type: str,
    threshold: Optional[float] = None,
    multiplier: Optional[float] = None,
    zscore: Optional[float] = None,
) -> int:
    """Create a new user-defined alert."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_alerts
        (symbol, alert_type, threshold, multiplier, zscore, created_at)
        VALUES (?, ?, ?, ?, ?, strftime('%s','now'))
        """,
        (symbol, alert_type, threshold, multiplier, zscore),
    )
    conn.commit()
    alert_id = cur.lastrowid
    conn.close()
    return alert_id


def get_alerts() -> List[Tuple]:
    """Return all active user-defined alerts."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, symbol, alert_type, threshold,
               multiplier, zscore, active, created_at
        FROM user_alerts
        WHERE active = 1
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_alert(alert_id: int) -> None:
    """Delete an alert permanently."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM user_alerts WHERE id = ?",
        (alert_id,),
    )
    conn.commit()
    conn.close()


def disable_alert(alert_id: int) -> None:
    """Soft-disable an alert."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE user_alerts SET active = 0 WHERE id = ?",
        (alert_id,),
    )
    conn.commit()
    conn.close()
