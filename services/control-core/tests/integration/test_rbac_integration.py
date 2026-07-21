"""Integration tests for RBAC permission guards on API endpoints."""

import os
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

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

    from sqlalchemy.pool import StaticPool
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
            pass  # Don't close the shared session

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
def admin_user_and_token(app_and_client):
    """Create an admin user with admin token."""
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="admin", password="admin123")
    user.role = "admin"  # type: ignore
    db.commit()

    # Assign admin role via RBAC
    admin_role = RBACRepository.get_role_by_name(db, "admin")
    if admin_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=admin_role.id)
        db.commit()

    token = create_access_token({"sub": user.id, "username": user.username})
    return user, token, db


@pytest.fixture
def viewer_user_and_token(app_and_client):
    """Create a viewer user (read-only permissions)."""
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="viewer", password="viewer123")
    db.commit()

    # Assign viewer role
    viewer_role = RBACRepository.get_role_by_name(db, "viewer")
    if viewer_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=viewer_role.id)
        db.commit()

    token = create_access_token({"sub": user.id, "username": user.username})
    return user, token, db


@pytest.fixture
def plain_user_and_token(app_and_client):
    """Create a basic user with default 'user' role."""
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="basicuser", password="user123")
    db.commit()

    default_role = RBACRepository.get_default_role(db)
    if default_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=default_role.id)
        db.commit()

    token = create_access_token({"sub": user.id, "username": user.username})
    return user, token, db


class TestRBACPublicRoutes:
    """Test that public routes don't require authentication."""

    def test_health_no_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_login_no_auth(self, app_and_client):
        client, db = app_and_client
        AuthRepository.create_user(db, username="loginuser", password="pass123")
        db.commit()
        resp = client.post("/api/v1/auth/login", json={"username": "loginuser", "password": "pass123"})
        assert resp.status_code == 200


class TestRBACAdminAccess:
    """Test that admin users can access all endpoints."""

    def test_admin_can_list_tasks(self, admin_user_and_token, app_and_client):
        user, token, _ = admin_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_admin_can_create_task(self, admin_user_and_token, app_and_client):
        user, token, _ = admin_user_and_token
        client, _ = app_and_client
        resp = client.post("/api/v1/tasks", json={"goal": "test"}, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code in (200, 201)

    def test_admin_can_access_rbac(self, admin_user_and_token, app_and_client):
        user, token, _ = admin_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/rbac/roles", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_admin_can_list_users(self, admin_user_and_token, app_and_client):
        user, token, _ = admin_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/rbac/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


class TestRBACViewerAccess:
    """Test that viewer users have read-only access."""

    def test_viewer_can_list_tasks(self, viewer_user_and_token, app_and_client):
        user, token, _ = viewer_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_viewer_can_read_memory(self, viewer_user_and_token, app_and_client):
        user, token, _ = viewer_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/memory", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_viewer_can_read_audit(self, viewer_user_and_token, app_and_client):
        user, token, _ = viewer_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/audit", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_viewer_cannot_create_task(self, viewer_user_and_token, app_and_client):
        user, token, _ = viewer_user_and_token
        client, _ = app_and_client
        resp = client.post("/api/v1/tasks", json={"goal": "should fail"}, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_viewer_cannot_manage_roles(self, viewer_user_and_token, app_and_client):
        user, token, _ = viewer_user_and_token
        client, _ = app_and_client
        resp = client.post("/api/v1/rbac/roles", json={"name": "hacker"}, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403


class TestRBACBasicUser:
    """Test that basic users can create tasks and use chat."""

    def test_user_can_list_tasks(self, plain_user_and_token, app_and_client):
        user, token, _ = plain_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_user_can_create_task(self, plain_user_and_token, app_and_client):
        user, token, _ = plain_user_and_token
        client, _ = app_and_client
        resp = client.post("/api/v1/tasks", json={"goal": "my task"}, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code in (200, 201)

    def test_user_can_read_memory(self, plain_user_and_token, app_and_client):
        user, token, _ = plain_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/memory", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_user_cannot_write_memory(self, plain_user_and_token, app_and_client):
        user, token, _ = plain_user_and_token
        client, _ = app_and_client
        # Try to disable a memory (write operation)
        resp = client.post("/api/v1/memory/fake-id/disable", headers={"Authorization": f"Bearer {token}"})
        # 403 (permission denied) or 404 (not found) are both acceptable
        assert resp.status_code in (403, 404)


class TestRBACNoAuth:
    """Test that unauthenticated requests are rejected."""

    def test_no_auth_tasks(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/tasks")
        # Should be 401 (unauthorized)
        assert resp.status_code in (401, 403)

    def test_no_auth_rbac(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/rbac/roles")
        assert resp.status_code in (401, 403)


class TestRBACManagement:
    """Test RBAC management API endpoints."""

    def test_list_roles(self, admin_user_and_token, app_and_client):
        user, token, _ = admin_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/rbac/roles", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) >= 4  # admin, operator, viewer, user

    def test_list_permissions(self, admin_user_and_token, app_and_client):
        user, token, _ = admin_user_and_token
        client, _ = app_and_client
        resp = client.get("/api/v1/rbac/permissions", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) >= 52

    def test_assign_role_to_user(self, admin_user_and_token, app_and_client):
        user, token, _ = admin_user_and_token
        client, db = app_and_client

        # Create a test user
        test_user = AuthRepository.create_user(db, username="target", password="pass123")
        db.commit()

        viewer_role = RBACRepository.get_role_by_name(db, "viewer")
        resp = client.post("/api/v1/rbac/users/assign",
            json={"user_id": test_user.id, "role_ids": [viewer_role.id]},
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

        # Verify assignment
        roles = RBACRepository.get_user_roles(db, test_user.id)
        assert any(r.name == "viewer" for r in roles)

    def test_revoke_role_from_user(self, admin_user_and_token, app_and_client):
        user, token, _ = admin_user_and_token
        client, db = app_and_client

        test_user = AuthRepository.create_user(db, username="revoke_target", password="pass123")
        db.commit()

        viewer_role = RBACRepository.get_role_by_name(db, "viewer")
        RBACRepository.assign_role_to_user(db, user_id=test_user.id, role_id=viewer_role.id)
        db.commit()

        resp = client.post("/api/v1/rbac/users/revoke",
            json={"user_id": test_user.id, "role_ids": [viewer_role.id]},
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

        roles = RBACRepository.get_user_roles(db, test_user.id)
        assert len(roles) == 0

    def test_get_user_permissions(self, admin_user_and_token, app_and_client):
        user, token, _ = admin_user_and_token
        client, db = app_and_client

        test_user = AuthRepository.create_user(db, username="perm_check", password="pass123")
        db.commit()

        user_role = RBACRepository.get_role_by_name(db, "user")
        RBACRepository.assign_role_to_user(db, user_id=test_user.id, role_id=user_role.id)
        db.commit()

        resp = client.get(f"/api/v1/rbac/users/{test_user.id}/permissions",
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        permissions = body.get("data", body.get("permissions", []))
        assert isinstance(permissions, list)
        assert "tasks:read" in permissions
