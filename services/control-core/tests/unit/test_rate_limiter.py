"""Tests for Rate Limiting middleware — global and per-route."""

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from packages.middleware.rate_limiter import RateLimiter

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_request(path: str = "/api/v1/tasks", client_host: str = "127.0.0.1"):
    request = MagicMock()
    request.url.path = path
    request.client = MagicMock()
    request.client.host = client_host
    request.headers = {}
    return request


def _route_limits():
    """Standard per-route limits used across tests."""
    return {
        "/api/v1/auth": (10, 60),
        "/api/v1/chat": (30, 60),
        "/api/v1/admin": (5, 60),
        "/api/v1/tasks": (20, 60),
    }


# ── Existing tests (backward compatibility) ────────────────────────────────


class TestRateLimiter:
    """Tests that exercise the original single-limit behaviour."""

    def test_allows_under_limit(self):
        limiter = RateLimiter(app=MagicMock(), max_requests=5, window_seconds=60)
        for _ in range(5):
            assert limiter._is_allowed("client1", "/api/v1/tasks")

    def test_blocks_over_limit(self):
        limiter = RateLimiter(app=MagicMock(), max_requests=3, window_seconds=60)
        for _ in range(3):
            limiter._is_allowed("client1", "/api/v1/tasks")
        assert limiter._is_allowed("client1", "/api/v1/tasks") is False

    def test_different_clients_independent(self):
        limiter = RateLimiter(app=MagicMock(), max_requests=2, window_seconds=60)
        assert limiter._is_allowed("client1", "/api/v1/tasks")
        assert limiter._is_allowed("client1", "/api/v1/tasks")
        # client2 should still be allowed
        assert limiter._is_allowed("client2", "/api/v1/tasks")

    def test_window_expiry(self):
        limiter = RateLimiter(app=MagicMock(), max_requests=2, window_seconds=1)
        limiter._is_allowed("client1", "/api/v1/tasks")
        limiter._is_allowed("client1", "/api/v1/tasks")
        assert limiter._is_allowed("client1", "/api/v1/tasks") is False

        # Wait for window to expire
        time.sleep(1.1)
        assert limiter._is_allowed("client1", "/api/v1/tasks") is True

    def test_get_client_id_from_forwarded(self):
        limiter = RateLimiter(app=MagicMock())
        request = _make_request()
        request.headers = {"x-forwarded-for": "10.0.0.1, 10.0.0.2"}
        assert limiter._get_client_id(request) == "10.0.0.1"

    def test_get_client_id_direct(self):
        limiter = RateLimiter(app=MagicMock())
        request = _make_request()
        assert limiter._get_client_id(request) == "127.0.0.1"

    def test_cleans_old_entries(self):
        limiter = RateLimiter(app=MagicMock(), max_requests=100, window_seconds=1)
        # Add some old entries
        limiter._requests["c1"] = {"__default__": [time.time() - 2, time.time() - 1.5]}
        # This should clean old entries and add new one
        limiter._is_allowed("c1", "/api/v1/tasks")
        # Old entries should be gone
        assert len(limiter._requests["c1"]["__default__"]) == 1


# ── Per-route rate limiting tests ───────────────────────────────────────────


