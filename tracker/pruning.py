import sqlite3
import time

def prune_old_data(db_path: str, days: int = 30):
    cutoff = time.time() - (days * 86400)
# Gives a cutoff timestamp and deletes all rows older than that 
  # This keeps the DB data lean and fast, gets rid of any unessecary things 
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM prices
        WHERE timestamp < ?
    """, (cutoff,))

    deleted_rows = cursor.rowcount
    conn.commit()
    conn.close()

    return deleted_rows
