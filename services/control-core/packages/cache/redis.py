"""Redis cache backend — requires redis>=5.0 (optional dependency)."""

from __future__ import annotations

import json
import logging
from typing import Any

from .base import CacheBackend

logger = logging.getLogger(__name__)


class RedisCacheBackend(CacheBackend):
    """Redis-backed cache with TTL support and automatic reconnection.

    Uses ``redis.asyncio`` for async operations.
    Falls back to serialization-safe JSON for values.

    When a Redis operation fails with a connection error, the client is
    marked unhealthy and subsequent operations short-circuit (return
    ``None`` / ``False`` / no-op) until a background ping succeeds,
    at which point the connection is restored transparently.
    """

    _RECONNECT_BACKOFF_SECONDS = 2.0

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        prefix: str = "myagent:",
        default_ttl: float = 300,
    ):
        try:
            import redis.asyncio as aioredis

            self._redis_url = redis_url
            self._redis = aioredis.from_url(redis_url, decode_responses=True)
        except ImportError:
            raise ImportError(
                "redis package is required for RedisCacheBackend. "
                "Install with: pip install redis>=5.0, or switch cache.backend to 'memory' in configs/cache.yaml"
            )
        self._prefix = prefix
        self._default_ttl = default_ttl
        self._healthy = True
        self._last_fail_time: float = 0.0

    def _prefixed(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def _ensure_connected(self) -> bool:
        """Check if the connection is alive; attempt reconnect if not.

        Returns True if the connection is usable, False otherwise.
        Uses a simple time-based backoff to avoid hammering a down server.
        """
        import time

        if self._healthy:
            return True

        now = time.time()
        if now - self._last_fail_time < self._RECONNECT_BACKOFF_SECONDS:
            return False

        try:
            await self._redis.ping()
            self._healthy = True
            logger.info("Redis connection restored")
            return True
        except Exception as e:
            self._last_fail_time = now
            logger.warning("Redis reconnection failed: %s", e)
            return False

    def _mark_unhealthy(self, exc: Exception) -> None:
        """Mark the connection as unhealthy after a failure."""
        import time

        self._healthy = False
        self._last_fail_time = time.time()
        logger.warning("Redis connection marked unhealthy: %s", exc)

    async def get(self, key: str) -> Any | None:
        if not await self._ensure_connected():
            return None
        try:
            value = await self._redis.get(self._prefixed(key))
        except Exception as e:
            self._mark_unhealthy(e)
            return None
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        if not await self._ensure_connected():
            return
        try:
            serialized = json.dumps(value)
            effective_ttl = ttl if ttl is not None else self._default_ttl
            await self._redis.set(self._prefixed(key), serialized, ex=int(effective_ttl))
        except Exception as e:
            self._mark_unhealthy(e)

    async def delete(self, key: str) -> None:
        if not await self._ensure_connected():
            return
        try:
            await self._redis.delete(self._prefixed(key))
        except Exception as e:
            self._mark_unhealthy(e)

    async def clear(self, pattern: str = "*") -> int:
        if not await self._ensure_connected():
            return 0
        full_pattern = self._prefixed(pattern)
        count = 0
        batch_size = 500
        try:
            batch: list[bytes | str] = []
            async for key in self._redis.scan_iter(match=full_pattern, count=batch_size):
                batch.append(key)
                if len(batch) >= batch_size:
                    await self._redis.delete(*batch)
                    count += len(batch)
                    batch.clear()
            if batch:
                await self._redis.delete(*batch)
                count += len(batch)
        except Exception as e:
            self._mark_unhealthy(e)
        return count

    async def exists(self, key: str) -> bool:
        if not await self._ensure_connected():
            return False
        try:
            return bool(await self._redis.exists(self._prefixed(key)))
        except Exception as e:
            self._mark_unhealthy(e)
            return False

    async def close(self) -> None:
        try:
            await self._redis.close()
        except Exception:
            logger.debug("Redis close failed", exc_info=True)
