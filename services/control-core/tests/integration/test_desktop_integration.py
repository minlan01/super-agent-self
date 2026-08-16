"""Integration tests for Desktop Automation API routes."""

import os
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.db.models import Base
from packages.db.repositories.rbac_repo import RBACRepository
from packages.db.repositories.auth_repo import AuthRepository
from packages.auth.auth_service import create_access_token
from packages.config import clear_settings_cache


@pytest.fixture
def app_and_client():
    """Create a test app with RBAC enabled and REQUIRE_AUTH=true."""
    _prev_require_auth = os.environ.get("REQUIRE_AUTH")
    os.environ["REQUIRE_AUTH"] = "1"
    clear_settings_cache()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)

    # Seed RBAC
    RBACRepository.seed_default_roles_and_permissions(db)
    db.commit()

    from packages.db.session import get_db
    from apps.api_server.main import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    yield client, db

    app.dependency_overrides.clear()
    db.close()
    if _prev_require_auth is not None:
        os.environ["REQUIRE_AUTH"] = _prev_require_auth
    else:
        os.environ.pop("REQUIRE_AUTH", None)


@pytest.fixture
def admin_token(app_and_client):
    """Create an admin user and return a valid auth token."""
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="admin", password="admin123")
    user.role = "admin"
    db.commit()

    # Assign admin role via RBAC
    admin_role = RBACRepository.get_role_by_name(db, "admin")
    if admin_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=admin_role.id)
        db.commit()

    return create_access_token({"sub": user.id, "username": user.username})


class TestDesktopAuth:
    def test_files_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.post("/api/v1/desktop/files", json={"action": "list", "path": "."})
        assert resp.status_code in (401, 403)

    def test_windows_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.post("/api/v1/desktop/windows", json={"action": "list"})
        assert resp.status_code in (401, 403)

    def test_screenshot_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/desktop/screenshot")
        assert resp.status_code in (401, 403)


class TestDesktopFilesAPI:
    def test_list_files(self, app_and_client, admin_token, tmp_path):
        client, _ = app_and_client
        # Create test files
        (tmp_path / "test.txt").write_text("hello")

        with patch("packages.config.get_settings") as mock_gs:
            mock_gs.return_value = type("S", (), {"workspace_root": str(tmp_path)})()
            resp = client.post(
                "/api/v1/desktop/files",
                json={"action": "list", "path": "."},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_path_traversal_blocked(self, app_and_client, admin_token, tmp_path):
        client, _ = app_and_client

        with patch("packages.config.get_settings") as mock_gs:
            mock_gs.return_value = type("S", (), {"workspace_root": str(tmp_path)})()
            resp = client.post(
                "/api/v1/desktop/files",
                json={"action": "read", "path": "../../etc/passwd"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 403


class TestDesktopWindowsAPI:
    @pytest.mark.skipif(
        __import__("sys").platform != "win32",
        reason="window_provider is Windows-only; stub fails closed elsewhere (correct)",
    )
    def test_list_windows(self, app_and_client, admin_token):
        client, _ = app_and_client
        resp = client.post(
            "/api/v1/desktop/windows",
            json={"action": "list"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "windows" in data["data"]

    def test_list_windows_fails_closed_off_windows(self, app_and_client, admin_token):
        """Off Windows the stub provider must NOT return success (P0.2:
        no silent fallback) — the route reports capability unavailability."""
        import sys

        if sys.platform == "win32":
            pytest.skip("fail-closed semantics only observable off Windows")

        client, _ = app_and_client
        resp = client.post(
            "/api/v1/desktop/windows",
            json={"action": "list"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code != 200, (
            "stub window_provider must fail closed, not fabricate a window list"
        )
