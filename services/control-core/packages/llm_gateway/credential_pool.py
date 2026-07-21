"""Credential Pool — rotating multi-key management for LLM providers."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class CredentialPool:
    """Round-robin rotating pool of API keys for a single provider.

    Thread-safe via asyncio.Lock. Supports runtime key addition and
    invalidation (e.g., revoked keys).
    """

    def __init__(self, api_keys: list[str]) -> None:
        self._keys: list[str] = list(api_keys)
        self._current_index: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    async def rotate(self) -> str | None:
        """Return the next API key in round-robin order.

        Returns None if the pool is empty.
        """
        async with self._lock:
            if not self._keys:
                return None
            key = self._keys[self._current_index % len(self._keys)]
            self._current_index = (self._current_index + 1) % len(self._keys)
            return key

    async def mark_invalid(self, key: str) -> None:
        """Remove an API key from the pool (e.g., revoked by provider).

        Thread-safe via asyncio.Lock.
        """
        async with self._lock:
            if key in self._keys:
                self._keys.remove(key)
                logger.info("Removed invalid API key (pool size: %d)", len(self._keys))

    async def add_key(self, key: str) -> None:
        """Add a new API key to the pool at runtime."""
        if not key:
            raise ValueError("Credential key cannot be empty")
        async with self._lock:
            if key in self._keys:
                return
            self._keys.append(key)
            logger.info("Added API key (pool size: %d)", len(self._keys))

    def is_empty(self) -> bool:
        """Return True if no keys remain in the pool."""
        return len(self._keys) == 0

    def size(self) -> int:
        """Return the number of keys in the pool."""
        return len(self._keys)

    @staticmethod
    def from_env_keys(env_keys: list[str]) -> CredentialPool:
        """Create a pool from a list of environment variable names.

        Only non-empty values are included.
        """
        import os

        keys: list[str] = []
        for env_var in env_keys:
            val = os.environ.get(env_var, "").strip()
            if val:
                keys.append(val)
        return CredentialPool(keys)