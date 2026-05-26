# tracker/database.py
# SQLite persistence for prices and alerts.

import os
import sqlite3
import time
from typing import List, Tuple, Optional

DB_PATH = "data/prices.db"


# ------------------------------------------------------------------------------
# Internal Helpers
# ------------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    """Ensure DB directory exists and return a connection."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


# ------------------------------------------------------------------------------
# Initialization
# ------------------------------------------------------------------------------

def init_db() -> None:
    """Initialize the database with prices and alerts tables."""
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            volume REAL,
            timestamp REAL NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            message TEXT,
            threshold REAL,
            multiplier REAL,
            zscore REAL,
            active INTEGER DEFAULT 1,
            created_at REAL NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol     TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            shares     REAL    NOT NULL CHECK (shares > 0),
            avg_cost   REAL,
            added_at   TEXT    DEFAULT (datetime('now'))
        )
        """
    )

    conn.commit()
    conn.close()


# ------------------------------------------------------------------------------
# Price Storage
# ------------------------------------------------------------------------------

def insert_price(symbol: str, price: float, volume: float = 0.0) -> None:
    """Insert a price row with timestamp."""
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO prices (symbol, price, volume, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (symbol, price, volume, time.time()),
    )

    conn.commit()
    conn.close()


def get_recent_prices(symbol: str, limit: int = 200) -> List[Tuple[float, float, float]]:
    """
    Return recent prices for a symbol as (timestamp, price, volume) tuples.
    Ordered oldest → newest.
    """
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT timestamp, price, volume
        FROM prices
        WHERE symbol = ?
        ORDER BY timestamp ASC
        LIMIT ?
        """,
        (symbol, limit),
    )

    rows = cursor.fetchall()
    conn.close()
    return rows


def get_prices_in_range(
    symbol: str,
    start_ts: float,
    end_ts: float,
) -> List[Tuple[float, float, float]]:
    """
    Return prices in a time range as (timestamp, price, volume).
    """
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT timestamp, price, volume
        FROM prices
        WHERE symbol = ?
          AND timestamp >= ?
          AND timestamp <= ?
        ORDER BY timestamp ASC
        """,
        (symbol, start_ts, end_ts),
    )

    rows = cursor.fetchall()
    conn.close()
    return rows


# ------------------------------------------------------------------------------
# Alerts
# ------------------------------------------------------------------------------

def insert_alert(symbol: str, alert_type: str, message: str) -> None:
    """
    Insert a simple alert (used by tests).
    """
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO alerts (symbol, alert_type, message, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (symbol, alert_type, message, time.time()),
    )

    conn.commit()
    conn.close()


def create_alert(
    symbol: str,
    alert_type: str,
    threshold: Optional[float] = None,
    multiplier: Optional[float] = None,
    zscore: Optional[float] = None,
) -> int:
    """
    Create a rule-based alert (used by dashboard API).
    """
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO alerts (
            symbol, alert_type, threshold, multiplier, zscore, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (symbol, alert_type, threshold, multiplier, zscore, time.time()),
    )

    alert_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return alert_id


def get_recent_alerts(symbol: str, limit: int = 10):
    """
    Return recent alerts for a symbol as (timestamp, alert_type, message).
    """
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT created_at, alert_type, message
        FROM alerts
        WHERE symbol = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (symbol, limit),
    )

    rows = cursor.fetchall()
    conn.close()
    return rows


def get_alerts():
    """
    Return all active alerts (for dashboard listing).
    """
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, symbol, alert_type, threshold, multiplier, zscore, created_at
        FROM alerts
        WHERE active = 1
        ORDER BY created_at DESC
        """
    )

    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_alert(alert_id: int) -> None:
    """Delete an alert by id."""
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()


# ------------------------------------------------------------------------------
# Portfolio
# ------------------------------------------------------------------------------

def upsert_holding(
    symbol: str,
    shares: float,
    avg_cost: Optional[float] = None,
) -> int:
    """Insert a new holding or update shares/avg_cost if the symbol already exists."""
    sym = symbol.upper().strip()
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO portfolio (symbol, shares, avg_cost, added_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(symbol) DO UPDATE SET
            shares   = excluded.shares,
            avg_cost = excluded.avg_cost,
            added_at = excluded.added_at
        """,
        (sym, shares, avg_cost),
    )

    conn.commit()
    row_id: int = cursor.execute(
        "SELECT id FROM portfolio WHERE symbol = ?", (sym,)
    ).fetchone()[0]
    conn.close()
    return row_id


def get_portfolio() -> List[dict]:
    """Return all portfolio holdings ordered by symbol."""
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, symbol, shares, avg_cost, added_at
        FROM portfolio
        ORDER BY symbol ASC
        """
    )

    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "symbol": r[1],
            "shares": r[2],
            "avg_cost": r[3],
            "added_at": r[4],
        }
        for r in rows
    ]


def delete_holding(holding_id: int) -> None:
    """Remove a portfolio holding by id."""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM portfolio WHERE id = ?", (holding_id,))
    conn.commit()
    conn.close()