class TestPerRouteLimits:
    """Tests for per-route configurable limits."""

    def test_auth_route_enforces_strict_limit(self):
        """Auth routes should be limited to 10 req/min."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=60, route_limits=_route_limits()
        )
        # Should allow exactly 10 requests
        for i in range(10):
            assert limiter._is_allowed("client1", "/api/v1/auth/login") is True, f"request {i}"
        # 11th should be blocked
        assert limiter._is_allowed("client1", "/api/v1/auth/login") is False

    def test_chat_route_allows_30(self):
        """Chat route should be limited to 30 req/min."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=60, route_limits=_route_limits()
        )
        for i in range(30):
            assert limiter._is_allowed("client1", "/api/v1/chat") is True, f"request {i}"
        assert limiter._is_allowed("client1", "/api/v1/chat") is False

    def test_admin_route_very_strict(self):
        """Admin routes should be limited to 5 req/min."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=60, route_limits=_route_limits()
        )
        for i in range(5):
            assert limiter._is_allowed("client1", "/api/v1/admin/backup") is True, f"request {i}"
        assert limiter._is_allowed("client1", "/api/v1/admin/backup") is False

    def test_tasks_post_route_20(self):
        """Tasks route should be limited to 20 req/min."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=60, route_limits=_route_limits()
        )
        for i in range(20):
            assert limiter._is_allowed("client1", "/api/v1/tasks") is True, f"request {i}"
        assert limiter._is_allowed("client1", "/api/v1/tasks") is False

    def test_default_limit_for_unmatched_routes(self):
        """Routes not in route_limits should fall back to the global default."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=5, window_seconds=60, route_limits=_route_limits()
        )
        # /api/v1/memory is not in route_limits, so should use global default of 5
        for i in range(5):
            assert limiter._is_allowed("client1", "/api/v1/memory") is True, f"request {i}"
        assert limiter._is_allowed("client1", "/api/v1/memory") is False

    def test_longest_prefix_match(self):
        """Longer/more-specific prefix should win over shorter ones."""
        route_limits = {
            "/api/v1": (100, 60),
            "/api/v1/auth": (3, 60),
        }
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=60, route_limits=route_limits
        )
        # /api/v1/auth/login matches /api/v1/auth (len 13) over /api/v1 (len 7)
        for i in range(3):
            assert limiter._is_allowed("client1", "/api/v1/auth/login") is True
        assert limiter._is_allowed("client1", "/api/v1/auth/login") is False

        # /api/v1/tasks matches only /api/v1, so gets 100
        for i in range(100):
            assert limiter._is_allowed("client1", "/api/v1/tasks") is True
        assert limiter._is_allowed("client1", "/api/v1/tasks") is False

    def test_per_route_quotas_are_independent(self):
        """Hitting one route's limit should not affect another route."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=60, route_limits=_route_limits()
        )
        # Exhaust the admin quota (5)
        for _ in range(5):
            limiter._is_allowed("client1", "/api/v1/admin/backup")
        assert limiter._is_allowed("client1", "/api/v1/admin/backup") is False

        # Auth route for the same client should still work
        assert limiter._is_allowed("client1", "/api/v1/auth/login") is True

    def test_different_clients_per_route_independent(self):
        """Different clients get independent per-route quotas."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=60, route_limits=_route_limits()
        )
        # Exhaust client1's admin quota
        for _ in range(5):
            limiter._is_allowed("client1", "/api/v1/admin/backup")
        assert limiter._is_allowed("client1", "/api/v1/admin/backup") is False

        # client2 should still be allowed
        assert limiter._is_allowed("client2", "/api/v1/admin/backup") is True

    def test_exact_path_match_uses_route_limit(self):
        """An exact path equal to the prefix should match."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=60, route_limits=_route_limits()
        )
        for i in range(10):
            assert limiter._is_allowed("client1", "/api/v1/auth") is True
        assert limiter._is_allowed("client1", "/api/v1/auth") is False

    def test_sub_path_matches_parent_prefix(self):
        """A sub-path like /api/v1/auth/register should match /api/v1/auth."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=60, route_limits=_route_limits()
        )
        # Use 5 on login, 5 on register — shared quota under /api/v1/auth
        for _ in range(5):
            limiter._is_allowed("client1", "/api/v1/auth/login")
        for _ in range(5):
            limiter._is_allowed("client1", "/api/v1/auth/register")
        # Total 10 used, next should be blocked
        assert limiter._is_allowed("client1", "/api/v1/auth/login") is False


# ── Exemption tests ────────────────────────────────────────────────────────


class TestExemptRoutes:
    """Routes that should bypass rate limiting entirely."""

    @pytest.mark.parametrize("path", [
        "/ws",
        "/ws/",
        "/ws/chat",
        "/ws/chat/notifications",
    ])
    def test_websocket_exempt(self, path):
        assert RateLimiter._is_exempt(path) is True

    @pytest.mark.parametrize("path", [
        "/health",
        "/api/v1/health",
        "/api/v1/health/ready",
        "/api/v1/health/live",
        "/api/v1/metrics",
        "/api/v1/metrics/prometheus",
    ])
    def test_health_and_metrics_exempt(self, path):
        assert RateLimiter._is_exempt(path) is True

    @pytest.mark.parametrize("path", [
        "/api/v1/tasks",
        "/api/v1/auth/login",
        "/api/v1/chat",
        "/api/v1/admin/backup",
        "/api/v1/memory",
    ])
    def test_normal_routes_not_exempt(self, path):
        assert RateLimiter._is_exempt(path) is False


# ── Config loading from YAML ───────────────────────────────────────────────


class TestConfigLoading:
    """Verify rate_limits.yaml is loadable and produces expected limits."""

    def test_load_yaml_config(self, tmp_path: Path):
        """Simulate loading rate_limits.yaml and constructing route_limits."""
        config_content = {
            "rate_limits": {
                "default": {"max_requests": 60, "window_seconds": 60},
                "routes": {
                    "/api/v1/auth": {"max_requests": 10, "window_seconds": 60},
                    "/api/v1/chat": {"max_requests": 30, "window_seconds": 60},
                    "/api/v1/admin": {"max_requests": 5, "window_seconds": 60},
                    "/api/v1/tasks": {"max_requests": 20, "window_seconds": 60},
                },
            }
        }
        yaml_path = tmp_path / "rate_limits.yaml"
        yaml_path.write_text(yaml.dump(config_content), encoding="utf-8")

        loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        rl_section = loaded["rate_limits"]
        default_cfg = rl_section["default"]
        default = (default_cfg["max_requests"], default_cfg["window_seconds"])

        route_limits: dict[str, tuple[int, int]] = {}
        for prefix, cfg in rl_section["routes"].items():
            route_limits[prefix] = (cfg["max_requests"], cfg["window_seconds"])

        assert default == (60, 60)
        assert route_limits["/api/v1/auth"] == (10, 60)
        assert route_limits["/api/v1/chat"] == (30, 60)
        assert route_limits["/api/v1/admin"] == (5, 60)
        assert route_limits["/api/v1/tasks"] == (20, 60)

    def test_actual_rate_limits_yaml_exists_and_valid(self):
        """The real configs/rate_limits.yaml should be valid."""
        config_path = Path("configs/rate_limits.yaml")
        assert config_path.exists(), "configs/rate_limits.yaml must exist"
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        rl = data["rate_limits"]
        assert "default" in rl
        assert "routes" in rl
        assert rl["default"]["max_requests"] > 0
        assert rl["default"]["window_seconds"] > 0

    def test_loaded_config_works_with_limiter(self):
        """End-to-end: load real YAML and use it with RateLimiter."""
        config_path = Path("configs/rate_limits.yaml")
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        rl = data["rate_limits"]
        default_cfg = rl["default"]
        route_limits: dict[str, tuple[int, int]] = {}
        for prefix, cfg in rl["routes"].items():
            route_limits[prefix] = (cfg["max_requests"], cfg["window_seconds"])

        limiter = RateLimiter(
            app=MagicMock(),
            max_requests=default_cfg["max_requests"],
            window_seconds=default_cfg["window_seconds"],
            route_limits=route_limits,
        )

        # Auth should be limited to whatever the YAML says for auth
        auth_limit = rl["routes"]["api/v1/auth"]["max_requests"] if "/api/v1/auth" not in rl["routes"] else rl["routes"]["/api/v1/auth"]["max_requests"]
        for _ in range(auth_limit):
            assert limiter._is_allowed("client1", "/api/v1/auth/login") is True
        assert limiter._is_allowed("client1", "/api/v1/auth/login") is False


# ── Backward compatibility ─────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Without route_limits the limiter should behave identically to before."""

    def test_no_route_limits_uses_global(self):
        """No route_limits means every route uses the global limit."""
        limiter = RateLimiter(app=MagicMock(), max_requests=3, window_seconds=60)
        for _ in range(3):
            assert limiter._is_allowed("client1", "/api/v1/auth/login") is True
        assert limiter._is_allowed("client1", "/api/v1/auth/login") is False

    def test_no_route_limits_different_routes_share_quota(self):
        """Without per-route limits, all routes share the same global bucket."""
        limiter = RateLimiter(app=MagicMock(), max_requests=3, window_seconds=60)
        limiter._is_allowed("client1", "/api/v1/auth/login")
        limiter._is_allowed("client1", "/api/v1/chat")
        limiter._is_allowed("client1", "/api/v1/tasks")
        assert limiter._is_allowed("client1", "/api/v1/memory") is False

    def test_empty_route_limits_same_as_none(self):
        """An empty route_limits dict should behave like no route_limits."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=3, window_seconds=60, route_limits={}
        )
        for _ in range(3):
            assert limiter._is_allowed("client1", "/api/v1/tasks") is True
        assert limiter._is_allowed("client1", "/api/v1/tasks") is False

    def test_exemptions_work_without_route_limits(self):
        """Exempt routes should be detected even without route_limits."""
        limiter = RateLimiter(app=MagicMock(), max_requests=1, window_seconds=60)
        assert RateLimiter._is_exempt("/health") is True
        assert RateLimiter._is_exempt("/ws/chat") is True

    def test_window_expiry_per_route(self):
        """Window expiry should work correctly for per-route buckets."""
        limiter = RateLimiter(
            app=MagicMock(), max_requests=60, window_seconds=1,
            route_limits={"/api/v1/auth": (2, 1)},
        )
        limiter._is_allowed("client1", "/api/v1/auth/login")
        limiter._is_allowed("client1", "/api/v1/auth/login")
        assert limiter._is_allowed("client1", "/api/v1/auth/login") is False

        time.sleep(1.1)
        assert limiter._is_allowed("client1", "/api/v1/auth/login") is True
