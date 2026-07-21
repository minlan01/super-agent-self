"""Abstract cache backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CacheBackend(ABC):
    """Abstract cache backend — all methods are async for uniformity."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Retrieve a cached value by key.  Returns None on miss."""
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store a value with an optional time-to-live in seconds."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a single key from the cache."""
        ...

    @abstractmethod
    async def clear(self, pattern: str = "*") -> int:
        """Remove keys matching *pattern* (fnmatch-style). Returns count deleted."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return True if *key* is present and not expired."""
        ...
