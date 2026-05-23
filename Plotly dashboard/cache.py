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

    def set(self, key, value, ttl=60):
        """Store a value with a time-to-live (TTL)."""
        expires_at = time.time() + ttl
        self.store[key] = (value, expires_at)

    def clear(self):
        """Clear all cached entries."""
        self.store.clear()
