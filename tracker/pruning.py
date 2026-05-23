# tracker/pruning.py
# Removes old rows from the prices table to keep the DB lean.

import sqlite3
import time


def prune_old_data(db_path: str, days: int = 30) -> int:
    """
    Delete price rows older than the given number of days.

    Args:
        db_path: Path to the SQLite database.
        days: Number of days to retain.

    Returns:
        Number of deleted rows.
    """
    cutoff = time.time() - (days * 86400)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM prices
        WHERE timestamp < ?
        """,
        (cutoff,),
    )

    deleted_rows = cursor.rowcount
    conn.commit()
    conn.close()

    return deleted_rows
