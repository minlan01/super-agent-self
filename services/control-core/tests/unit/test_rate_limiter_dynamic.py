"""Tests for Rate Limiter hot-reload and admin endpoints."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.middleware.rate_limiter import (
    RateLimiter,
    get_active_limiter,
    set_active_limiter,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _valid_yaml() -> dict:
    """Return a valid rate-limits config dict."""
    return {
        "rate_limits": {
            "default": {"max_requests": 60, "window_seconds": 60},
            "routes": {
                "/api/v1/auth": {"max_requests": 10, "window_seconds": 60},
                "/api/v1/chat": {"max_requests": 30, "window_seconds": 60},
            },
        }
    }


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _make_limiter(config_path: str) -> RateLimiter:
    """Create a RateLimiter wired to the given config file."""
    return RateLimiter(app=MagicMock(), config_path=config_path)


# ── Config validation tests ────────────────────────────────────────────────


class TestConfigValidation:
    """_validate_config should catch every class of bad input."""

    def test_valid_config_passes(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))
        # No exception raised during construction
        assert limiter.max_requests == 60
        assert limiter.route_limits["/api/v1/auth"] == (10, 60)

    def test_missing_rate_limits_key(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, {"something_else": {}})
        # Should keep defaults
        limiter = _make_limiter(str(cfg_path))
        assert limiter.max_requests == 60

    def test_missing_default_key(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, {"rate_limits": {"routes": {}}})
        limiter = _make_limiter(str(cfg_path))
        assert limiter.max_requests == 60  # kept default

    def test_non_positive_max_requests(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        data = _valid_yaml()
        data["rate_limits"]["default"]["max_requests"] = 0
        _write_yaml(cfg_path, data)
        limiter = _make_limiter(str(cfg_path))
        # Should keep default
        assert limiter.max_requests == 60

    def test_negative_window_seconds(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        data = _valid_yaml()
        data["rate_limits"]["default"]["window_seconds"] = -5
        _write_yaml(cfg_path, data)
        limiter = _make_limiter(str(cfg_path))
        assert limiter.window_seconds == 60

    def test_route_missing_max_requests(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        data = _valid_yaml()
        data["rate_limits"]["routes"]["/api/v1/auth"] = {"window_seconds": 60}
        _write_yaml(cfg_path, data)
        limiter = _make_limiter(str(cfg_path))
        # Route should not be loaded, but default stays
        assert "/api/v1/auth" not in limiter.route_limits

    def test_route_missing_window_seconds(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        data = _valid_yaml()
        data["rate_limits"]["routes"]["/api/v1/chat"] = {"max_requests": 30}
        _write_yaml(cfg_path, data)
        limiter = _make_limiter(str(cfg_path))
        assert "/api/v1/chat" not in limiter.route_limits

    def test_route_non_int_max_requests(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        data = _valid_yaml()
        data["rate_limits"]["routes"]["/api/v1/auth"]["max_requests"] = "abc"
        _write_yaml(cfg_path, data)
        limiter = _make_limiter(str(cfg_path))
        assert "/api/v1/auth" not in limiter.route_limits

    def test_routes_not_mapping(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        data = _valid_yaml()
        data["rate_limits"]["routes"] = "not_a_dict"
        _write_yaml(cfg_path, data)
        limiter = _make_limiter(str(cfg_path))
        assert limiter.route_limits == {}

    def test_top_level_not_mapping(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        cfg_path.write_text("42", encoding="utf-8")
        limiter = _make_limiter(str(cfg_path))
        assert limiter.max_requests == 60  # kept default


# ── Hot-reload (manual) tests ──────────────────────────────────────────────


class TestManualReload:
    """reload_config() should pick up file changes."""

    def test_reload_config_with_valid_yaml(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))
        assert limiter.route_limits["/api/v1/auth"] == (10, 60)

        # Update YAML on disk
        new_data = _valid_yaml()
        new_data["rate_limits"]["routes"]["/api/v1/auth"]["max_requests"] = 50
        _write_yaml(cfg_path, new_data)

        result = limiter.reload_config()
        assert limiter.route_limits["/api/v1/auth"] == (50, 60)
        assert result["limits"]["/api/v1/auth"] == (50, 60)

    def test_reload_config_with_invalid_yaml_keeps_old(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))
        assert limiter.route_limits["/api/v1/auth"] == (10, 60)

        # Write invalid config
        cfg_path.write_text("not: valid: yaml: [", encoding="utf-8")
        result = limiter.reload_config()

        # Old config must still be intact
        assert limiter.route_limits["/api/v1/auth"] == (10, 60)

    def test_reload_config_returns_current_config(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))

        result = limiter.reload_config()
        assert "limits" in result
        assert "default" in result
        assert result["default"] == (60, 60)


# ── Hot-reload (poll) tests ────────────────────────────────────────────────


class TestPollReload:
    """_check_config_reload() should detect mtime changes."""

    def test_mtime_change_triggers_reload(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))
        limiter._reload_interval = 0  # force check every time

        # Force last check to the past
        limiter._last_reload_check = 0.0
        # Advance mtime into the future
        new_data = _valid_yaml()
        new_data["rate_limits"]["default"]["max_requests"] = 100
        _write_yaml(cfg_path, new_data)
        # Ensure mtime is different
        os.utime(str(cfg_path), (time.time() + 10, time.time() + 10))

        limiter._check_config_reload()
        assert limiter.max_requests == 100

    def test_no_mtime_change_no_reload(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))
        limiter._reload_interval = 0

        # Read current mtime so it won't change
        limiter._config_mtime = os.path.getmtime(str(cfg_path))
        limiter._last_reload_check = 0.0

        # Write same content — mtime may or may not change, so lock it
        original_max = limiter.max_requests
        limiter._check_config_reload()
        assert limiter.max_requests == original_max

    def test_reload_interval_respected(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))
        limiter._reload_interval = 9999.0  # very long interval
        limiter._last_reload_check = time.time()

        # Write new config and advance mtime
        new_data = _valid_yaml()
        new_data["rate_limits"]["default"]["max_requests"] = 200
        _write_yaml(cfg_path, new_data)
        os.utime(str(cfg_path), (time.time() + 10, time.time() + 10))

        limiter._check_config_reload()
        # Should NOT have reloaded because interval not elapsed
        assert limiter.max_requests == 60

    def test_missing_file_no_crash(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))
        limiter._reload_interval = 0
        limiter._last_reload_check = 0.0

        # Delete the file
        cfg_path.unlink()
        limiter._check_config_reload()
        # Should not crash, keeps old config
        assert limiter.max_requests == 60


# ── get_current_config tests ──────────────────────────────────────────────


class TestGetCurrentConfig:
    """get_current_config() should return a snapshot without side-effects."""

    def test_returns_limits_and_default(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))

        config = limiter.get_current_config()
        assert config["default"] == (60, 60)
        assert config["limits"]["/api/v1/auth"] == (10, 60)

    def test_returns_copy_not_reference(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))

        config = limiter.get_current_config()
        # Mutating the returned dict should not affect the limiter
        config["limits"]["/new"] = (99, 99)
        assert "/new" not in limiter.route_limits


# ── Active limiter registry tests ─────────────────────────────────────────


class TestActiveLimiterRegistry:
    """set_active_limiter / get_active_limiter module-level helpers."""

    def test_set_and_get(self, tmp_path: Path):
        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())
        limiter = _make_limiter(str(cfg_path))
        # Constructor already called set_active_limiter
        assert get_active_limiter() is limiter

    def test_get_before_set_returns_none(self):
        # Since last test already set one, this tests the general contract
        # but we explicitly set None first
        set_active_limiter(None)
        assert get_active_limiter() is None
        # Restore for other tests
        # (each test that creates a limiter will set it again)


# ── Admin endpoint tests ──────────────────────────────────────────────────


class TestAdminEndpoints:
    """Integration tests for GET /admin/rate-limits and POST /admin/rate-limits/reload."""

    def _build_app(self, tmp_path: Path) -> tuple[FastAPI, TestClient, str]:
        """Create a test app with the admin routes and a fresh limiter.

        P1: require_auth defaults to True, and require_permission() then
        queries RBAC tables for the resolved user — against the global
        engine when get_db is not overridden.  For this isolated app we
        disable require_auth (synthetic-admin path, no DB touched) and
        override ``_resolve_current_user`` — the function object
        require_permission actually Depends on (get_current_user is only
        a re-export alias, overriding it has no effect here).
        """
        import os

        from apps.api_server.dependencies import _resolve_current_user
        from apps.api_server.routes.admin import router as admin_router
        from packages.config import clear_settings_cache

        cfg_path = tmp_path / "rate_limits.yaml"
        _write_yaml(cfg_path, _valid_yaml())

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")

        # Fake admin user (synthetic, never attached to a session).
        from packages.db.models import User, UserRole
        _fake_admin = User(
            id="test-admin",
            username="admin",
            email=None,
            hashed_password="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        app.dependency_overrides[_resolve_current_user] = lambda: _fake_admin

        os.environ["REQUIRE_AUTH"] = "false"
        clear_settings_cache()

        # Create limiter and register as active
        limiter = RateLimiter(app=app, config_path=str(cfg_path))
        client = TestClient(app)
        return app, client, str(cfg_path)

    def test_get_rate_limits(self, tmp_path: Path):
        _app, client, _cfg = self._build_app(tmp_path)

        resp = client.get("/api/v1/admin/rate-limits")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "limits" in body["data"]
        assert "default" in body["data"]
        assert body["data"]["default"] == [60, 60]

    def test_reload_rate_limits(self, tmp_path: Path):
        app, client, cfg_path = self._build_app(tmp_path)

        # Write new config
        new_data = _valid_yaml()
        new_data["rate_limits"]["default"]["max_requests"] = 99
        _write_yaml(Path(cfg_path), new_data)

        resp = client.post("/api/v1/admin/rate-limits/reload")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["default"] == [99, 60]

    def test_reload_preserves_old_on_invalid(self, tmp_path: Path):
        app, client, cfg_path = self._build_app(tmp_path)

        # Write invalid YAML
        Path(cfg_path).write_text("broken: [", encoding="utf-8")

        resp = client.post("/api/v1/admin/rate-limits/reload")
        assert resp.status_code == 200
        body = resp.json()
        # Should keep the old default
        assert body["data"]["default"] == [60, 60]

    def test_get_rate_limits_without_limiter(self, tmp_path: Path):
        """When no limiter is registered, should return 503."""
        from apps.api_server.dependencies import get_current_user
        from apps.api_server.routes.admin import router as admin_router
        from packages.middleware.rate_limiter import set_active_limiter

        set_active_limiter(None)

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")

        from packages.db.models import User, UserRole
        _fake_admin = User(
            id="test-admin", username="admin", email=None,
            hashed_password="", role=UserRole.ADMIN, is_active=True,
        )
        app.dependency_overrides[get_current_user] = lambda: _fake_admin

        client = TestClient(app)
        resp = client.get("/api/v1/admin/rate-limits")
        assert resp.status_code == 503

    def test_reload_without_limiter(self, tmp_path: Path):
        """When no limiter is registered, reload should return 503."""
        from apps.api_server.dependencies import get_current_user
        from apps.api_server.routes.admin import router as admin_router
        from packages.middleware.rate_limiter import set_active_limiter

        set_active_limiter(None)

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")

        from packages.db.models import User, UserRole
        _fake_admin = User(
            id="test-admin", username="admin", email=None,
            hashed_password="", role=UserRole.ADMIN, is_active=True,
        )
        app.dependency_overrides[get_current_user] = lambda: _fake_admin

        client = TestClient(app)
        resp = client.post("/api/v1/admin/rate-limits/reload")
        assert resp.status_code == 503


# ── Backward compatibility ─────────────────────────────────────────────────


class TestBackwardCompatNoConfigPath:
    """Without config_path, the limiter should work exactly as before."""

    def test_no_config_path_no_crash(self):
        limiter = RateLimiter(app=MagicMock(), max_requests=5, window_seconds=60)
        assert limiter.max_requests == 5
        assert limiter.route_limits == {}

    def test_check_reload_is_noop(self):
        limiter = RateLimiter(app=MagicMock())
        limiter._check_config_reload()  # should not crash

    def test_reload_config_is_noop(self):
        limiter = RateLimiter(app=MagicMock(), max_requests=5, window_seconds=30)
        result = limiter.reload_config()
        assert result["default"] == (5, 30)
        assert result["limits"] == {}

    def test_get_current_config_no_config(self):
        limiter = RateLimiter(app=MagicMock(), max_requests=10, window_seconds=20)
        config = limiter.get_current_config()
        assert config["default"] == (10, 20)
        assert config["limits"] == {}

    def test_existing_is_allowed_still_works(self):
        limiter = RateLimiter(app=MagicMock(), max_requests=3, window_seconds=60)
        for _ in range(3):
            assert limiter._is_allowed("c1", "/api/v1/tasks")
        assert limiter._is_allowed("c1", "/api/v1/tasks") is False
