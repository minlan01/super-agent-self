"""In-memory cache backend with TTL support and LRU eviction."""

from __future__ import annotations

import fnmatch
import threading
import time
from collections import OrderedDict
from typing import Any

from .base import CacheBackend


class MemoryCacheBackend(CacheBackend):
    """In-memory cache backed by an OrderedDict.

    Features:
    - Per-key TTL (time-to-live) with lazy + periodic eviction
    - LRU eviction when *max_size* is exceeded
    - Thread-safe via ``threading.Lock``
    - Pattern-based ``clear()`` using :mod:`fnmatch`
    """

    def __init__(self, max_size: int = 1000, default_ttl: float = 300.0):
        self.max_size = max_size
        self.default_ttl = default_ttl
        # OrderedDict preserves insertion order — oldest first.
        # We move keys to the end on access (LRU).
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers (called with lock held)
    # ------------------------------------------------------------------

    def _evict_expired(self) -> None:
        """Remove all expired entries.  Must be called with *self._lock* held."""
        now = time.time()
        expired = [k for k, (_, expiry) in self._store.items() if expiry <= now]
        for k in expired:
            del self._store[k]

    def _evict_lru(self) -> None:
        """Evict oldest entries until we are within *max_size*.  Lock must be held."""
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)  # FIFO — oldest first

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if expiry <= time.time():
                del self._store[key]
                return None
            # Move to end — most recently used
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        effective_ttl = ttl if ttl is not None else self.default_ttl
        expiry = time.time() + effective_ttl
        with self._lock:
            self._evict_expired()
            self._store[key] = (value, expiry)
            self._store.move_to_end(key)
            self._evict_lru()

    async def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    async def clear(self, pattern: str = "*") -> int:
        with self._lock:
            self._evict_expired()
            if pattern == "*":
                count = len(self._store)
                self._store.clear()
                return count
            keys_to_delete = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
            for k in keys_to_delete:
                del self._store[k]
            return len(keys_to_delete)

    async def exists(self, key: str) -> bool:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            _, expiry = entry
            if expiry <= time.time():
                del self._store[key]
                return False
            return True
