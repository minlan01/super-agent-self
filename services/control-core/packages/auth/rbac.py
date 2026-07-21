"""RBAC Service — permission checking with in-memory cache."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import yaml

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = structlog.get_logger()


class _PermissionCache:
    """TTL-based in-memory permission cache per user with bounded size."""

    _MAX_SIZE = 10_000
    _CLEANUP_INTERVAL = 60

    def __init__(self, ttl_seconds: int = 300, max_size: int = _MAX_SIZE):
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._store: dict[str, tuple[list[str], float]] = {}  # user_id -> (permissions, timestamp)
        self._last_cleanup: float = 0.0

    def _evict_expired(self) -> None:
        """Remove expired entries and trim cache to max size (oldest first)."""
        now = time.time()
        if now - self._last_cleanup < self._CLEANUP_INTERVAL and len(self._store) <= self._max_size:
            return
        self._last_cleanup = now
        expired = [uid for uid, (_, ts) in self._store.items() if now - ts > self._ttl]
        for uid in expired:
            del self._store[uid]

        # Cap dict size — evict oldest entries first
        if len(self._store) > self._max_size:
            sorted_keys = sorted(self._store, key=lambda uid: self._store[uid][1])
            excess = len(self._store) - self._max_size
            for uid in sorted_keys[:excess]:
                del self._store[uid]

    def get(self, user_id: str) -> list[str] | None:
        entry = self._store.get(user_id)
        if entry is None:
            return None
        permissions, ts = entry
        if time.time() - ts > self._ttl:
            del self._store[user_id]
            return None
        return permissions

    def set(self, user_id: str, permissions: list[str]) -> None:
        self._evict_expired()
        self._store[user_id] = (permissions, time.time())

    def invalidate(self, user_id: str) -> None:
        self._store.pop(user_id, None)

    def clear(self) -> None:
        self._store.clear()


class _RedisPermissionCache:
    """Optional Redis-backed permission cache for multi-process deployments."""

    def __init__(self, redis_client, ttl: int = 300, prefix="rbac:perm:"):
        self._r = redis_client
        self._ttl = ttl
        self._prefix = prefix

    def get(self, user_id: str) -> list[str] | None:
        raw = self._r.get(f"{self._prefix}{user_id}")
        if raw:
            return json.loads(raw)
        return None

    def set(self, user_id: str, permissions: list[str]) -> None:
        self._r.setex(f"{self._prefix}{user_id}", self._ttl, json.dumps(permissions))

    def invalidate(self, user_id: str) -> None:
        self._r.delete(f"{self._prefix}{user_id}")

    def clear(self) -> None:
        for key in self._r.scan_iter(match=f"{self._prefix}*"):
            self._r.delete(key)


class RBACService:
    """Role-Based Access Control service."""

    def __init__(self, cache_ttl: int = 300):
        self._cache = _PermissionCache(ttl_seconds=cache_ttl)
        self._route_permissions: dict[str, list[str]] = {}
        self._public_routes: list[str] = []
        self._authenticated_routes: list[str] = []
        self._legacy_admin_bypass: bool = False
        self._rbac_enabled: bool = True
        self._loaded = False

    def load_config(self) -> None:
        """Load RBAC configuration from configs/rbac.yaml."""
        if self._loaded:
            return
        config_path = Path("configs/rbac.yaml")
        if not config_path.exists():
            logger.warning("configs/rbac.yaml not found, RBAC using defaults")
            self._loaded = True
            return

        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            rbac = cfg.get("rbac", {})

            self._rbac_enabled = rbac.get("enabled", True)
            self._legacy_admin_bypass = rbac.get("legacy_admin_bypass", True)

            route_perms = rbac.get("route_permissions", {})
            self._public_routes = route_perms.get("public", [])
            self._authenticated_routes = route_perms.get("authenticated", [])

            cache_cfg = rbac.get("cache", {})
            if cache_cfg.get("enabled", True):
                self._cache = _PermissionCache(ttl_seconds=cache_cfg.get("ttl_seconds", 300))
            else:
                self._cache = _PermissionCache(ttl_seconds=0)

            self._loaded = True
            logger.info("RBAC config loaded: enabled=%s, %d public routes, %d authenticated routes",
                        self._rbac_enabled, len(self._public_routes), len(self._authenticated_routes))
        except Exception:
            logger.exception("Failed to load RBAC config — will retry on next access")

    def configure_cache_backend(self, redis_client) -> None:
        """Replace the in-memory permission cache with a Redis-backed one."""
        self._cache = _RedisPermissionCache(redis_client)
        logger.info("RBAC permission cache switched to Redis backend")

    @property
    def rbac_enabled(self) -> bool:
        if not self._loaded:
            self.load_config()
        return self._rbac_enabled

    @property
    def legacy_admin_bypass(self) -> bool:
        if not self._loaded:
            self.load_config()
        return self._legacy_admin_bypass

    @staticmethod
    def _normalize_path(path: str) -> str:
        normalized = re.sub(r"/+", "/", path)
        parts = []
        for part in normalized.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part and part != ".":
                parts.append(part)
        return "/" + "/".join(parts) if parts else "/"

    def _match_route(self, method: str, path: str, routes: list[str]) -> bool:
        norm_path = self._normalize_path(path)
        pattern = f"{method}:{norm_path}"
        for route in routes:
            if route == pattern:
                return True
            if route == norm_path:
                return True
            if route.endswith("/*"):
                prefix_with_method = route[:-1]
                if pattern.startswith(prefix_with_method):
                    return True
                if not route.startswith(("GET:", "POST:", "PUT:", "DELETE:", "PATCH:", "WS:")):
                    prefix_path = route[:-1]
                    if norm_path.startswith(prefix_path):
                        return True
        return False

    def is_public_route(self, method: str, path: str) -> bool:
        """Check if a route is public (no auth required)."""
        if not self._loaded:
            self.load_config()
        return self._match_route(method, path, self._public_routes)

    def is_authenticated_only(self, method: str, path: str) -> bool:
        """Check if a route only requires authentication (no specific permission)."""
        if not self._loaded:
            self.load_config()
        return self._match_route(method, path, self._authenticated_routes)

    def get_user_permissions(self, db: Session, user_id: str) -> list[str]:
        """Get permission strings for a user, with caching."""
        self._cache._evict_expired()
        # Check cache
        cached = self._cache.get(user_id)
        if cached is not None:
            return cached

        # Query DB
        from packages.db.repositories.rbac_repo import RBACRepository
        permissions = RBACRepository.get_user_permission_strings(db, user_id)

        # Cache result
        self._cache.set(user_id, permissions)
        return permissions

    def check_permission(self, db: Session, user_id: str, resource: str, action: str) -> bool:
        """Check if a user has a specific resource:action permission."""
        if not self.rbac_enabled:
            return True

        self._cache._evict_expired()
        permissions = self.get_user_permissions(db, user_id)

        # Check for exact match
        target = f"{resource}:{action}"
        if target in permissions:
            return True

        # Check for admin override (resource:admin implies all actions)
        if action != "admin" and f"{resource}:admin" in permissions:
            return True

        # Check for system:admin (super admin)
        if "system:admin" in permissions:
            return True

        return False

    def check_any_permission(self, db: Session, user_id: str, resource: str, actions: list[str]) -> bool:
        """Check if a user has any of the specified actions for a resource."""
        return any(self.check_permission(db, user_id, resource, action) for action in actions)

    def invalidate_user_cache(self, user_id: str) -> None:
        """Invalidate cached permissions for a user."""
        self._cache.invalidate(user_id)

    def invalidate_all_cache(self) -> None:
        """Clear the entire permission cache."""
        self._cache.clear()

    def seed_if_empty(self, db: Session) -> None:
        """Seed default roles and permissions if the roles table is empty."""
        from sqlalchemy import func, select

        from packages.db.models import Role
        count = db.scalar(select(func.count()).select_from(Role))
        if count == 0:
            from packages.db.repositories.rbac_repo import RBACRepository
            result = RBACRepository.seed_default_roles_and_permissions(db)
            db.flush()
            logger.info("Seeded %d default roles", len(result))


# Module-level singleton
_rbac_service: RBACService | None = None


def get_rbac_service() -> RBACService:
    """Get or create the singleton RBACService."""
    global _rbac_service
    if _rbac_service is None:
        _rbac_service = RBACService()
        _rbac_service.load_config()
    return _rbac_service
