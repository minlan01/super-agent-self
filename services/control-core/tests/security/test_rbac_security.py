"""Security tests for RBAC — privilege escalation, bypass, and permission boundary tests."""

import os
import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import Base
from packages.db.repositories.rbac_repo import RBACRepository
from packages.db.repositories.auth_repo import AuthRepository
from packages.auth.auth_service import create_access_token
from packages.config import clear_settings_cache


@pytest.fixture
def secure_app():
    """Create a test app with full security enabled."""
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


def _make_user(db, username, role_name):
    """Helper: create user, assign RBAC role, return (user, token)."""
    user = AuthRepository.create_user(db, username=username, password="pass123")
    db.commit()
    if role_name:
        role = RBACRepository.get_role_by_name(db, role_name)
        if role:
            RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
            db.commit()
    token = create_access_token({"sub": user.id, "username": user.username})
    return user, token


class TestPrivilegeEscalation:
    """Test that users cannot escalate their own privileges."""

    def test_viewer_cannot_assign_admin_role(self, secure_app):
        client, db = secure_app
        viewer, viewer_token = _make_user(db, "viewer1", "viewer")
        target, _ = _make_user(db, "target1", "user")
        admin_role = RBACRepository.get_role_by_name(db, "admin")

        resp = client.post("/api/v1/rbac/users/assign",
            json={"user_id": target.id, "role_ids": [admin_role.id]},
            headers={"Authorization": f"Bearer {viewer_token}"})
        assert resp.status_code == 403

    def test_user_cannot_create_role(self, secure_app):
        client, db = secure_app
        user, token = _make_user(db, "basic1", "user")

        resp = client.post("/api/v1/rbac/roles",
            json={"name": "super_hacker"},
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_user_cannot_delete_role(self, secure_app):
        client, db = secure_app
        user, token = _make_user(db, "basic2", "user")
        viewer_role = RBACRepository.get_role_by_name(db, "viewer")

        resp = client.delete(f"/api/v1/rbac/roles/{viewer_role.id}",
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_user_cannot_modify_own_permissions(self, secure_app):
        client, db = secure_app
        user, token = _make_user(db, "selfmodifier", "user")
        admin_role = RBACRepository.get_role_by_name(db, "admin")

        resp = client.post("/api/v1/rbac/users/assign",
            json={"user_id": user.id, "role_ids": [admin_role.id]},
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403


class TestPermissionBoundaries:
    """Test that users stay within their permission boundaries."""

    def test_viewer_cannot_execute_tasks(self, secure_app):
        client, db = secure_app
        viewer, token = _make_user(db, "v_exec", "viewer")

        resp = client.post("/api/v1/tasks", json={"goal": "hack"},
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_user_cannot_access_admin_routes(self, secure_app):
        client, db = secure_app
        user, token = _make_user(db, "u_admin", "user")

        resp = client.post("/api/v1/admin/backup",
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_user_cannot_manage_marketplace_admin(self, secure_app):
        client, db = secure_app
        user, token = _make_user(db, "u_market", "user")

        # Try to review a promotion (admin action)
        resp = client.post("/api/v1/marketplace/promotions/fake-id/review",
            json={"approved": True, "review_note": "haha"},
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code in (403, 404)

    def test_operator_cannot_manage_roles(self, secure_app):
        client, db = secure_app
        operator, token = _make_user(db, "op1", "operator")

        resp = client.post("/api/v1/rbac/roles",
            json={"name": "new_role"},
            headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403


class TestTokenSecurity:
    """Test token-based access control."""

    def test_invalid_token_rejected(self, secure_app):
        client, db = secure_app
        resp = client.get("/api/v1/tasks", headers={"Authorization": "Bearer invalid-token"})
        assert resp.status_code in (401, 403)

    def test_expired_token_rejected(self, secure_app):
        client, db = secure_app
        # Create a token that expires immediately
        token = create_access_token({"sub": "fake", "username": "fake"}, expires_delta=-1)
        resp = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code in (401, 403)

    def test_tampered_token_rejected(self, secure_app):
        client, db = secure_app
        user, token = _make_user(db, "tamper", "user")
        tampered = token + "x"
        resp = client.get("/api/v1/tasks", headers={"Authorization": f"Bearer {tampered}"})
        assert resp.status_code in (401, 403)

    def test_no_token_rejected(self, secure_app):
        client, db = secure_app
        resp = client.get("/api/v1/tasks")
        assert resp.status_code in (401, 403)


class TestSystemRoleProtection:
    """Test that system roles cannot be deleted."""

    def test_system_role_cannot_be_deleted(self, secure_app):
        client, db = secure_app
        admin, token = _make_user(db, "sysadmin", "admin")
        admin_role = RBACRepository.get_role_by_name(db, "admin")

        resp = client.delete(f"/api/v1/rbac/roles/{admin_role.id}",
            headers={"Authorization": f"Bearer {token}"})
        # Should be 404 (not found or is system role)
        assert resp.status_code in (404, 200)
        # Verify role still exists
        assert RBACRepository.get_role_by_name(db, "admin") is not None
