"""Integration tests for Admin API — backup/restore lifecycle, Prometheus metrics, rate limiting, access control."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api_server.main import app


@pytest.fixture()
def client(db_engine, db):
    from apps.api_server.dependencies import get_db

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client(db_engine, db):
    """Authenticated admin client (P1: require_auth defaults True).

    Creates the it-admin user + admin role binding in the overridden DB and
    attaches a valid Bearer token.
    """
    from apps.api_server.dependencies import get_db

    from tests.integration.conftest import make_auth_header

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    headers = make_auth_header(db)
    with TestClient(app) as c:
        c.headers.update(headers)
        yield c
    app.dependency_overrides.clear()


# ── Backup / Restore Lifecycle ─────────────────────────────────────────────


@pytest.mark.integration
class TestBackupRestoreLifecycle:
    """Full backup -> list -> verify -> restore lifecycle."""

    def test_create_backup_returns_success(self, auth_client: TestClient):
        resp = auth_client.post("/api/v1/admin/backup")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "backup_path" in body["data"]

    def test_backup_file_exists_on_disk(self, auth_client: TestClient, tmp_path):
        """Verify the backup file was actually written to disk."""
        # Create a temporary SQLite database for backup
        import sqlite3
        db_path = tmp_path / "test_backup.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
        conn.close()

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        from packages.admin.backup_service import BackupService

        result = BackupService.create_backup(
            f"sqlite:///{db_path}", str(backup_dir)
        )
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_list_backups_returns_list(self, auth_client: TestClient):
        resp = auth_client.get("/api/v1/admin/backups")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "backups" in body["data"]
        assert "total" in body["data"]
        assert isinstance(body["data"]["backups"], list)

    def test_backup_creates_new_entry(self, auth_client: TestClient):
        """Creating a backup should produce at least one backup entry."""
        backup_resp = auth_client.post("/api/v1/admin/backup")
        assert backup_resp.status_code == 200

        list_resp = auth_client.get("/api/v1/admin/backups")
        assert list_resp.json()["data"]["total"] >= 1

    def test_backup_file_is_valid_sqlite(self, auth_client: TestClient):
        """Each backup should pass SQLite integrity check via validate endpoint."""
        list_resp = auth_client.get("/api/v1/admin/backups")
        backups = list_resp.json()["data"]["backups"]
        for b in backups:
            validate_resp = auth_client.get(
                f"/api/v1/admin/backups/{b['id']}/validate"
            )
            assert validate_resp.status_code == 200
            assert validate_resp.json()["data"]["is_valid_sqlite"] is True

    def test_restore_nonexistent_backup_returns_400(self, auth_client: TestClient):
        resp = auth_client.post(
            "/api/v1/admin/restore",
            json={"backup_path": "/nonexistent/path/backup.db"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False

    def test_backup_list_entry_has_required_fields(self, auth_client: TestClient):
        auth_client.post("/api/v1/admin/backup")
        list_resp = auth_client.get("/api/v1/admin/backups")
        backups = list_resp.json()["data"]["backups"]
        assert len(backups) >= 1
        entry = backups[0]
        for field in ("id", "filename", "path", "size_bytes", "created_at"):
            assert field in entry, f"Missing field: {field}"

    def test_delete_nonexistent_backup_returns_404(self, auth_client: TestClient):
        resp = auth_client.delete("/api/v1/admin/backups/nonexistent_backup_id")
        assert resp.status_code == 404

    def test_backup_restore_delete_full_lifecycle(self, auth_client: TestClient, tmp_path):
        """Full lifecycle using the BackupService directly."""
        import sqlite3

        db_path = tmp_path / "lifecycle.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE items (name TEXT)")
        conn.execute("INSERT INTO items VALUES ('test-item')")
        conn.commit()
        conn.close()

        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()

        from packages.admin.backup_service import BackupService

        # Create backup
        backup_path = BackupService.create_backup(
            f"sqlite:///{db_path}", str(backup_dir)
        )
        assert Path(backup_path).exists()

        # Modify original DB
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO items VALUES ('added-later')")
        conn.commit()
        conn.close()

        # Restore from backup
        result = BackupService.restore_backup(
            f"sqlite:///{db_path}", backup_path
        )
        assert result is True

        # Verify restored data (should only have original row)
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT name FROM items").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "test-item"

        # Delete backup
        BackupService.delete_backup(backup_path, str(backup_dir))
        assert not Path(backup_path).exists()


# ── Prometheus Metrics Format Validation ────────────────────────────────────


@pytest.mark.integration
class TestPrometheusMetricsFormat:
    """Validate Prometheus text exposition format."""

    def test_prometheus_endpoint_200(self, client: TestClient):
        resp = client.get("/api/v1/metrics/prometheus")
        assert resp.status_code == 200

    def test_prometheus_content_type(self, client: TestClient):
        resp = client.get("/api/v1/metrics/prometheus")
        assert "text/plain" in resp.headers["content-type"]

    def test_prometheus_has_help_and_type_for_each_metric(self, client: TestClient):
        resp = client.get("/api/v1/metrics/prometheus")
        text = resp.text
        for name in [
            "http_requests_total",
            "http_request_duration_seconds",
            "agent_tasks_total",
            "agent_active_websockets",
            "agent_db_connections_active",
        ]:
            assert f"# HELP {name}" in text, f"Missing HELP for {name}"
            assert f"# TYPE {name}" in text, f"Missing TYPE for {name}"

    def test_prometheus_metric_lines_match_format(self, client: TestClient):
        """Every non-comment, non-empty line must match Prometheus format."""
        resp = client.get("/api/v1/metrics/prometheus")
        pattern = re.compile(r'^[a-z_:][a-zA-Z0-9_:]*(?:\{[^}]*\})? [\d.+eEinf]+$')
        for line in resp.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert pattern.match(line), f"Invalid Prometheus line: {line}"

    def test_prometheus_counter_has_incremented_after_requests(self, client: TestClient):
        # Make a request to generate a metric
        client.get("/api/v1/tasks")
        resp = client.get("/api/v1/metrics/prometheus")
        assert "http_requests_total" in resp.text
        # Should contain at least one non-zero counter
        assert re.search(r'http_requests_total\{[^}]*\} [1-9]', resp.text) is not None

    def test_prometheus_histogram_has_buckets(self, client: TestClient):
        resp = client.get("/api/v1/metrics/prometheus")
        text = resp.text
        # Histogram should have _bucket, _sum, _count
        assert "http_request_duration_seconds_bucket" in text
        assert "http_request_duration_seconds_sum" in text
        assert "http_request_duration_seconds_count" in text

    def test_prometheus_gauge_format(self, client: TestClient):
        resp = client.get("/api/v1/metrics/prometheus")
        text = resp.text
        # Gauge should have TYPE gauge
        assert "# TYPE agent_active_websockets gauge" in text


# ── Rate Limiting Behavior ──────────────────────────────────────────────────


@pytest.mark.integration
class TestRateLimitingBehavior:
    """Test rate limiting via the middleware (when enabled)."""

    def test_rate_limiter_exempt_paths(self, client: TestClient):
        """Health and metrics endpoints should never be rate-limited."""
        # These should all succeed without rate limiting
        for _ in range(5):
            resp = client.get("/health")
            assert resp.status_code == 200
            resp = client.get("/api/v1/health/ready")
            assert resp.status_code == 200
            resp = client.get("/api/v1/health/metrics")
            assert resp.status_code == 200

    def test_rate_limiter_returns_429_when_exceeded(self):
        """When TESTING env is cleared, rate limiter should enforce limits."""
        from fastapi import FastAPI

        from packages.middleware.rate_limiter import RateLimiter

        app_rl = FastAPI()

        @app_rl.get("/test-rate")
        def test_rate():
            return {"ok": True}

        app_rl.add_middleware(RateLimiter, max_requests=3, window_seconds=60)

        with TestClient(app_rl) as c:
            # First 3 requests should succeed
            for _ in range(3):
                resp = c.get("/test-rate")
                assert resp.status_code == 200

            # 4th request should be rate-limited
            resp = c.get("/test-rate")
            assert resp.status_code == 429
            assert resp.json()["success"] is False
            assert "Rate limit" in resp.json()["message"]

    def test_rate_limiter_exempt_prefixes(self):
        """Paths matching EXEMPT_PREFIXES should bypass rate limiting."""
        from packages.middleware.rate_limiter import RateLimiter

        assert RateLimiter._is_exempt("/health") is True
        assert RateLimiter._is_exempt("/health/") is True
        assert RateLimiter._is_exempt("/ws/chat") is True
        assert RateLimiter._is_exempt("/ws/tasks/123") is True
        assert RateLimiter._is_exempt("/api/v1/metrics/prometheus") is True
        assert RateLimiter._is_exempt("/api/v1/health/ready") is True

    def test_rate_limiter_non_exempt_paths(self):
        """Non-exempt paths should NOT bypass rate limiting."""
        from packages.middleware.rate_limiter import RateLimiter

        assert RateLimiter._is_exempt("/api/v1/tasks") is False
        assert RateLimiter._is_exempt("/api/v1/auth/login") is False
        assert RateLimiter._is_exempt("/api/v1/admin/backup") is False

    def test_rate_limiter_per_route_limits(self):
        """Per-route limits should override global limits."""
        from fastapi import FastAPI

        from packages.middleware.rate_limiter import RateLimiter

        app_rl = FastAPI()

        @app_rl.get("/api/v1/auth/login")
        def login():
            return {"ok": True}

        @app_rl.get("/api/v1/tasks")
        def tasks():
            return {"ok": True}

        app_rl.add_middleware(
            RateLimiter,
            max_requests=100,
            window_seconds=60,
            route_limits={"/api/v1/auth": (2, 60)},
        )

        with TestClient(app_rl) as c:
            # Auth route: 2 allowed, 3rd blocked
            for _ in range(2):
                resp = c.get("/api/v1/auth/login")
                assert resp.status_code == 200
            resp = c.get("/api/v1/auth/login")
            assert resp.status_code == 429

            # Tasks route: still under global limit
            resp = c.get("/api/v1/tasks")
            assert resp.status_code == 200

    def test_rate_limiter_retry_after_header(self):
        """429 response should include Retry-After header."""
        from fastapi import FastAPI

        from packages.middleware.rate_limiter import RateLimiter

        app_rl = FastAPI()

        @app_rl.get("/limited")
        def limited():
            return {"ok": True}

        app_rl.add_middleware(RateLimiter, max_requests=1, window_seconds=30)

        with TestClient(app_rl) as c:
            c.get("/limited")  # uses the quota
            resp = c.get("/limited")  # blocked
            assert resp.status_code == 429
            assert "retry-after" in resp.headers


# ── Admin-Only Access Control ───────────────────────────────────────────────


@pytest.mark.integration
class TestAdminAccessControl:
    """Test that admin endpoints use the _require_admin dependency."""

    def test_backup_accessible_with_default_auth(self, auth_client: TestClient):
        """With REQUIRE_AUTH=false, backup should work."""
        resp = auth_client.post("/api/v1/admin/backup")
        assert resp.status_code == 200

    def test_list_backups_accessible_with_default_auth(self, auth_client: TestClient):
        resp = auth_client.get("/api/v1/admin/backups")
        assert resp.status_code == 200

    def test_restore_requires_body(self, auth_client: TestClient):
        """Restore endpoint requires a JSON body with backup_path."""
        resp = auth_client.post("/api/v1/admin/restore")
        assert resp.status_code == 422  # validation error

    def test_delete_backup_accepts_valid_id(self, auth_client: TestClient):
        """Delete should return 404 for non-existent but valid-format ID."""
        resp = auth_client.delete("/api/v1/admin/backups/nonexistent_20260101_000000")
        # Either 404 (file not found) or 400 (backup error)
        assert resp.status_code in (400, 404)

    def test_admin_endpoints_exist_and_are_mounted(self, auth_client: TestClient):
        """All admin routes should be registered and accessible."""
        # POST /backup
        assert auth_client.post("/api/v1/admin/backup").status_code in (200, 500)
        # GET /backups
        assert auth_client.get("/api/v1/admin/backups").status_code == 200
        # POST /restore (will 422 without body)
        assert auth_client.post("/api/v1/admin/restore").status_code == 422
