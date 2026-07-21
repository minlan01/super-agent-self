"""Integration tests for Personal Edition API endpoints."""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import Base, Memory, MemoryType, Edition
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
def admin_user_and_token(app_and_client):
    """Create an admin user with admin token."""
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="admin", password="admin123")
    user.role = "admin"  # type: ignore
    db.commit()

    admin_role = RBACRepository.get_role_by_name(db, "admin")
    if admin_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=admin_role.id)
        db.commit()

    token = create_access_token({"sub": user.id, "username": user.username})
    return user, token, db


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_reminder(db: Session, title: str = "Test Reminder") -> Memory:
    """Insert an active reminder into the database."""
    memory = Memory(
        user_id="default",
        edition=Edition.PERSONAL,
        memory_type=MemoryType.REMINDER,
        title=title,
        summary=title,
        content={"type": "reminder", "description": "test"},
        importance_score=0.6,
        confidence_score=1.0,
        is_active=True,
    )
    db.add(memory)
    db.flush()
    db.refresh(memory)
    return memory


# ── Reminders ───────────────────────────────────────────────────────────────


class TestCreateReminder:
    @pytest.mark.integration
    def test_create_reminder(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.post(
            "/api/v1/personal/reminders",
            json={"title": "Buy groceries", "description": "Milk and eggs"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Reminder created"
        assert body["data"]["title"] == "Buy groceries"

    @pytest.mark.integration
    def test_create_reminder_with_expiry(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.post(
            "/api/v1/personal/reminders",
            json={
                "title": "Timed reminder",
                "description": "Expires soon",
                "expires_at": "2099-12-31T23:59:00",
            },
            headers=_auth_headers(token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True

    @pytest.mark.integration
    def test_create_reminder_empty_title_rejected(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.post(
            "/api/v1/personal/reminders",
            json={"title": "", "description": "no title"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 422


class TestListReminders:
    @pytest.mark.integration
    def test_list_reminders_empty(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.get(
            "/api/v1/personal/reminders",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    @pytest.mark.integration
    def test_list_reminders_returns_active(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        _seed_reminder(db, "Active Reminder")
        db.commit()

        resp = client.get(
            "/api/v1/personal/reminders",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["title"] == "Active Reminder"


class TestDismissReminder:
    @pytest.mark.integration
    def test_dismiss_reminder(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token
        reminder = _seed_reminder(db, "Dismiss Me")
        db.commit()

        resp = client.post(
            f"/api/v1/personal/reminders/{reminder.id}/dismiss",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Reminder dismissed"

    @pytest.mark.integration
    def test_dismiss_nonexistent_reminder(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.post(
            "/api/v1/personal/reminders/nonexistent-id/dismiss",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404


# ── Daily Context ───────────────────────────────────────────────────────────


class TestDailyContext:
    @pytest.mark.integration
    def test_get_daily_context(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.get(
            "/api/v1/personal/context",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "daily_context" in body["data"]
        assert "reminders" in body["data"]
        assert "preferences_count" in body["data"]
        assert "projects_count" in body["data"]


# ── Preferences ─────────────────────────────────────────────────────────────


class TestPreferences:
    @pytest.mark.integration
    def test_get_preferences_empty(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        resp = client.get(
            "/api/v1/personal/preferences",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    @pytest.mark.integration
    def test_save_and_get_preference(self, app_and_client, admin_user_and_token):
        client, db = app_and_client
        _, token, _ = admin_user_and_token

        # Build a mock that satisfies MemoryResponse.model_validate fields
        from datetime import datetime, timezone
        from packages.db.models import MemoryType as MT, Edition as Ed

        mock_result = MagicMock()
        mock_result.id = "pref-001"
        mock_result.user_id = "default"
        mock_result.edition = Ed.PERSONAL
        mock_result.memory_type = MT.USER_PREFERENCE
        mock_result.title = "preference:theme"
        mock_result.summary = "theme = dark"
        mock_result.content = {"key": "theme", "value": "dark"}
        mock_result.content_hash = None
        mock_result.importance_score = 0.5
        mock_result.confidence_score = 0.5
        mock_result.source_task_id = None
        mock_result.is_active = True
        mock_result.expires_at = None
        mock_result.created_at = datetime.now(timezone.utc)
        mock_result.updated_at = datetime.now(timezone.utc)

        with patch(
            "packages.personal_context.personal_context_service.PersonalContextService.save_preference",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post(
                "/api/v1/personal/preferences",
                json={"key": "theme", "value": "dark"},
                headers=_auth_headers(token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Preference saved"


# ── Editions ────────────────────────────────────────────────────────────────


class TestEditions:
    @pytest.mark.integration
    def test_list_editions(self, app_and_client, admin_user_and_token):
        client, _ = app_and_client
        _, token, _ = admin_user_and_token

        # EditionManager reads from configs/editions/*.yaml which may not
        # exist in test env — patch the factory in the route module.
        mock_mgr = MagicMock()
        mock_mgr.list_editions.return_value = ["personal", "enterprise"]
        mock_mgr.get_name.side_effect = lambda e: e.title()
        mock_mgr.get_description.side_effect = lambda e: f"{e} edition"

        with patch(
            "apps.api_server.routes.personal._get_edition_manager",
            return_value=mock_mgr,
        ):
            resp = client.get(
                "/api/v1/personal/editions",
                headers=_auth_headers(token),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 2
        assert body["data"][0]["edition"] == "personal"


# ── Auth guard ──────────────────────────────────────────────────────────────


class TestPersonalNoAuth:
    @pytest.mark.integration
    def test_reminders_require_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/personal/reminders")
        assert resp.status_code in (401, 403)

    @pytest.mark.integration
    def test_context_requires_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/personal/context")
        assert resp.status_code in (401, 403)

    @pytest.mark.integration
    def test_preferences_require_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/personal/preferences")
        assert resp.status_code in (401, 403)

    @pytest.mark.integration
    def test_editions_require_auth(self, app_and_client):
        client, _ = app_and_client
        resp = client.get("/api/v1/personal/editions")
        assert resp.status_code in (401, 403)
