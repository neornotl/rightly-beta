"""In-memory sliding-window rate limiter (F4, demo-grade).

Honest limits of this module:
- Single-process memory only. Streamlit Cloud runs several instances, so this
  is NOT real DDoS protection; it only caps one instance's load and gives the
  team a visible per-client cap for the pilot/demo window.
- Keys are opaque strings (e.g. "<hashed-ip>|<session-id>") built by callers.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        if limit < 0:
            raise ValueError("limit must be >= 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record a hit for ``key``; True when within the window limit."""
        if self.limit == 0:
            return False
        stamp = now if now is not None else time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if stamp - t < self.window_seconds]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(stamp)
            self._hits[key] = hits
            return True

    def remaining(self, key: str, now: float | None = None) -> int:
        stamp = now if now is not None else time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if stamp - t < self.window_seconds]
            self._hits[key] = hits
            return max(0, self.limit - len(hits))

    def sweep(self, now: float | None = None) -> int:
        """Drop expired entries; returns how many keys were removed."""
        stamp = now if now is not None else time.monotonic()
        with self._lock:
            before = len(self._hits)
            self._hits = {
                k: [t for t in v if stamp - t < self.window_seconds] for k, v in self._hits.items()
            }
            self._hits = {k: v for k, v in self._hits.items() if v}
            return before - len(self._hits)
