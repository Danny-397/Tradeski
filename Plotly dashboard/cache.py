import time

class SimpleCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        entry = self.store.get(key)
        if not entry:
            return None

        value, expires_at = entry
        if time.time() > expires_at:
            del self.store[key]
            return None

        return value

    def set(self, key, value, ttl=60):
        expires_at = time.time() + ttl
        self.store[key] = (value, expires_at)
# creates a tiny in-memory cahce 
