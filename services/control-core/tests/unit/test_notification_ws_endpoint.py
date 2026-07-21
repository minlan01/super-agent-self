"""Tests for the dedicated /ws/notifications WebSocket endpoint and NotificationWSManager."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.notification.notification_service import (
    Notification,
)
from packages.notification.notification_ws_manager import NotificationWSManager

# ── NotificationWSManager unit tests ────────────────────────────────────


@pytest.mark.unit
class TestNotificationWSManagerConnectDisconnect:
    """Test connect / disconnect lifecycle."""

    def test_connect_registers_websocket(self):
        """connect() must add the websocket under the correct user_id."""
        mgr = NotificationWSManager()
        mock_ws = AsyncMock()

        asyncio.run(mgr.connect("user-1", mock_ws))

        assert mgr.get_active_count() == 1
        assert "user-1" in mgr._connections

    def test_connect_accepts_websocket(self):
        """connect() must call websocket.accept()."""
        mgr = NotificationWSManager()
        mock_ws = AsyncMock()

        asyncio.run(mgr.connect("user-1", mock_ws))

        mock_ws.accept.assert_called_once()

    def test_connect_multiple_sockets_same_user(self):
        """Multiple connections for the same user should all be tracked."""
        mgr = NotificationWSManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        asyncio.run(mgr.connect("user-1", ws1))
        asyncio.run(mgr.connect("user-1", ws2))

        assert mgr.get_active_count() == 2
        assert mgr.active_users == 1

    def test_connect_multiple_users(self):
        """Connections for different users are tracked separately."""
        mgr = NotificationWSManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        asyncio.run(mgr.connect("alice", ws1))
        asyncio.run(mgr.connect("bob", ws2))

        assert mgr.get_active_count() == 2
        assert mgr.active_users == 2

    def test_disconnect_removes_websocket(self):
        """disconnect() must remove the specific websocket."""
        mgr = NotificationWSManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        asyncio.run(mgr.connect("user-1", ws1))
        asyncio.run(mgr.connect("user-1", ws2))
        asyncio.run(mgr.disconnect("user-1", ws1))

        assert mgr.get_active_count() == 1

    def test_disconnect_cleans_up_empty_user(self):
        """When the last connection is removed, the user key is deleted."""
        mgr = NotificationWSManager()
        ws = AsyncMock()

        asyncio.run(mgr.connect("user-1", ws))
        asyncio.run(mgr.disconnect("user-1", ws))

        assert mgr.get_active_count() == 0
        assert "user-1" not in mgr._connections

    def test_disconnect_nonexistent_user_is_noop(self):
        """Disconnecting a user with no connections should not raise."""
        mgr = NotificationWSManager()
        ws = AsyncMock()

        asyncio.run(mgr.disconnect("ghost", ws))

        assert mgr.get_active_count() == 0


@pytest.mark.unit
class TestNotificationWSManagerSend:
    """Test send_to_user / broadcast."""

    def test_send_to_user_delivers_message(self):
        """send_to_user() must send JSON to all sockets of that user."""
        mgr = NotificationWSManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        asyncio.run(mgr.connect("alice", ws1))
        asyncio.run(mgr.connect("alice", ws2))

        payload = {"type": "notification", "data": {"id": "n-1"}}
        asyncio.run(mgr.send_to_user("alice", payload))

        expected = json.dumps(payload, ensure_ascii=False)
        ws1.send_text.assert_called_once_with(expected)
        ws2.send_text.assert_called_once_with(expected)

    def test_send_to_user_prunes_dead_sockets(self):
        """Sockets that raise on send must be disconnected."""
        mgr = NotificationWSManager()
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = RuntimeError("closed")

        asyncio.run(mgr.connect("alice", ws_alive))
        asyncio.run(mgr.connect("alice", ws_dead))

        asyncio.run(mgr.send_to_user("alice", {"type": "pong"}))

        assert mgr.get_active_count() == 1

    def test_send_to_user_no_connections_is_noop(self):
        """Sending to a user with no connections should not raise."""
        mgr = NotificationWSManager()
        asyncio.run(mgr.send_to_user("nobody", {"type": "pong"}))

    def test_broadcast_delivers_to_all_users(self):
        """broadcast() must send to every connected user."""
        mgr = NotificationWSManager()
        ws_alice = AsyncMock()
        ws_bob = AsyncMock()

        asyncio.run(mgr.connect("alice", ws_alice))
        asyncio.run(mgr.connect("bob", ws_bob))

        payload = {"type": "notification", "data": {"id": "n-bcast"}}
        asyncio.run(mgr.broadcast(payload))

        expected = json.dumps(payload, ensure_ascii=False)
        ws_alice.send_text.assert_called_once_with(expected)
        ws_bob.send_text.assert_called_once_with(expected)

    def test_broadcast_prunes_dead_sockets(self):
        """broadcast() must prune any socket that fails to send."""
        mgr = NotificationWSManager()
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = RuntimeError("closed")

        asyncio.run(mgr.connect("alice", ws_alive))
        asyncio.run(mgr.connect("bob", ws_dead))

        asyncio.run(mgr.broadcast({"type": "pong"}))

        assert mgr.get_active_count() == 1

    def test_get_active_count_empty(self):
        """Active count is 0 when no connections exist."""
        mgr = NotificationWSManager()
        assert mgr.get_active_count() == 0


# ── /ws/notifications endpoint tests ────────────────────────────────────


@pytest.mark.unit
class TestNotificationWSEndpoint:
    """Integration-style tests for the /ws/notifications FastAPI endpoint."""

    @pytest.fixture(autouse=True)
    def _disable_auth(self):
        from packages.config import get_settings
        settings = get_settings()
        prev = settings.security.require_auth
        settings.security.require_auth = False
        yield
        settings.security.require_auth = prev

    @pytest.fixture()
    def _reset_manager(self):
        """Reset the module-level singleton between tests."""
        from packages.notification.notification_ws_manager import notification_ws_manager
        notification_ws_manager._connections.clear()
        yield
        notification_ws_manager._connections.clear()

    def test_rejects_invalid_token(self, _reset_manager):
        """Connection with an invalid token must be closed with code 4001."""
        from fastapi.testclient import TestClient

        from apps.api_server.main import app

        with patch("packages.auth.auth_service.verify_token", return_value=None):
            client = TestClient(app)
            with pytest.raises(Exception):
                # TestClient will raise because the server closes the WS
                with client.websocket_connect("/ws/notifications?token=bad"):
                    pass

    def test_accepts_connection_without_token(self, _reset_manager):
        """Without a token the connection is accepted as 'default' user."""
        from fastapi.testclient import TestClient

        from apps.api_server.main import app

        # Reset notification_service state for default user
        from packages.notification.notification_service import notification_service
        notification_service.clear("default")

        client = TestClient(app)
        with client.websocket_connect("/ws/notifications") as ws:
            # Should receive initial unread_count message
            data = json.loads(ws.receive_text())
            assert data["type"] == "unread_count"
            assert data["count"] == 0

    def test_accepts_valid_token(self, _reset_manager):
        """A valid token should allow connection and send initial unread count."""
        from fastapi.testclient import TestClient

        from apps.api_server.main import app

        mock_payload = {"sub": "alice"}
        with patch("packages.auth.auth_service.verify_token", return_value=mock_payload), \
             patch("packages.db.repositories.auth_repo.AuthRepository.get_by_id", return_value=MagicMock(is_active=True, role=MagicMock(value="admin"))), \
             patch("packages.auth.rbac.get_rbac_service", return_value=MagicMock(rbac_enabled=False)):
            from packages.notification.notification_service import notification_service
            notification_service.clear("alice")

            client = TestClient(app)
            with client.websocket_connect("/ws/notifications?token=valid.jwt") as ws:
                data = json.loads(ws.receive_text())
                assert data["type"] == "unread_count"
                assert data["count"] == 0

    def test_ping_pong_text(self, _reset_manager):
        """Sending plain 'ping' must receive {'type': 'pong'}."""
        from fastapi.testclient import TestClient

        from apps.api_server.main import app
        from packages.notification.notification_service import notification_service
        notification_service.clear("default")

        client = TestClient(app)
        with client.websocket_connect("/ws/notifications") as ws:
            # Consume initial unread_count
            ws.receive_text()
            # Send ping
            ws.send_text("ping")
            data = json.loads(ws.receive_text())
            assert data["type"] == "pong"

    def test_ping_pong_json(self, _reset_manager):
        """Sending JSON ping must receive {'type': 'pong'}."""
        from fastapi.testclient import TestClient

        from apps.api_server.main import app
        from packages.notification.notification_service import notification_service
        notification_service.clear("default")

        client = TestClient(app)
        with client.websocket_connect("/ws/notifications") as ws:
            # Consume initial unread_count
            ws.receive_text()
            # Send JSON ping
            ws.send_text(json.dumps({"type": "ping"}))
            data = json.loads(ws.receive_text())
            assert data["type"] == "pong"

    def test_initial_unread_count_with_existing_notifications(self, _reset_manager):
        """On connect, server sends the correct unread count for the user."""
        from fastapi.testclient import TestClient

        from apps.api_server.main import app
        from packages.notification.notification_service import notification_service
        notification_service.clear("alice")
        notification_service.create("alice", "info", "Test", "Message")
        notification_service.create("alice", "info", "Test2", "Message2")

        mock_payload = {"sub": "alice"}
        with patch("packages.auth.auth_service.verify_token", return_value=mock_payload), \
             patch("packages.db.repositories.auth_repo.AuthRepository.get_by_id", return_value=MagicMock(is_active=True, role=MagicMock(value="admin"))), \
             patch("packages.auth.rbac.get_rbac_service", return_value=MagicMock(rbac_enabled=False)):
            client = TestClient(app)
            with client.websocket_connect("/ws/notifications?token=valid.jwt") as ws:
                data = json.loads(ws.receive_text())
                assert data["type"] == "unread_count"
                assert data["count"] == 2

        notification_service.clear("alice")


# ── Broadcaster dual-push tests ─────────────────────────────────────────


@pytest.mark.unit
class TestBroadcasterDualPush:
    """Verify NotificationBroadcaster pushes to both chat_manager and notification_ws_manager."""

    def test_broadcast_pushes_to_both_managers(self):
        """broadcast_notification must send to both chat and notification WS managers."""
        from packages.notification.ws_broadcaster import NotificationBroadcaster

        broadcaster = NotificationBroadcaster()
        notification = Notification(
            id="n-dual", type="info", title="T", message="M",
            data=None, created_at="2026-01-01T00:00:00+00:00", read=False,
        )

        mock_chat = MagicMock()
        mock_chat.send_to_user = AsyncMock()

        mock_notif = MagicMock()
        mock_notif.send_to_user = AsyncMock()

        with patch("apps.api_server.routes.ws.chat_manager", mock_chat), \
             patch("packages.notification.notification_ws_manager.notification_ws_manager", mock_notif):
            asyncio.run(broadcaster.broadcast_notification("user-1", notification))

        payload = {"type": "notification", "data": notification.to_dict()}

        mock_chat.send_to_user.assert_called_once_with("user-1", payload)
        mock_notif.send_to_user.assert_called_once_with("user-1", payload)

    def test_broadcast_survives_chat_manager_failure(self):
        """If chat_manager fails, notification_ws_manager must still be called."""
        from packages.notification.ws_broadcaster import NotificationBroadcaster

        broadcaster = NotificationBroadcaster()
        notification = Notification(
            id="n-resilient", type="info", title="T", message="M",
            data=None, created_at="2026-01-01T00:00:00+00:00", read=False,
        )

        mock_chat = MagicMock()
        mock_chat.send_to_user = AsyncMock(side_effect=RuntimeError("boom"))

        mock_notif = MagicMock()
        mock_notif.send_to_user = AsyncMock()

        with patch("apps.api_server.routes.ws.chat_manager", mock_chat), \
             patch("packages.notification.notification_ws_manager.notification_ws_manager", mock_notif):
            asyncio.run(broadcaster.broadcast_notification("user-1", notification))

        # notification_ws_manager should still have been called
        mock_notif.send_to_user.assert_called_once()

    def test_broadcast_survives_notif_manager_failure(self):
        """If notification_ws_manager fails, chat_manager should still have been called."""
        from packages.notification.ws_broadcaster import NotificationBroadcaster

        broadcaster = NotificationBroadcaster()
        notification = Notification(
            id="n-resilient2", type="info", title="T", message="M",
            data=None, created_at="2026-01-01T00:00:00+00:00", read=False,
        )

        mock_chat = MagicMock()
        mock_chat.send_to_user = AsyncMock()

        mock_notif = MagicMock()
        mock_notif.send_to_user = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("apps.api_server.routes.ws.chat_manager", mock_chat), \
             patch("packages.notification.notification_ws_manager.notification_ws_manager", mock_notif):
            asyncio.run(broadcaster.broadcast_notification("user-1", notification))

        # chat_manager should have been called
        mock_chat.send_to_user.assert_called_once()
