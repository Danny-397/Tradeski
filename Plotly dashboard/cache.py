# dashboard/cache.py
# Simple in‑memory TTL cache for dashboard endpoints.

import time


class SimpleCache:
    """A minimal TTL-based in-memory cache."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        """Retrieve a cached value if it has not expired."""
        entry = self.store.get(key)
        if not entry:
            return None

        value, expires_at = entry
        if time.time() > expires_at:
            del self.store[key]
            return None

        return value

    # get() only drops an expired entry when that same key is read again, so
    # keys nobody asks for twice would stay until the server restarts.
    MAX_ENTRIES = 5000

    def set(self, key, value, ttl=60):
        """Store a value with a time-to-live (TTL)."""
        now = time.time()
        if len(self.store) >= self.MAX_ENTRIES:
            self.store = {k: v for k, v in self.store.items() if v[1] > now}
        self.store[key] = (value, now + ttl)
