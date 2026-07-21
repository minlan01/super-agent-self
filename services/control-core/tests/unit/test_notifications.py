"""Unit tests for the notification system — service, broadcaster, and API routes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from packages.notification.notification_service import (
    Notification,
    NotificationService,
)

# ── NotificationService unit tests ─────────────────────────────────────────


@pytest.mark.unit
class TestNotificationServiceCreate:
    def test_create_returns_notification(self):
        svc = NotificationService()
        n = svc.create("user-1", "info", "Hello", "World")
        assert isinstance(n, Notification)
        assert n.id
        assert n.type == "info"
        assert n.title == "Hello"
        assert n.message == "World"
        assert n.read is False
        assert n.data is None
        assert n.created_at

    def test_create_with_data(self):
        svc = NotificationService()
        n = svc.create("user-1", "task_completed", "Done", "Task done", data={"task_id": "t-1"})
        assert n.data == {"task_id": "t-1"}

    def test_create_stores_notification(self):
        svc = NotificationService()
        svc.create("user-1", "info", "T", "M")
        all_n = svc.get_all("user-1")
        assert len(all_n) == 1
        assert all_n[0].title == "T"

    def test_create_multiple_users_isolated(self):
        svc = NotificationService()
        svc.create("user-1", "info", "U1", "M")
        svc.create("user-2", "info", "U2", "M")
        assert len(svc.get_all("user-1")) == 1
        assert len(svc.get_all("user-2")) == 1
        assert svc.get_all("user-1")[0].title == "U1"

    def test_create_newest_first(self):
        svc = NotificationService()
        svc.create("user-1", "info", "First", "M")
        svc.create("user-1", "info", "Second", "M")
        all_n = svc.get_all("user-1")
        assert all_n[0].title == "Second"
        assert all_n[1].title == "First"


@pytest.mark.unit
class TestNotificationServiceRingBuffer:
    def test_ring_buffer_drops_oldest_at_limit(self):
        svc = NotificationService(max_per_user=5)
        for i in range(7):
            svc.create("user-1", "info", f"N{i}", "M")
        all_n = svc.get_all("user-1", limit=100)
        assert len(all_n) == 5
        # Newest is N6, oldest retained is N2 (N0, N1 dropped)
        assert all_n[0].title == "N6"
        assert all_n[-1].title == "N2"

    def test_default_max_is_100(self):
        svc = NotificationService()
        assert svc._max_per_user == 100

    def test_ring_buffer_per_user_independent(self):
        svc = NotificationService(max_per_user=3)
        for i in range(5):
            svc.create("user-1", "info", f"U1-{i}", "M")
        svc.create("user-2", "info", "Only", "M")
        assert len(svc.get_all("user-1")) == 3
        assert len(svc.get_all("user-2")) == 1


@pytest.mark.unit
class TestNotificationServiceGetUnread:
    def test_get_unread_initially_all(self):
        svc = NotificationService()
        svc.create("user-1", "info", "A", "M")
        svc.create("user-1", "info", "B", "M")
        unread = svc.get_unread("user-1")
        assert len(unread) == 2

    def test_get_unread_after_mark_read(self):
        svc = NotificationService()
        n = svc.create("user-1", "info", "A", "M")
        svc.mark_read("user-1", n.id)
        unread = svc.get_unread("user-1")
        assert len(unread) == 0

    def test_get_unread_count(self):
        svc = NotificationService()
        svc.create("user-1", "info", "A", "M")
        svc.create("user-1", "info", "B", "M")
        svc.create("user-1", "info", "C", "M")
        assert svc.get_unread_count("user-1") == 3

    def test_get_unread_empty_user(self):
        svc = NotificationService()
        assert svc.get_unread("nonexistent") == []
        assert svc.get_unread_count("nonexistent") == 0


@pytest.mark.unit
class TestNotificationServiceGetAll:
    def test_get_all_default_limit(self):
        svc = NotificationService()
        for i in range(60):
            svc.create("user-1", "info", f"N{i}", "M")
        all_n = svc.get_all("user-1")
        assert len(all_n) == 50  # default limit

    def test_get_all_custom_limit(self):
        svc = NotificationService()
        for i in range(10):
            svc.create("user-1", "info", f"N{i}", "M")
        all_n = svc.get_all("user-1", limit=5)
        assert len(all_n) == 5


@pytest.mark.unit
class TestNotificationServiceMarkRead:
    def test_mark_read_found(self):
        svc = NotificationService()
        n = svc.create("user-1", "info", "A", "M")
        assert svc.mark_read("user-1", n.id) is True
        assert n.read is True

    def test_mark_read_not_found(self):
        svc = NotificationService()
        assert svc.mark_read("user-1", "nonexistent-id") is False

    def test_mark_read_wrong_user(self):
        svc = NotificationService()
        n = svc.create("user-1", "info", "A", "M")
        assert svc.mark_read("user-2", n.id) is False


@pytest.mark.unit
class TestNotificationServiceMarkAllRead:
    def test_mark_all_read(self):
        svc = NotificationService()
        svc.create("user-1", "info", "A", "M")
        svc.create("user-1", "info", "B", "M")
        count = svc.mark_all_read("user-1")
        assert count == 2
        assert svc.get_unread_count("user-1") == 0

    def test_mark_all_read_already_read(self):
        svc = NotificationService()
        n = svc.create("user-1", "info", "A", "M")
        svc.mark_read("user-1", n.id)
        count = svc.mark_all_read("user-1")
        assert count == 0

    def test_mark_all_read_empty(self):
        svc = NotificationService()
        count = svc.mark_all_read("nonexistent")
        assert count == 0


@pytest.mark.unit
class TestNotificationServiceClear:
    def test_clear(self):
        svc = NotificationService()
        svc.create("user-1", "info", "A", "M")
        svc.create("user-1", "info", "B", "M")
        count = svc.clear("user-1")
        assert count == 2
        assert svc.get_all("user-1") == []

    def test_clear_empty(self):
        svc = NotificationService()
        count = svc.clear("nonexistent")
        assert count == 0

    def test_clear_does_not_affect_other_users(self):
        svc = NotificationService()
        svc.create("user-1", "info", "A", "M")
        svc.create("user-2", "info", "B", "M")
        svc.clear("user-1")
        assert len(svc.get_all("user-2")) == 1


@pytest.mark.unit
class TestNotificationToDict:
    def test_to_dict_keys(self):
        n = Notification(
            id="test-id",
            type="info",
            title="T",
            message="M",
            data=None,
            created_at="2026-01-01T00:00:00+00:00",
            read=False,
        )
        d = n.to_dict()
        assert set(d.keys()) == {"id", "type", "title", "message", "data", "created_at", "read"}
        assert d["id"] == "test-id"
        assert d["read"] is False


# ── NotificationBroadcaster tests ──────────────────────────────────────────


@pytest.mark.unit
class TestNotificationBroadcaster:
    def test_broadcast_notification_calls_send_to_user(self):
        from packages.notification.ws_broadcaster import NotificationBroadcaster

        broadcaster = NotificationBroadcaster()
        notification = Notification(
            id="n-1", type="info", title="T", message="M",
            data=None, created_at="2026-01-01T00:00:00+00:00", read=False,
        )

        mock_manager = MagicMock()
        mock_manager.send_to_user = AsyncMock()

        with patch("apps.api_server.routes.ws.chat_manager", mock_manager):
            asyncio.run(broadcaster.broadcast_notification("user-1", notification))

        mock_manager.send_to_user.assert_called_once()
        call_args = mock_manager.send_to_user.call_args
        assert call_args[0][0] == "user-1"
        payload = call_args[0][1]
        assert payload["type"] == "notification"
        assert payload["data"]["id"] == "n-1"

    def test_broadcast_notification_handles_exception(self):
        from packages.notification.ws_broadcaster import NotificationBroadcaster

        broadcaster = NotificationBroadcaster()
        notification = Notification(
            id="n-1", type="info", title="T", message="M",
            data=None, created_at="2026-01-01T00:00:00+00:00", read=False,
        )

        mock_manager = MagicMock()
        mock_manager.send_to_user = AsyncMock(side_effect=Exception("WS error"))

        # Should not raise
        with patch("apps.api_server.routes.ws.chat_manager", mock_manager):
            asyncio.run(broadcaster.broadcast_notification("user-1", notification))


# ── Notification API route tests ───────────────────────────────────────────


@pytest.fixture
def test_svc():
    """Fresh NotificationService per test to avoid state leakage."""
    return NotificationService()


@pytest.fixture
def client(test_svc):
    """FastAPI TestClient with the notification service patched and auth disabled."""
    import os

    prev_require_auth = os.environ.get("REQUIRE_AUTH")
    os.environ["REQUIRE_AUTH"] = "0"

    from packages.config import get_settings
    settings = get_settings()
    prev_require = settings.security.require_auth
    settings.security.require_auth = False

    with patch(
        "apps.api_server.routes.notifications.notification_service",
        test_svc,
    ):
        from apps.api_server.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    settings.security.require_auth = prev_require
    if prev_require_auth is not None:
        os.environ["REQUIRE_AUTH"] = prev_require_auth
    else:
        os.environ.pop("REQUIRE_AUTH", None)


@pytest.mark.unit
class TestNotificationAPIGetList:
    def test_get_notifications_empty(self, client, test_svc):
        resp = client.get("/api/v1/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"] == []
        assert data["count"] == 0
        assert data["unread_count"] == 0

    def test_get_notifications_with_data(self, client, test_svc):
        test_svc.create("default-admin", "info", "Title1", "Msg1")
        test_svc.create("default-admin", "task_completed", "Title2", "Msg2")
        resp = client.get("/api/v1/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["unread_count"] == 2
        assert data["data"][0]["title"] == "Title2"  # newest first


@pytest.mark.unit
class TestNotificationAPIGetUnread:
    def test_get_unread_count(self, client, test_svc):
        test_svc.create("default-admin", "info", "A", "M")
        test_svc.create("default-admin", "info", "B", "M")
        resp = client.get("/api/v1/notifications/unread")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_get_unread_count_zero(self, client, test_svc):
        resp = client.get("/api/v1/notifications/unread")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


@pytest.mark.unit
class TestNotificationAPIMarkRead:
    def test_mark_as_read(self, client, test_svc):
        n = test_svc.create("default-admin", "info", "A", "M")
        resp = client.post(f"/api/v1/notifications/{n.id}/read")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert test_svc.get_unread_count("default-admin") == 0

    def test_mark_as_read_not_found(self, client, test_svc):
        resp = client.post("/api/v1/notifications/nonexistent-id/read")
        assert resp.status_code == 404


@pytest.mark.unit
class TestNotificationAPIMarkAllRead:
    def test_mark_all_as_read(self, client, test_svc):
        test_svc.create("default-admin", "info", "A", "M")
        test_svc.create("default-admin", "info", "B", "M")
        resp = client.post("/api/v1/notifications/read-all")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["marked_count"] == 2


@pytest.mark.unit
class TestNotificationAPIClear:
    def test_clear_notifications(self, client, test_svc):
        test_svc.create("default-admin", "info", "A", "M")
        test_svc.create("default-admin", "info", "B", "M")
        resp = client.delete("/api/v1/notifications")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["cleared_count"] == 2
        assert test_svc.get_all("default-admin") == []

    def test_clear_empty(self, client, test_svc):
        resp = client.delete("/api/v1/notifications")
        assert resp.status_code == 200
        assert resp.json()["cleared_count"] == 0
