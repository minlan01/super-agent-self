"""Unit tests for RBAC service — permission checking, caching, config loading."""

import time
from unittest.mock import MagicMock, patch

import pytest

from packages.auth.rbac import RBACService, _PermissionCache


class TestPermissionCache:
    """Tests for the in-memory permission TTL cache."""

    def test_cache_miss_returns_none(self):
        cache = _PermissionCache(ttl_seconds=60)
        assert cache.get("user1") is None

    def test_cache_set_and_get(self):
        cache = _PermissionCache(ttl_seconds=60)
        cache.set("user1", ["tasks:read", "tasks:write"])
        assert cache.get("user1") == ["tasks:read", "tasks:write"]

    def test_cache_ttl_expiry(self):
        cache = _PermissionCache(ttl_seconds=0)  # immediate expiry
        cache.set("user1", ["tasks:read"])
        time.sleep(0.01)
        assert cache.get("user1") is None

    def test_cache_invalidate(self):
        cache = _PermissionCache(ttl_seconds=60)
        cache.set("user1", ["tasks:read"])
        cache.invalidate("user1")
        assert cache.get("user1") is None

    def test_cache_invalidate_nonexistent(self):
        cache = _PermissionCache(ttl_seconds=60)
        cache.invalidate("nonexistent")  # Should not raise

    def test_cache_clear(self):
        cache = _PermissionCache(ttl_seconds=60)
        cache.set("user1", ["tasks:read"])
        cache.set("user2", ["memory:read"])
        cache.clear()
        assert cache.get("user1") is None
        assert cache.get("user2") is None

    def test_cache_overwrite(self):
        cache = _PermissionCache(ttl_seconds=60)
        cache.set("user1", ["tasks:read"])
        cache.set("user1", ["tasks:read", "tasks:write"])
        assert cache.get("user1") == ["tasks:read", "tasks:write"]


class TestRBACServicePermissionCheck:
    """Tests for RBACService.check_permission logic."""

    def setup_method(self):
        self.service = RBACService(cache_ttl=60)
        self.service._rbac_enabled = True
        self.service._legacy_admin_bypass = True
        self.service._loaded = True

    def test_rbac_disabled_allows_all(self):
        self.service._rbac_enabled = False
        mock_db = MagicMock()
        assert self.service.check_permission(mock_db, "user1", "tasks", "read") is True

    def test_system_admin_grants_all(self):
        mock_db = MagicMock()
        self.service._cache.set("user1", ["system:admin"])
        assert self.service.check_permission(mock_db, "user1", "tasks", "read") is True
        assert self.service.check_permission(mock_db, "user1", "tasks", "write") is True
        assert self.service.check_permission(mock_db, "user1", "anything", "admin") is True

    def test_resource_admin_grants_all_actions(self):
        mock_db = MagicMock()
        self.service._cache.set("user1", ["tasks:admin"])
        assert self.service.check_permission(mock_db, "user1", "tasks", "read") is True
        assert self.service.check_permission(mock_db, "user1", "tasks", "write") is True
        assert self.service.check_permission(mock_db, "user1", "tasks", "execute") is True

    def test_exact_permission_match(self):
        mock_db = MagicMock()
        self.service._cache.set("user1", ["tasks:read"])
        assert self.service.check_permission(mock_db, "user1", "tasks", "read") is True

    def test_no_permission_denied(self):
        mock_db = MagicMock()
        self.service._cache.set("user1", ["tasks:read"])
        assert self.service.check_permission(mock_db, "user1", "tasks", "write") is False

    def test_empty_permissions_denied(self):
        mock_db = MagicMock()
        self.service._cache.set("user1", [])
        assert self.service.check_permission(mock_db, "user1", "tasks", "read") is False

    def test_different_resource_denied(self):
        mock_db = MagicMock()
        self.service._cache.set("user1", ["tasks:read"])
        assert self.service.check_permission(mock_db, "user1", "memory", "read") is False

    def test_admin_action_not_granted_by_write(self):
        mock_db = MagicMock()
        self.service._cache.set("user1", ["tasks:write"])
        assert self.service.check_permission(mock_db, "user1", "tasks", "admin") is False

    def test_check_any_permission(self):
        mock_db = MagicMock()
        self.service._cache.set("user1", ["tasks:read"])
        assert self.service.check_any_permission(mock_db, "user1", "tasks", ["read", "write"]) is True
        assert self.service.check_any_permission(mock_db, "user1", "tasks", ["write", "admin"]) is False


class TestRBACServiceConfig:
    """Tests for RBAC config loading and route matching."""

    def test_default_config(self):
        service = RBACService()
        service._loaded = True
        assert service.rbac_enabled is True
        assert service.legacy_admin_bypass is False

    def test_is_public_route_with_exact_match(self):
        service = RBACService()
        service._loaded = True
        service._public_routes = ["POST:/api/v1/auth/login"]
        assert service.is_public_route("POST", "/api/v1/auth/login") is True

    def test_is_public_route_no_match(self):
        service = RBACService()
        service._loaded = True
        service._public_routes = ["POST:/api/v1/auth/login"]
        assert service.is_public_route("GET", "/api/v1/tasks") is False

    def test_is_public_route_wildcard(self):
        service = RBACService()
        service._loaded = True
        service._public_routes = ["GET:/api/v1/health"]
        assert service.is_public_route("GET", "/api/v1/health") is True

    def test_is_authenticated_only(self):
        service = RBACService()
        service._loaded = True
        service._authenticated_routes = ["GET:/api/v1/auth/me"]
        assert service.is_authenticated_only("GET", "/api/v1/auth/me") is True

    def test_invalidate_user_cache(self):
        service = RBACService(cache_ttl=60)
        service._cache.set("user1", ["tasks:read"])
        service.invalidate_user_cache("user1")
        assert service._cache.get("user1") is None

    def test_invalidate_all_cache(self):
        service = RBACService(cache_ttl=60)
        service._cache.set("user1", ["tasks:read"])
        service._cache.set("user2", ["memory:read"])
        service.invalidate_all_cache()
        assert service._cache.get("user1") is None
        assert service._cache.get("user2") is None
