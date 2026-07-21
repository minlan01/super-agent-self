"""Tests for WebSocket token refresh and token-expiry notification.

Covers all 3 WebSocket endpoints:
  - /ws/tasks/{task_id}
  - /ws/chat
  - /ws/notifications
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketDisconnect

from apps.api_server.routes.ws import (
    _handle_token_refresh,
    _is_token_expired,
)
from packages.config import get_settings, clear_settings_cache


# ── Helper factories ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _disable_auth():
    settings = get_settings()
    prev = settings.security.require_auth
    prev_env = os.environ.get("REQUIRE_AUTH")
    settings.security.require_auth = False
    os.environ.pop("REQUIRE_AUTH", None)
    yield
    settings.security.require_auth = prev
    if prev_env is not None:
        os.environ["REQUIRE_AUTH"] = prev_env


def _make_ws(token: str | None = None, receive_texts: list | None = None):
    """Create an AsyncMock WebSocket with proper query_params mock."""
    ws = AsyncMock()
    ws.query_params = MagicMock()
    ws.query_params.get.return_value = token
    if receive_texts is not None:
        ws.receive_text.side_effect = receive_texts
    return ws


def _sent_messages(ws: AsyncMock) -> list[dict]:
    """Extract all JSON messages sent through the mock websocket."""
    return [json.loads(call[0][0]) for call in ws.send_text.call_args_list]


# ── Unit tests for _handle_token_refresh helper ───────────────────────────


class TestHandleTokenRefreshHelper:
    """Tests for the shared _handle_token_refresh helper."""

    @patch("packages.auth.auth_service.verify_token", return_value={"sub": "user-1"})
    def test_valid_token_returns_refresh_ok(self, mock_verify):
        ws = AsyncMock()
        envelope = {"type": "refresh", "token": "good.jwt"}

        async def _test():
            result = await _handle_token_refresh(ws, envelope)
            assert result is True

        asyncio.run(_test())
        sent = _sent_messages(ws)
        assert len(sent) == 1
        assert sent[0]["type"] == "refresh_ok"

    @patch("packages.auth.auth_service.verify_token", return_value=None)
    def test_invalid_token_returns_refresh_error(self, mock_verify):
        ws = AsyncMock()
        envelope = {"type": "refresh", "token": "bad.jwt"}

        async def _test():
            result = await _handle_token_refresh(ws, envelope)
            assert result is True

        asyncio.run(_test())
        sent = _sent_messages(ws)
        assert len(sent) == 1
        assert sent[0]["type"] == "refresh_error"
        assert "Invalid" in sent[0]["message"]

    def test_missing_token_field_returns_refresh_error(self):
        ws = AsyncMock()
        envelope = {"type": "refresh"}

        async def _test():
            result = await _handle_token_refresh(ws, envelope)
            assert result is True

        asyncio.run(_test())
        sent = _sent_messages(ws)
        assert len(sent) == 1
        assert sent[0]["type"] == "refresh_error"
        assert "Missing" in sent[0]["message"]

    def test_empty_token_returns_refresh_error(self):
        ws = AsyncMock()
        envelope = {"type": "refresh", "token": ""}

        async def _test():
            result = await _handle_token_refresh(ws, envelope)
            assert result is True

        asyncio.run(_test())
        sent = _sent_messages(ws)
        assert len(sent) == 1
        assert sent[0]["type"] == "refresh_error"
        assert "Missing" in sent[0]["message"]


# ── Unit tests for _is_token_expired helper ───────────────────────────────


class TestIsTokenExpired:
    """Tests for the _is_token_expired helper."""

    def test_none_payload_is_not_expired(self):
        assert _is_token_expired(None) is False

    def test_payload_without_exp_is_not_expired(self):
        assert _is_token_expired({"sub": "user-1"}) is False

    def test_payload_with_future_exp_is_not_expired(self):
        future_exp = int(time.time()) + 3600
        assert _is_token_expired({"sub": "user-1", "exp": future_exp}) is False

    def test_payload_with_past_exp_is_expired(self):
        past_exp = int(time.time()) - 10
        assert _is_token_expired({"sub": "user-1", "exp": past_exp}) is True


# ── Task WebSocket token refresh tests ────────────────────────────────────


class TestTaskWSTokenRefresh:
    """Tests for token refresh on the /ws/tasks/{task_id} endpoint."""

    @patch("packages.auth.auth_service.verify_token", return_value={"sub": "user-1"})
    def test_refresh_valid_token_on_task_ws(self, mock_verify):
        from apps.api_server.routes.ws import task_websocket

        ws = _make_ws(
            token=None,
            receive_texts=[
                json.dumps({"type": "refresh", "token": "new-good.jwt"}),
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            await task_websocket(ws, "task-1")

        asyncio.run(_test())
        sent = _sent_messages(ws)
        refresh_ok = [m for m in sent if m["type"] == "refresh_ok"]
        assert len(refresh_ok) == 1

    @patch("packages.auth.auth_service.verify_token", return_value=None)
    def test_refresh_invalid_token_on_task_ws(self, mock_verify):
        from apps.api_server.routes.ws import task_websocket

        ws = _make_ws(
            token=None,
            receive_texts=[
                json.dumps({"type": "refresh", "token": "bad.jwt"}),
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            await task_websocket(ws, "task-2")

        asyncio.run(_test())
        sent = _sent_messages(ws)
        refresh_err = [m for m in sent if m["type"] == "refresh_error"]
        assert len(refresh_err) == 1

    def test_refresh_missing_token_field_on_task_ws(self):
        from apps.api_server.routes.ws import task_websocket

        ws = _make_ws(
            token=None,
            receive_texts=[
                json.dumps({"type": "refresh"}),
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            await task_websocket(ws, "task-3")

        asyncio.run(_test())
        sent = _sent_messages(ws)
        refresh_err = [m for m in sent if m["type"] == "refresh_error"]
        assert len(refresh_err) == 1
        assert "Missing" in refresh_err[0]["message"]


# ── Chat WebSocket token refresh tests ────────────────────────────────────


class TestChatWSTokenRefresh:
    """Tests for token refresh on the /ws/chat endpoint."""

    def test_refresh_valid_token_returns_ok(self):
        from apps.api_server.routes.ws import chat_websocket

        ws = _make_ws(
            token="initial.jwt",
            receive_texts=[
                json.dumps({"type": "refresh", "token": "new-good.jwt"}),
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            with patch(
                "packages.auth.auth_service.verify_token",
                return_value={"sub": "user-1", "exp": int(time.time()) + 3600},
            ):
                await chat_websocket(ws)

        asyncio.run(_test())
        sent = _sent_messages(ws)
        refresh_ok = [m for m in sent if m["type"] == "refresh_ok"]
        assert len(refresh_ok) == 1

    def test_refresh_invalid_token_returns_error(self):
        from apps.api_server.routes.ws import chat_websocket

        # Initial token is valid, refresh token is invalid
        call_count = [0]

        def _verify_side_effect(token):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: initial auth (from endpoint)
                return {"sub": "user-1", "exp": int(time.time()) + 3600}
            # Second call: refresh attempt
            return None

        ws = _make_ws(
            token="initial.jwt",
            receive_texts=[
                json.dumps({"type": "refresh", "token": "bad.jwt"}),
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            with patch(
                "packages.auth.auth_service.verify_token",
                side_effect=_verify_side_effect,
            ):
                await chat_websocket(ws)

        asyncio.run(_test())
        sent = _sent_messages(ws)
        refresh_err = [m for m in sent if m["type"] == "refresh_error"]
        assert len(refresh_err) == 1
        assert "Invalid" in refresh_err[0]["message"]

    def test_refresh_missing_token_field_returns_error(self):
        from apps.api_server.routes.ws import chat_websocket

        ws = _make_ws(
            token=None,  # no auth needed
            receive_texts=[
                json.dumps({"type": "refresh"}),
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            await chat_websocket(ws)

        asyncio.run(_test())
        sent = _sent_messages(ws)
        refresh_err = [m for m in sent if m["type"] == "refresh_error"]
        assert len(refresh_err) == 1
        assert "Missing" in refresh_err[0]["message"]

    def test_refresh_ok_does_not_close_connection(self):
        """After a successful refresh, the connection should remain open
        and accept further messages."""
        from apps.api_server.routes.ws import chat_websocket

        ws = _make_ws(
            token="initial.jwt",
            receive_texts=[
                json.dumps({"type": "refresh", "token": "new.jwt"}),
                "ping",  # second message proves connection stayed open
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            with patch(
                "packages.auth.auth_service.verify_token",
                return_value={"sub": "user-1", "exp": int(time.time()) + 3600},
            ):
                await chat_websocket(ws)

        asyncio.run(_test())
        ws.close.assert_not_called()
        sent = _sent_messages(ws)
        types = [m["type"] for m in sent]
        assert "refresh_ok" in types
        assert "pong" in types

    def test_refresh_error_does_not_close_connection(self):
        """After a failed refresh, the connection should remain open."""
        from apps.api_server.routes.ws import chat_websocket

        call_count = [0]

        def _verify_side_effect(token):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"sub": "user-1", "exp": int(time.time()) + 3600}
            return None

        ws = _make_ws(
            token="initial.jwt",
            receive_texts=[
                json.dumps({"type": "refresh", "token": "bad"}),
                "ping",
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            with patch(
                "packages.auth.auth_service.verify_token",
                side_effect=_verify_side_effect,
            ):
                await chat_websocket(ws)

        asyncio.run(_test())
        ws.close.assert_not_called()
        sent = _sent_messages(ws)
        types = [m["type"] for m in sent]
        assert "refresh_error" in types
        assert "pong" in types


# ── Token expiry notification tests ──────────────────────────────────────


class TestTokenExpiryNotification:
    """Tests for token_expired notification on chat and notification WS."""

    def test_chat_sends_token_expired_when_expired(self):
        """When the initial token has expired, chat WS should send
        token_expired before processing the message."""
        from apps.api_server.routes.ws import chat_websocket

        past_exp = int(time.time()) - 100

        ws = _make_ws(
            token="old.jwt",
            receive_texts=[
                json.dumps({"type": "chat", "message": "hello"}),
                WebSocketDisconnect(),
            ],
        )

        # Need to mock DB layer since the message will proceed to chat handling
        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.id = "conv-exp"
        mock_response = MagicMock()
        mock_response.reply = "ok"
        mock_response.task_id = None

        async def _mock_classify(msg):
            return {"intent": "info", "confidence": 0.9, "extracted": msg}

        async def _test():
            with (
                patch(
                    "packages.auth.auth_service.verify_token",
                    return_value={"sub": "user-1", "exp": past_exp},
                ),
                patch("packages.db.session.SessionLocal", return_value=mock_db),
                patch(
                    "packages.db.repositories.conversation_repo.ConversationRepository"
                ) as mock_repo_cls,
                patch(
                    "apps.api_server.routes.chat._classify_intent",
                    side_effect=_mock_classify,
                ),
                patch(
                    "apps.api_server.routes.chat._handle_info",
                    return_value=mock_response,
                ),
            ):
                mock_repo_cls.create_conversation.return_value = mock_conv
                mock_repo_cls.add_message.return_value = MagicMock()
                await chat_websocket(ws)

        asyncio.run(_test())
        sent = _sent_messages(ws)
        expired_msgs = [m for m in sent if m["type"] == "token_expired"]
        assert len(expired_msgs) == 1
        assert "refresh" in expired_msgs[0]["message"].lower()

    def test_chat_does_not_send_token_expired_when_valid(self):
        """When the token is still valid, no token_expired message is sent."""
        from apps.api_server.routes.ws import chat_websocket

        future_exp = int(time.time()) + 3600

        ws = _make_ws(
            token="fresh.jwt",
            receive_texts=[
                "ping",
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            with patch(
                "packages.auth.auth_service.verify_token",
                return_value={"sub": "user-1", "exp": future_exp},
            ):
                await chat_websocket(ws)

        asyncio.run(_test())
        sent = _sent_messages(ws)
        expired_msgs = [m for m in sent if m["type"] == "token_expired"]
        assert len(expired_msgs) == 0

    def test_chat_no_token_means_no_expiry_check(self):
        """When connected without a token, no expiry check is done."""
        from apps.api_server.routes.ws import chat_websocket

        ws = _make_ws(
            token=None,
            receive_texts=[
                "ping",
                WebSocketDisconnect(),
            ],
        )

        async def _test():
            await chat_websocket(ws)

        asyncio.run(_test())
        sent = _sent_messages(ws)
        expired_msgs = [m for m in sent if m["type"] == "token_expired"]
        assert len(expired_msgs) == 0

    def test_notification_sends_token_expired_when_expired(self):
        """When the notification WS token has expired, it sends token_expired
        when receiving a non-ping/non-refresh message."""
        from fastapi.testclient import TestClient

        from apps.api_server.main import app

        past_exp = int(time.time()) - 100
        mock_payload = {"sub": "alice", "exp": past_exp}

        # Reset singletons
        from packages.notification.notification_service import notification_service
        from packages.notification.notification_ws_manager import notification_ws_manager
        notification_ws_manager._connections.clear()
        notification_service.clear("alice")

        with patch("packages.auth.auth_service.verify_token", return_value=mock_payload):
            client = TestClient(app)
            with client.websocket_connect("/ws/notifications?token=expired.jwt") as ws:
                # Consume initial unread_count
                ws.receive_text()
                # Send a non-ping, non-refresh message to trigger token_expired check
                ws.send_text(json.dumps({"type": "status_check"}))
                data = json.loads(ws.receive_text())
                assert data["type"] == "token_expired"
                assert "refresh" in data["message"].lower()

        notification_ws_manager._connections.clear()

    def test_notification_no_token_means_no_expiry_check(self):
        """When connected without a token, no expiry check is done."""
        from fastapi.testclient import TestClient

        from apps.api_server.main import app
        from packages.notification.notification_service import notification_service
        from packages.notification.notification_ws_manager import notification_ws_manager
        notification_ws_manager._connections.clear()
        notification_service.clear("default")

        client = TestClient(app)
        with client.websocket_connect("/ws/notifications") as ws:
            # Consume initial unread_count
            ws.receive_text()
            ws.send_text(json.dumps({"type": "ping"}))
            data = json.loads(ws.receive_text())
            assert data["type"] == "pong"
            # No more messages — no token_expired

        notification_ws_manager._connections.clear()

    def test_expired_token_does_not_disconnect_client(self):
        """Token expiry sends a notification but does NOT close the connection.
        The client can still send a refresh message afterward."""
        from apps.api_server.routes.ws import chat_websocket

        past_exp = int(time.time()) - 100

        # First verify_token returns expired payload for initial auth.
        # Second verify_token returns valid payload for refresh.
        # Third verify_token (inside refresh handler) returns valid payload.
        call_count = [0]

        def _verify_side_effect(token):
            call_count[0] += 1
            if call_count[0] == 1:
                # Initial auth
                return {"sub": "user-1", "exp": past_exp}
            # Refresh validation
            return {"sub": "user-1", "exp": int(time.time()) + 3600}

        ws = _make_ws(
            token="expired.jwt",
            receive_texts=[
                json.dumps({"type": "chat", "message": "hello"}),
                json.dumps({"type": "refresh", "token": "new-valid.jwt"}),
                "ping",
                WebSocketDisconnect(),
            ],
        )

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.id = "conv-exp2"
        mock_response = MagicMock()
        mock_response.reply = "ok"
        mock_response.task_id = None

        async def _mock_classify(msg):
            return {"intent": "info", "confidence": 0.9, "extracted": msg}

        async def _test():
            with (
                patch(
                    "packages.auth.auth_service.verify_token",
                    side_effect=_verify_side_effect,
                ),
                patch("packages.db.session.SessionLocal", return_value=mock_db),
                patch(
                    "packages.db.repositories.conversation_repo.ConversationRepository"
                ) as mock_repo_cls,
                patch(
                    "apps.api_server.routes.chat._classify_intent",
                    side_effect=_mock_classify,
                ),
                patch(
                    "apps.api_server.routes.chat._handle_info",
                    return_value=mock_response,
                ),
            ):
                mock_repo_cls.create_conversation.return_value = mock_conv
                mock_repo_cls.add_message.return_value = MagicMock()
                await chat_websocket(ws)

        asyncio.run(_test())
        ws.close.assert_not_called()

        sent = _sent_messages(ws)
        types = [m["type"] for m in sent]

        # Should have token_expired (from first message), refresh_ok (from second),
        # and pong (from third)
        assert "token_expired" in types
        assert "refresh_ok" in types
        assert "pong" in types


# ── Notification WebSocket token refresh tests ────────────────────────────


class TestNotificationWSTokenRefresh:
    """Tests for token refresh on the /ws/notifications endpoint."""

    @pytest.fixture(autouse=True)
    def _reset_singletons(self):
        from packages.notification.notification_ws_manager import notification_ws_manager
        notification_ws_manager._connections.clear()
        yield
        notification_ws_manager._connections.clear()

    def test_refresh_valid_token(self):
        from fastapi.testclient import TestClient

        from apps.api_server.main import app
        from packages.notification.notification_service import notification_service
        notification_service.clear("alice")

        mock_payload = {"sub": "alice", "exp": int(time.time()) + 3600}

        call_count = [0]

        def _verify_side_effect(token):
            call_count[0] += 1
            return mock_payload

        with patch("packages.auth.auth_service.verify_token", side_effect=_verify_side_effect):
            client = TestClient(app)
            with client.websocket_connect("/ws/notifications?token=initial.jwt") as ws:
                # Consume initial unread_count
                ws.receive_text()
                # Send refresh
                ws.send_text(json.dumps({"type": "refresh", "token": "new-valid.jwt"}))
                data = json.loads(ws.receive_text())
                assert data["type"] == "refresh_ok"

    def test_refresh_invalid_token_returns_error(self):
        from fastapi.testclient import TestClient

        from apps.api_server.main import app
        from packages.notification.notification_service import notification_service
        notification_service.clear("alice")

        call_count = [0]

        def _verify_side_effect(token):
            call_count[0] += 1
            if call_count[0] == 1:
                # Initial auth
                return {"sub": "alice", "exp": int(time.time()) + 3600}
            # Refresh attempt
            return None

        with patch("packages.auth.auth_service.verify_token", side_effect=_verify_side_effect):
            client = TestClient(app)
            with client.websocket_connect("/ws/notifications?token=initial.jwt") as ws:
                # Consume initial unread_count
                ws.receive_text()
                ws.send_text(json.dumps({"type": "refresh", "token": "bad.jwt"}))
                data = json.loads(ws.receive_text())
                assert data["type"] == "refresh_error"

    def test_refresh_missing_token_field(self):
        from fastapi.testclient import TestClient

        from apps.api_server.main import app
        from packages.notification.notification_service import notification_service
        notification_service.clear("default")

        client = TestClient(app)
        with client.websocket_connect("/ws/notifications") as ws:
            # Consume initial unread_count
            ws.receive_text()
            ws.send_text(json.dumps({"type": "refresh"}))
            data = json.loads(ws.receive_text())
            assert data["type"] == "refresh_error"
            assert "Missing" in data["message"]
