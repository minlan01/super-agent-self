"""Integration tests for webhook and messaging API endpoints."""

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.auth.auth_service import create_access_token
from packages.config import clear_settings_cache
from packages.db.models import Base
from packages.db.repositories.auth_repo import AuthRepository
from packages.db.repositories.rbac_repo import RBACRepository


@pytest.fixture
def app_and_client():
    """Create a test app with auth enabled, RBAC seeded, and in-memory DB."""
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

    RBACRepository.seed_default_roles_and_permissions(db)
    db.commit()

    from apps.api_server.dependencies import get_db
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
def admin_headers(app_and_client):
    """Create an admin user and return auth headers."""
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="admin", password="admin123")
    user.role = "admin"  # type: ignore
    db.commit()

    admin_role = RBACRepository.get_role_by_name(db, "admin")
    if admin_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=admin_role.id)
        db.commit()

    token = create_access_token({"sub": user.id, "username": user.username})
    return {"Authorization": f"Bearer {token}"}


# ── POST /api/v1/webhooks/{platform} ──────────────────────────────────────


@pytest.mark.integration
def test_webhook_receive_unconfigured_platform_returns_400(app_and_client):
    """Webhook to a platform with no configured provider returns 400."""
    client, db = app_and_client
    resp = client.post(
        "/api/v1/webhooks/feishu",
        json={"text": "hello"},
    )
    # No feishu provider configured -> handle_webhook returns None -> 400
    assert resp.status_code == 400


@pytest.mark.integration
def test_webhook_receive_unknown_platform_returns_400(app_and_client):
    """Webhook to a platform with no configured provider returns 400."""
    client, db = app_and_client
    resp = client.post(
        "/api/v1/webhooks/nonexistent_platform",
        content=b'{"hello": "world"}',
        headers={"Content-Type": "application/json"},
    )
    # No provider configured -> handle_webhook returns None -> 400
    assert resp.status_code == 400


# ── POST /api/v1/messaging/send ───────────────────────────────────────────


@pytest.mark.integration
def test_send_message_requires_auth(app_and_client):
    """Sending a message without auth returns 401."""
    client, db = app_and_client
    resp = client.post(
        "/api/v1/messaging/send",
        json={
            "platform": "telegram",
            "channel_id": "ch1",
            "text": "Hello",
        },
    )
    assert resp.status_code == 401


