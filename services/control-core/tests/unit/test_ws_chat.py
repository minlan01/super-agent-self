"""Tests for ChatConnectionManager and /ws/chat WebSocket endpoint."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketDisconnect

from apps.api_server.routes.ws import ChatConnectionManager

# ── ChatConnectionManager tests ────────────────────────────────────────────


class TestChatConnectionManager:
    """Tests for the ChatConnectionManager class (connection tracking per user)."""

    def test_connect_adds_connection(self):
        manager = ChatConnectionManager()
        ws = AsyncMock()

        async def _test():
            await manager.connect(ws, "user-1")
            assert "user-1" in manager._connections
            assert len(manager._connections["user-1"]) == 1
            assert manager.active_connections == 1

        asyncio.run(_test())

    def test_connect_multiple_users(self):
        manager = ChatConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        async def _test():
            await manager.connect(ws1, "user-1")
            await manager.connect(ws2, "user-2")
            assert manager.active_connections == 2
            assert manager.active_users == 2

        asyncio.run(_test())

    def test_connect_same_user_multiple_times(self):
        manager = ChatConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        async def _test():
            await manager.connect(ws1, "user-1")
            await manager.connect(ws2, "user-1")
            assert len(manager._connections["user-1"]) == 2
            assert manager.active_connections == 2
            assert manager.active_users == 1

        asyncio.run(_test())

    def test_disconnect_removes_single_connection(self):
        manager = ChatConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        async def _test():
            await manager.connect(ws1, "user-1")
            await manager.connect(ws2, "user-1")
            await manager.disconnect(ws1, "user-1")
            assert len(manager._connections["user-1"]) == 1
            assert manager.active_connections == 1

        asyncio.run(_test())

    def test_disconnect_last_removes_key(self):
        manager = ChatConnectionManager()
        ws = AsyncMock()

        async def _test():
            await manager.connect(ws, "user-1")
            await manager.disconnect(ws, "user-1")
            assert "user-1" not in manager._connections
            assert manager.active_connections == 0
            assert manager.active_users == 0

        asyncio.run(_test())

    def test_disconnect_nonexistent_user_no_error(self):
        manager = ChatConnectionManager()
        ws = AsyncMock()

        async def _test():
            await manager.disconnect(ws, "nonexistent")

        asyncio.run(_test())

    def test_send_to_user_broadcasts_to_all_connections(self):
        manager = ChatConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        async def _test():
            await manager.connect(ws1, "user-1")
            await manager.connect(ws2, "user-1")
            await manager.send_to_user("user-1", {"type": "message", "content": "hello"})

            expected = json.dumps({"type": "message", "content": "hello"})
            ws1.send_text.assert_called_once_with(expected)
            ws2.send_text.assert_called_once_with(expected)

        asyncio.run(_test())

    def test_send_to_user_no_connections(self):
        manager = ChatConnectionManager()

        async def _test():
            # Should not raise
            await manager.send_to_user("user-999", {"type": "message"})

        asyncio.run(_test())

    def test_send_to_user_removes_dead_connections(self):
        manager = ChatConnectionManager()
        ws = AsyncMock()
        ws.send_text.side_effect = Exception("Connection closed")

        async def _test():
            await manager.connect(ws, "user-1")
            await manager.send_to_user("user-1", {"type": "message"})
            assert manager.active_connections == 0

        asyncio.run(_test())

    def test_send_to_user_partial_dead_connections(self):
        manager = ChatConnectionManager()
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = Exception("dead")

        async def _test():
            await manager.connect(ws_alive, "user-1")
            await manager.connect(ws_dead, "user-1")
            await manager.send_to_user("user-1", {"type": "ping"})

            ws_alive.send_text.assert_called_once()
            assert manager.active_connections == 1

        asyncio.run(_test())

    def test_broadcast_sends_to_all_users(self):
        manager = ChatConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()

        async def _test():
            await manager.connect(ws1, "user-1")
            await manager.connect(ws2, "user-2")
            await manager.connect(ws3, "user-2")
            await manager.broadcast({"type": "system", "text": "maintenance"})

            expected = json.dumps({"type": "system", "text": "maintenance"})
            ws1.send_text.assert_called_once_with(expected)
            ws2.send_text.assert_called_once_with(expected)
            ws3.send_text.assert_called_once_with(expected)

        asyncio.run(_test())

    def test_broadcast_prunes_dead_connections(self):
        manager = ChatConnectionManager()
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = Exception("gone")

        async def _test():
            await manager.connect(ws_alive, "user-1")
            await manager.connect(ws_dead, "user-2")
            await manager.broadcast({"type": "ping"})

            assert manager.active_connections == 1
            assert manager.active_users == 1

        asyncio.run(_test())

    def test_active_users_count(self):
        manager = ChatConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        async def _test():
            await manager.connect(ws1, "user-1")
            assert manager.active_users == 1
            await manager.connect(ws2, "user-2")
            assert manager.active_users == 2
            await manager.disconnect(ws1, "user-1")
            assert manager.active_users == 1

        asyncio.run(_test())

    def test_active_connections_initial(self):
        manager = ChatConnectionManager()
        assert manager.active_connections == 0
        assert manager.active_users == 0


# ── _resolve_chat_user tests ───────────────────────────────────────────────
#
# _resolve_chat_user does a lazy import: from packages.auth.auth_service import verify_token
# We must patch at the source module, not at ws module level.


class TestResolveChatUser:
    """Tests for the _resolve_chat_user helper."""

    @patch("packages.auth.auth_service.verify_token", return_value={"sub": "user-42"})
    def test_valid_token_returns_user_id(self, mock_verify):
        from apps.api_server.routes.ws import _resolve_chat_user

        ws = MagicMock()
        ws.query_params.get.return_value = "valid-token"

        async def _test():
            result = await _resolve_chat_user(ws)
            assert result == "user-42"

        asyncio.run(_test())

    @patch("packages.auth.auth_service.verify_token", return_value=None)
    def test_invalid_token_returns_default(self, mock_verify):
        from apps.api_server.routes.ws import _resolve_chat_user

        ws = MagicMock()
        ws.query_params.get.return_value = "bad-token"

        async def _test():
            result = await _resolve_chat_user(ws)
            assert result == "default"

        asyncio.run(_test())

    def test_no_token_returns_default(self):
        from apps.api_server.routes.ws import _resolve_chat_user

        ws = MagicMock()
        ws.query_params.get.return_value = None

        async def _test():
            result = await _resolve_chat_user(ws)
            assert result == "default"

        asyncio.run(_test())

    @patch("packages.auth.auth_service.verify_token", return_value={"exp": 999})
    def test_token_without_sub_returns_default(self, mock_verify):
        from apps.api_server.routes.ws import _resolve_chat_user

        ws = MagicMock()
        ws.query_params.get.return_value = "token-no-sub"

        async def _test():
            result = await _resolve_chat_user(ws)
            assert result == "default"

        asyncio.run(_test())


# ── Chat WebSocket endpoint tests ──────────────────────────────────────────


class TestChatWebSocket:
    """Tests for the /ws/chat endpoint message handling."""

    @pytest.fixture(autouse=True)
    def _disable_auth(self):
        from packages.config import get_settings
        settings = get_settings()
        prev = settings.security.require_auth
        settings.security.require_auth = False
        yield
        settings.security.require_auth = prev

    def _make_ws(self, token=None):
        """Create an AsyncMock WebSocket with proper query_params mock."""
        ws = AsyncMock()
        # query_params.get must be a regular MagicMock (not AsyncMock)
        ws.query_params = MagicMock()
        ws.query_params.get.return_value = token
        return ws

    def test_ping_text_pong(self):
        """Raw 'ping' string returns JSON pong."""
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(token=None)
        ws.receive_text.side_effect = ["ping", WebSocketDisconnect()]

        async def _test():
            await chat_websocket(ws)

        asyncio.run(_test())
        sent = [call[0][0] for call in ws.send_text.call_args_list]
        assert any(
            json.loads(s).get("type") == "pong" for s in sent
        ), f"Expected pong in {sent}"

    def test_ping_json_envelope(self):
        """JSON ping envelope returns JSON pong."""
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(token=None)
        ws.receive_text.side_effect = [
            json.dumps({"type": "ping"}),
            WebSocketDisconnect(),
        ]

        async def _test():
            await chat_websocket(ws)

        asyncio.run(_test())
        sent = [call[0][0] for call in ws.send_text.call_args_list]
        assert any(
            json.loads(s).get("type") == "pong" for s in sent
        ), f"Expected pong in {sent}"

    def test_invalid_json_returns_error(self):
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(token=None)
        ws.receive_text.side_effect = ["not-json{{{", WebSocketDisconnect()]

        async def _test():
            await chat_websocket(ws)

        asyncio.run(_test())
        sent = [call[0][0] for call in ws.send_text.call_args_list]
        error_msgs = [json.loads(s) for s in sent if json.loads(s).get("type") == "error"]
        assert len(error_msgs) == 1
        assert "Invalid JSON" in error_msgs[0]["message"]

    def test_missing_message_field_returns_error(self):
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(token=None)
        ws.receive_text.side_effect = [
            json.dumps({"type": "chat"}),
            WebSocketDisconnect(),
        ]

        async def _test():
            await chat_websocket(ws)

        asyncio.run(_test())
        sent = [call[0][0] for call in ws.send_text.call_args_list]
        error_msgs = [json.loads(s) for s in sent if json.loads(s).get("type") == "error"]
        assert len(error_msgs) == 1
        assert "message" in error_msgs[0]["message"].lower()

    def test_empty_message_returns_error(self):
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(token=None)
        ws.receive_text.side_effect = [
            json.dumps({"type": "chat", "message": "   "}),
            WebSocketDisconnect(),
        ]

        async def _test():
            await chat_websocket(ws)

        asyncio.run(_test())
        sent = [call[0][0] for call in ws.send_text.call_args_list]
        error_msgs = [json.loads(s) for s in sent if json.loads(s).get("type") == "error"]
        assert len(error_msgs) == 1

    def test_unknown_message_type_returns_error(self):
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(token=None)
        ws.receive_text.side_effect = [
            json.dumps({"type": "unknown_type"}),
            WebSocketDisconnect(),
        ]

        async def _test():
            await chat_websocket(ws)

        asyncio.run(_test())
        sent = [call[0][0] for call in ws.send_text.call_args_list]
        error_msgs = [json.loads(s) for s in sent if json.loads(s).get("type") == "error"]
        assert len(error_msgs) == 1
        assert "unknown_type" in error_msgs[0]["message"]

    def test_invalid_token_closes_connection(self):
        """When verify_token returns None, the endpoint should close with 4001."""
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(token="invalid-token")

        async def _test():
            with patch("packages.auth.auth_service.verify_token", return_value=None):
                await chat_websocket(ws)

        asyncio.run(_test())
        ws.close.assert_called_once_with(code=4001, reason="Invalid or expired token")

    def test_auth_failure_closes_with_4001(self):
        """Explicit patch: verify_token returns None → close 4001."""
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(token="bad")

        async def _test():
            with patch("packages.auth.auth_service.verify_token", return_value=None):
                await chat_websocket(ws)

        asyncio.run(_test())
        ws.close.assert_called_once_with(code=4001, reason="Invalid or expired token")

    def test_valid_token_accepts_connection(self):
        """Valid token should accept the WebSocket (not close it)."""
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(token="good-token")
        ws.receive_text.side_effect = [WebSocketDisconnect()]

        mock_user = MagicMock()
        mock_user.id = "user-1"
        mock_user.role = MagicMock(value="user")

        async def _test():
            with (
                patch(
                    "packages.auth.auth_service.verify_token",
                    return_value={"sub": "user-1"},
                ),
                patch(
                    "packages.db.repositories.auth_repo.AuthRepository.get_by_id",
                    return_value=mock_user,
                ),
                patch(
                    "packages.auth.rbac.get_rbac_service",
                ) as mock_rbac_cls,
            ):
                mock_rbac = MagicMock()
                mock_rbac.rbac_enabled = False
                mock_rbac_cls.return_value = mock_rbac
                await chat_websocket(ws)

        asyncio.run(_test())
        ws.close.assert_not_called()
        ws.accept.assert_called_once()


# ── _handle_chat_message tests ─────────────────────────────────────────────
#
# _handle_chat_message uses lazy imports from its source modules.
# We patch at the source to intercept the imports inside the function body.


class TestHandleChatMessage:
    """Tests for the _handle_chat_message helper."""

    @patch("apps.api_server.routes.ws.manager")
    @patch("apps.api_server.routes.ws.chat_manager")
    @patch("packages.db.repositories.conversation_repo.ConversationRepository")
    @patch("packages.db.session.SessionLocal")
    def test_chat_message_sends_typing_then_reply(
        self, mock_session_local, mock_conv_repo_cls, mock_chat_mgr, mock_task_mgr
    ):
        """Full flow: typing indicator, then assistant message."""
        from apps.api_server.routes.ws import _handle_chat_message

        ws = AsyncMock()
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        # ConversationRepository.create_conversation returns a mock conv
        mock_conv = MagicMock()
        mock_conv.id = "conv-123"

        mock_conv_repo_cls.create_conversation.return_value = mock_conv
        mock_conv_repo_cls.add_message.return_value = MagicMock()

        mock_response = MagicMock()
        mock_response.reply = "Hello! How can I help?"
        mock_response.task_id = None

        async def _mock_classify(msg):
            return {"intent": "info", "confidence": 0.9, "extracted": "hello"}

        with (
            patch(
                "apps.api_server.routes.chat._classify_intent",
                side_effect=_mock_classify,
            ),
            patch(
                "apps.api_server.routes.chat._handle_info",
                return_value=mock_response,
            ),
        ):
            asyncio.run(_handle_chat_message(
                websocket=ws,
                user_id="default",
                message="hello",
                conversation_id=None,
            ))

        # Verify typing indicator was sent
        sent_texts = [call[0][0] for call in ws.send_text.call_args_list]
        types = [json.loads(t)["type"] for t in sent_texts]
        assert "typing" in types
        assert "message" in types

        # Verify the assistant message content
        msg_calls = [json.loads(t) for t in sent_texts if json.loads(t).get("type") == "message"]
        assert len(msg_calls) == 1
        assert msg_calls[0]["role"] == "assistant"
        assert msg_calls[0]["content"] == "Hello! How can I help?"
        assert msg_calls[0]["conversation_id"] == "conv-123"

    @patch("apps.api_server.routes.ws.manager")
    @patch("apps.api_server.routes.ws.chat_manager")
    @patch("packages.db.repositories.conversation_repo.ConversationRepository")
    @patch("packages.db.session.SessionLocal")
    def test_chat_message_with_existing_conversation(
        self, mock_session_local, mock_conv_repo_cls, mock_chat_mgr, mock_task_mgr
    ):
        """When conversation_id is provided, it should be reused."""
        from apps.api_server.routes.ws import _handle_chat_message

        ws = AsyncMock()
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        mock_conv = MagicMock()
        mock_conv.id = "existing-conv"

        mock_response = MagicMock()
        mock_response.reply = "OK"
        mock_response.task_id = None

        async def _mock_classify(msg):
            return {"intent": "info", "confidence": 0.9, "extracted": msg}

        mock_conv_repo_cls.get_conversation.return_value = mock_conv
        mock_conv_repo_cls.add_message.return_value = MagicMock()

        with (
            patch(
                "apps.api_server.routes.chat._classify_intent",
                side_effect=_mock_classify,
            ),
            patch(
                "apps.api_server.routes.chat._handle_info",
                return_value=mock_response,
            ),
        ):
            asyncio.run(_handle_chat_message(
                websocket=ws,
                user_id="user-1",
                message="test",
                conversation_id="existing-conv",
            ))

            # Should NOT create a new conversation
            mock_conv_repo_cls.create_conversation.assert_not_called()

    @patch("packages.db.repositories.conversation_repo.ConversationRepository")
    @patch("packages.db.session.SessionLocal")
    def test_chat_message_with_task_creation_broadcasts_status(
        self, mock_session_local, mock_conv_repo_cls
    ):
        """When a task is created, task_status should be broadcast."""
        from apps.api_server.routes.ws import _handle_chat_message

        ws = AsyncMock()
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        # chat_manager.send_to_user is async — use AsyncMock
        mock_chat_mgr = AsyncMock()
        mock_chat_mgr.send_to_user = AsyncMock()
        # manager.send_update is also async
        mock_task_mgr = AsyncMock()
        mock_task_mgr.send_update = AsyncMock()

        mock_conv = MagicMock()
        mock_conv.id = "conv-456"

        mock_response = MagicMock()
        mock_response.reply = "Task created"
        mock_response.task_id = "task-789"
        mock_response.action = "task_created"

        mock_conv_repo_cls.create_conversation.return_value = mock_conv
        mock_conv_repo_cls.add_message.return_value = MagicMock()

        async def _mock_classify(msg):
            return {"intent": "task", "confidence": 0.9, "extracted": msg}

        with (
            patch(
                "apps.api_server.routes.ws.manager",
                new=mock_task_mgr,
            ),
            patch(
                "apps.api_server.routes.ws.chat_manager",
                new=mock_chat_mgr,
            ),
            patch(
                "apps.api_server.routes.chat._classify_intent",
                side_effect=_mock_classify,
            ),
            patch(
                "apps.api_server.routes.chat._handle_task",
                return_value=mock_response,
            ),
        ):
            asyncio.run(_handle_chat_message(
                websocket=ws,
                user_id="user-1",
                message="help me search",
                conversation_id=None,
            ))

            # chat_manager.send_to_user should be called
            mock_chat_mgr.send_to_user.assert_called_once()
            call_args = mock_chat_mgr.send_to_user.call_args
            assert call_args[0][0] == "user-1"
            assert call_args[0][1]["type"] == "task_status"

            # task manager.send_update should also be called
            mock_task_mgr.send_update.assert_called_once()
            call_args = mock_task_mgr.send_update.call_args
            assert call_args[0][0] == "task-789"
            assert call_args[0][1]["type"] == "task_status"

    @patch("apps.api_server.routes.ws.manager")
    @patch("apps.api_server.routes.ws.chat_manager")
    @patch("packages.db.repositories.conversation_repo.ConversationRepository")
    @patch("packages.db.session.SessionLocal")
    def test_chat_message_error_handled_gracefully(
        self, mock_session_local, mock_conv_repo_cls, mock_chat_mgr, mock_task_mgr
    ):
        """Exceptions in chat handling propagate from _handle_chat_message.

        The endpoint wraps this in try/except and sends error back to client.
        Here we verify the exception propagates (the endpoint catches it).
        """
        from apps.api_server.routes.ws import _handle_chat_message

        ws = AsyncMock()
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        mock_conv = MagicMock()
        mock_conv.id = "conv-err"

        mock_conv_repo_cls.create_conversation.return_value = mock_conv
        mock_conv_repo_cls.add_message.return_value = MagicMock()

        with patch(
            "apps.api_server.routes.chat._classify_intent",
            side_effect=RuntimeError("LLM exploded"),
        ):
            # _handle_chat_message should propagate the exception
            # (the chat_websocket endpoint catches it)
            with pytest.raises(RuntimeError, match="LLM exploded"):
                asyncio.run(_handle_chat_message(
                    websocket=ws,
                    user_id="default",
                    message="trigger error",
                    conversation_id=None,
                ))

        # DB should still be closed in finally (run_in_thread also closes its own sessions)
        assert mock_db.close.call_count >= 1

    @patch("apps.api_server.routes.ws.manager")
    @patch("apps.api_server.routes.ws.chat_manager")
    @patch("packages.db.repositories.conversation_repo.ConversationRepository")
    @patch("packages.db.session.SessionLocal")
    def test_db_closed_in_finally(
        self, mock_session_local, mock_conv_repo_cls, mock_chat_mgr, mock_task_mgr
    ):
        """The DB session must be closed even on success."""
        from apps.api_server.routes.ws import _handle_chat_message

        ws = AsyncMock()
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db

        mock_conv = MagicMock()
        mock_conv.id = "conv-close"

        mock_conv_repo_cls.create_conversation.return_value = mock_conv
        mock_conv_repo_cls.add_message.return_value = MagicMock()

        async def _mock_classify(msg):
            return {"intent": "info", "confidence": 0.9, "extracted": msg}

        mock_response = MagicMock()
        mock_response.reply = "ok"
        mock_response.task_id = None

        with (
            patch(
                "apps.api_server.routes.chat._classify_intent",
                side_effect=_mock_classify,
            ),
            patch(
                "apps.api_server.routes.chat._handle_info",
                return_value=mock_response,
            ),
        ):
            asyncio.run(_handle_chat_message(
                websocket=ws,
                user_id="default",
                message="test",
                conversation_id=None,
            ))

        # run_in_thread also creates/closes its own sessions via SessionLocal
        assert mock_db.close.call_count >= 1


# ── Full endpoint integration tests ────────────────────────────────────────


class TestChatWebSocketIntegration:
    """Higher-level tests that exercise the full chat_websocket endpoint."""

    @pytest.fixture(autouse=True)
    def _disable_auth(self):
        from packages.config import get_settings
        settings = get_settings()
        prev = settings.security.require_auth
        settings.security.require_auth = False
        yield
        settings.security.require_auth = prev

    def _make_ws(self, token=None, receive_texts=None):
        """Create an AsyncMock WebSocket with proper query_params mock."""
        ws = AsyncMock()
        ws.query_params = MagicMock()
        ws.query_params.get.return_value = token
        if receive_texts is not None:
            ws.receive_text.side_effect = receive_texts
        return ws

    def test_chat_message_goes_through_full_flow(self):
        """A valid chat message should trigger typing, then assistant reply."""
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(receive_texts=[
            json.dumps({"type": "chat", "message": "hello world"}),
            WebSocketDisconnect(),
        ])

        mock_response = MagicMock()
        mock_response.reply = "Hi there!"
        mock_response.task_id = None

        mock_conv = MagicMock()
        mock_conv.id = "conv-int-1"
        mock_db = MagicMock()

        async def _mock_classify(msg):
            return {"intent": "info", "confidence": 0.8, "extracted": msg}

        async def _test():
            with (
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

        sent = [call[0][0] for call in ws.send_text.call_args_list]
        types = [json.loads(s)["type"] for s in sent]
        assert "typing" in types
        assert "message" in types

        reply = [json.loads(s) for s in sent if json.loads(s).get("type") == "message"]
        assert len(reply) == 1
        assert reply[0]["role"] == "assistant"
        assert reply[0]["content"] == "Hi there!"

    def test_chat_internal_error_sends_error_to_client(self):
        """If _handle_chat_message raises, the endpoint sends an error message."""
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(receive_texts=[
            json.dumps({"type": "chat", "message": "break it"}),
            WebSocketDisconnect(),
        ])

        mock_db = MagicMock()

        async def _test():
            with (
                patch("packages.db.session.SessionLocal", return_value=mock_db),
                patch(
                    "packages.db.repositories.conversation_repo.ConversationRepository"
                ) as mock_repo_cls,
                patch(
                    "apps.api_server.routes.chat._classify_intent",
                    side_effect=RuntimeError("boom"),
                ),
            ):
                mock_conv = MagicMock()
                mock_conv.id = "conv-err-2"
                mock_repo_cls.create_conversation.return_value = mock_conv
                mock_repo_cls.add_message.return_value = MagicMock()
                await chat_websocket(ws)

        asyncio.run(_test())

        sent = [call[0][0] for call in ws.send_text.call_args_list]
        error_msgs = [json.loads(s) for s in sent if json.loads(s).get("type") == "error"]
        assert len(error_msgs) == 1
        assert "Internal error" in error_msgs[0]["message"]

    def test_multiple_messages_in_sequence(self):
        """Multiple chat messages should each get a response."""
        from apps.api_server.routes.ws import chat_websocket

        ws = self._make_ws(receive_texts=[
            json.dumps({"type": "chat", "message": "first"}),
            json.dumps({"type": "chat", "message": "second"}),
            WebSocketDisconnect(),
        ])

        mock_response = MagicMock()
        mock_response.reply = "Response"
        mock_response.task_id = None

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.id = "conv-seq"

        async def _mock_classify(msg):
            return {"intent": "info", "confidence": 0.8, "extracted": msg}

        async def _test():
            with (
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

        sent = [call[0][0] for call in ws.send_text.call_args_list]
        messages = [json.loads(s) for s in sent if json.loads(s).get("type") == "message"]
        assert len(messages) == 2
        for m in messages:
            assert m["role"] == "assistant"
