"""High-level cache manager with namespaced keys and invalidation."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from .base import CacheBackend
from .memory import MemoryCacheBackend

logger = logging.getLogger(__name__)


def _load_cache_config() -> dict:
    """Load ``configs/cache.yaml`` if it exists."""
    config_path = Path("configs/cache.yaml")
    if not config_path.exists():
        return {}
    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.warning("Failed to load cache config from %s: %s", config_path, e)
        return {}


class CacheManager:
    """High-level cache with namespaced keys, per-namespace TTL, and bulk invalidation.

    Each logical domain (tasks, dashboard, skills, ...) gets its own namespace.
    Keys are stored as ``{prefix}:{namespace}:{key}`` so that clearing a namespace
    is a single ``clear("prefix:namespace:*")`` call.

    Configuration is read from ``configs/cache.yaml`` when available, with
    sensible defaults otherwise.
    """

    def __init__(
        self,
        backend: CacheBackend | None = None,
        prefix: str = "myagent",
    ):
        self._prefix = prefix
        self._config = _load_cache_config()
        self._namespaces: dict[str, dict[str, Any]] = self._config.get("cache", {}).get(
            "namespaces", {}
        )

        if backend is not None:
            self._backend = backend
        else:
            self._backend = self._create_backend_from_config()

    def _create_backend_from_config(self) -> CacheBackend:
        """Factory: create backend based on cache.yaml config."""
        cache_cfg = self._config.get("cache", {})
        backend_type = cache_cfg.get("backend", "memory")

        if backend_type == "redis":
            try:
                from .redis import RedisCacheBackend

                redis_url = cache_cfg.get("redis_url", "redis://localhost:6379/0")
                return RedisCacheBackend(
                    redis_url=redis_url,
                    default_ttl=cache_cfg.get("default_ttl", 300),
                )
            except (ImportError, Exception):
                logger.warning(
                    "Failed to create Redis backend, falling back to memory",
                    exc_info=True,
                )

        # Default: memory backend
        return MemoryCacheBackend(
            max_size=cache_cfg.get("max_size", 1000),
            default_ttl=cache_cfg.get("default_ttl", 300),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ns_key(self, namespace: str, key: str, *, user_id: str | None = None) -> str:
        """Build a namespaced cache key.

        When ``user_id`` is provided, the key includes a user segment to
        isolate per-user data (multi-tenancy)::

            {prefix}:{namespace}:u:{user_id}:{key}

        Without ``user_id`` the classic format is used::

            {prefix}:{namespace}:{key}

        An empty ``user_id`` string is treated as None to prevent key
        collisions between ``u::{key}`` and ``{key}``.
        """
        uid = user_id or None
        if uid:
            return f"{self._prefix}:{namespace}:u:{uid}:{key}"
        return f"{self._prefix}:{namespace}:{key}"

    def _ns_pattern(self, namespace: str, *, user_id: str | None = None) -> str:
        """Build a namespace wildcard pattern for bulk invalidation."""
        uid = user_id or None
        if uid:
            return f"{self._prefix}:{namespace}:u:{uid}:*"
        return f"{self._prefix}:{namespace}:*"

    def _ns_ttl(self, namespace: str) -> float | None:
        """Return the configured TTL for *namespace*, or None for default."""
        ns_cfg = self._namespaces.get(namespace)
        if ns_cfg and "ttl" in ns_cfg:
            return float(ns_cfg["ttl"])
        return None

    @staticmethod
    def hash_query(params: Any) -> str:
        """Deterministic hash of query parameters for use as a cache key."""
        raw = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ------------------------------------------------------------------
    # Generic namespaced operations
    # ------------------------------------------------------------------

    async def get(self, namespace: str, key: str, *, user_id: str | None = None) -> Any | None:
        return await self._backend.get(self._ns_key(namespace, key, user_id=user_id))

    async def set(
        self, namespace: str, key: str, value: Any, *, user_id: str | None = None
    ) -> None:
        await self._backend.set(
            self._ns_key(namespace, key, user_id=user_id),
            value, ttl=self._ns_ttl(namespace),
        )

    async def invalidate(self, namespace: str, *, user_id: str | None = None) -> int:
        return await self._backend.clear(self._ns_pattern(namespace, user_id=user_id))

    # ------------------------------------------------------------------
    # Convenience shortcuts for common namespaces
    # ------------------------------------------------------------------

    async def get_tasks(self, query_hash: str, *, user_id: str | None = None) -> Any | None:
        return await self.get("tasks", query_hash, user_id=user_id)

    async def set_tasks(self, query_hash: str, data: Any, *, user_id: str | None = None) -> None:
        await self.set("tasks", query_hash, data, user_id=user_id)

    async def invalidate_tasks(self, *, user_id: str | None = None) -> int:
        return await self.invalidate("tasks", user_id=user_id)

    async def get_dashboard(self, *, user_id: str | None = None) -> Any | None:
        return await self.get("dashboard", "stats", user_id=user_id)

    async def set_dashboard(self, data: Any, *, user_id: str | None = None) -> None:
        await self.set("dashboard", "stats", data, user_id=user_id)

    async def invalidate_dashboard(self, *, user_id: str | None = None) -> int:
        return await self.invalidate("dashboard", user_id=user_id)

    async def get_skills(self, query_hash: str, *, user_id: str | None = None) -> Any | None:
        return await self.get("skills", query_hash, user_id=user_id)

    async def set_skills(self, query_hash: str, data: Any, *, user_id: str | None = None) -> None:
        await self.set("skills", query_hash, data, user_id=user_id)

    async def invalidate_skills(self, *, user_id: str | None = None) -> int:
        return await self.invalidate("skills", user_id=user_id)