@pytest.mark.integration
@patch("apps.api_server.routes.webhooks.get_messaging_router")
def test_send_message_success(mock_get_router, app_and_client, admin_headers):
    """Sending a message with auth returns delivery status."""
    from packages.messaging_gateway.base import MessageDeliveryStatus

    mock_router = AsyncMock()
    mock_router.send.return_value = MessageDeliveryStatus(
        message_id="msg-001",
        platform="telegram",
        status="sent",
    )
    mock_get_router.return_value = mock_router

    client, db = app_and_client
    resp = client.post(
        "/api/v1/messaging/send",
        json={
            "platform": "telegram",
            "channel_id": "ch1",
            "text": "Hello world",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message_id"] == "msg-001"
    assert body["status"] == "sent"


# ── GET /api/v1/messaging/channels ────────────────────────────────────────


@pytest.mark.integration
def test_list_channels_requires_auth(app_and_client):
    """Listing channels without auth returns 401."""
    client, db = app_and_client
    resp = client.get("/api/v1/messaging/channels")
    assert resp.status_code == 401


@pytest.mark.integration
def test_list_channels_empty(app_and_client, admin_headers):
    """Listing channels with no channels returns empty list."""
    client, db = app_and_client
    resp = client.get("/api/v1/messaging/channels", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["channels"] == []


@pytest.mark.integration
def test_list_channels_returns_created(app_and_client, admin_headers):
    """Listing channels returns previously created channels."""
    client, db = app_and_client
    # Create a channel first
    client.post(
        "/api/v1/messaging/channels",
        json={
            "platform": "telegram",
            "channel_id": "tg-123",
            "channel_name": "Test Channel",
        },
        headers=admin_headers,
    )

    resp = client.get("/api/v1/messaging/channels", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["channels"]) == 1
    ch = body["channels"][0]
    assert ch["platform"] == "telegram"
    assert ch["channel_id"] == "tg-123"
    assert ch["channel_name"] == "Test Channel"
    assert ch["is_active"] is True


@pytest.mark.integration
def test_list_channels_filter_by_platform(app_and_client, admin_headers):
    """Listing channels with platform filter returns only matching channels."""
    client, db = app_and_client
    # Create channels on two platforms
    client.post(
        "/api/v1/messaging/channels",
        json={"platform": "telegram", "channel_id": "tg-1"},
        headers=admin_headers,
    )
    client.post(
        "/api/v1/messaging/channels",
        json={"platform": "discord", "channel_id": "dc-1"},
        headers=admin_headers,
    )

    resp = client.get("/api/v1/messaging/channels?platform=telegram", headers=admin_headers)
    assert resp.status_code == 200
    channels = resp.json()["channels"]
    assert len(channels) == 1
    assert channels[0]["platform"] == "telegram"


# ── POST /api/v1/messaging/channels ───────────────────────────────────────


@pytest.mark.integration
def test_create_channel_requires_auth(app_and_client):
    """Creating a channel without auth returns 401."""
    client, db = app_and_client
    resp = client.post(
        "/api/v1/messaging/channels",
        json={"platform": "telegram", "channel_id": "ch1"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
def test_create_channel_success(app_and_client, admin_headers):
    """Creating a channel returns channel details."""
    client, db = app_and_client
    resp = client.post(
        "/api/v1/messaging/channels",
        json={
            "platform": "discord",
            "channel_id": "dc-999",
            "channel_name": "My Discord",
            "config": {"webhook_url": "https://example.com/hook"},
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["channel"]["platform"] == "discord"
    assert body["channel"]["channel_id"] == "dc-999"
    assert "id" in body["channel"]


# ── GET /api/v1/messaging/history/{channel_id} ────────────────────────────


@pytest.mark.integration
def test_message_history_requires_auth(app_and_client):
    """Fetching message history without auth returns 401."""
    client, db = app_and_client
    resp = client.get("/api/v1/messaging/history/ch-1")
    assert resp.status_code == 401


@pytest.mark.integration
def test_message_history_empty(app_and_client, admin_headers):
    """Message history for a channel with no messages returns empty list."""
    client, db = app_and_client
    # Create a channel first to get a valid ID
    create_resp = client.post(
        "/api/v1/messaging/channels",
        json={"platform": "slack", "channel_id": "sl-1"},
        headers=admin_headers,
    )
    channel_id = create_resp.json()["channel"]["id"]

    resp = client.get(f"/api/v1/messaging/history/{channel_id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["messages"] == []


@pytest.mark.integration
def test_message_history_returns_logged_messages(app_and_client, admin_headers):
    """Message history returns messages previously logged to the channel."""
    client, db = app_and_client
    # Create a channel
    create_resp = client.post(
        "/api/v1/messaging/channels",
        json={"platform": "telegram", "channel_id": "tg-hist"},
        headers=admin_headers,
    )
    channel_id = create_resp.json()["channel"]["id"]

    # Directly insert message logs via the repository
    from packages.db.repositories.messaging_repo import MessagingRepository

    fixed_now = datetime(2026, 8, 16, 2, 30, tzinfo=UTC)
    with (
        patch("packages.db.models.datetime") as clock,
        patch("packages.db.models._last_model_timestamp", None),
    ):
        clock.now.return_value = fixed_now
        inbound = MessagingRepository.log_message(
            db,
            channel_id=channel_id,
            direction="inbound",
            platform="telegram",
            sender_id="user-1",
            content="Hello from Telegram",
            status="received",
        )
        outbound = MessagingRepository.log_message(
            db,
            channel_id=channel_id,
            direction="outbound",
            platform="telegram",
            content="Reply from agent",
            status="sent",
        )
    assert outbound.created_at > inbound.created_at
    db.commit()

    resp = client.get(f"/api/v1/messaging/history/{channel_id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["messages"]) == 2
    # Most recent first (desc order)
    assert body["messages"][0]["direction"] == "outbound"
    assert body["messages"][0]["content"] == "Reply from agent"
    assert body["messages"][1]["direction"] == "inbound"
    assert body["messages"][1]["content"] == "Hello from Telegram"


@pytest.mark.integration
def test_message_history_pagination(app_and_client, admin_headers):
    """Message history respects limit and offset parameters."""
    client, db = app_and_client
    create_resp = client.post(
        "/api/v1/messaging/channels",
        json={"platform": "slack", "channel_id": "sl-page"},
        headers=admin_headers,
    )
    channel_id = create_resp.json()["channel"]["id"]

    from packages.db.repositories.messaging_repo import MessagingRepository

    for i in range(5):
        MessagingRepository.log_message(
            db,
            channel_id=channel_id,
            direction="inbound",
            platform="slack",
            content=f"Message {i}",
            status="received",
        )
    db.commit()

    # Get first 2
    resp = client.get(
        f"/api/v1/messaging/history/{channel_id}?limit=2&offset=0",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()["messages"]) == 2

    # Get next page
    resp = client.get(
        f"/api/v1/messaging/history/{channel_id}?limit=2&offset=2",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()["messages"]) == 2
