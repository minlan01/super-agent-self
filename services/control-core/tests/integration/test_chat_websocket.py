"""Integration tests for Chat WebSocket — connect, chat flow, ping/pong, errors, lifecycle.

These tests use Starlette's TestClient which supports WebSocket connections
via the context manager protocol.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api_server.main import app


@pytest.fixture()
def client():
    """TestClient with a valid Bearer token (P1: require_auth defaults True).

    The raw token is exposed as ``client.ws_token`` for WebSocket connects
    (WS auth uses ``?token=`` query param, not the Authorization header).
    """
    from tests.integration.conftest import make_auth_header

    from packages.db.session import SessionLocal

    db = SessionLocal()
    try:
        headers = make_auth_header(db)
    finally:
        db.close()

    with TestClient(app) as c:
        c.headers.update(headers)
        c.ws_token = headers["Authorization"].removeprefix("Bearer ")
        yield c


def _ws(client: TestClient, url: str):
    """WebSocket connect with the auth token attached (?token=...)."""
    sep = "&" if "?" in url else "?"
    return client.websocket_connect(f"{url}{sep}token={client.ws_token}")


# ── Task WebSocket: connect, ping/pong ──────────────────────────────────────


@pytest.mark.integration
class TestTaskWebSocket:
    """Tests for /ws/tasks/{task_id} WebSocket endpoint."""

    def test_connect_and_ping_pong(self, client: TestClient):
        """Connecting to a task WS and sending 'ping' should return 'pong'."""
        task_id = str(uuid.uuid4())
        with _ws(client, f"/ws/tasks/{task_id}") as ws:
            ws.send_text("ping")
            data = ws.receive_text()
            assert data == "pong"

    def test_connect_without_token_rejected(self, client: TestClient):
        """Without a token the WS is rejected (P1: require_auth defaults True)."""
        from starlette.websockets import WebSocketDisconnect

        task_id = str(uuid.uuid4())
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/tasks/{task_id}") as ws:
                ws.receive_text()

    def test_multiple_pings_in_sequence(self, client: TestClient):
        """Multiple pings should each get a pong."""
        task_id = str(uuid.uuid4())
        with _ws(client, f"/ws/tasks/{task_id}") as ws:
            for _ in range(5):
                ws.send_text("ping")
                assert ws.receive_text() == "pong"

    def test_different_task_ids_independent(self, client: TestClient):
        """Connections to different task_ids should be independent."""
        task_id_1 = str(uuid.uuid4())
        task_id_2 = str(uuid.uuid4())

        with _ws(client, f"/ws/tasks/{task_id_1}") as ws1:
            with _ws(client, f"/ws/tasks/{task_id_2}") as ws2:
                ws1.send_text("ping")
                ws2.send_text("ping")
                assert ws1.receive_text() == "pong"
                assert ws2.receive_text() == "pong"

    def test_websocket_connection_lifecycle(self, client: TestClient):
        """Connection should be usable, then cleanly close."""
        task_id = str(uuid.uuid4())
        with _ws(client, f"/ws/tasks/{task_id}") as ws:
            ws.send_text("ping")
            assert ws.receive_text() == "pong"
        # After context manager exits, connection is closed


# ── Chat WebSocket: connect, ping/pong ──────────────────────────────────────


@pytest.mark.integration
class TestChatWebSocketPingPong:
    """Tests for /ws/chat ping/pong protocol."""

    def test_raw_text_ping_returns_json_pong(self, client: TestClient):
        """Sending raw 'ping' string should return JSON pong."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text("ping")
            data = json.loads(ws.receive_text())
            assert data["type"] == "pong"

    def test_json_ping_envelope_returns_json_pong(self, client: TestClient):
        """Sending JSON {"type":"ping"} should return JSON pong."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            data = json.loads(ws.receive_text())
            assert data["type"] == "pong"

    def test_multiple_pings(self, client: TestClient):
        """Multiple sequential pings should each get a pong."""
        with _ws(client, "/ws/chat") as ws:
            for _ in range(3):
                ws.send_text(json.dumps({"type": "ping"}))
                data = json.loads(ws.receive_text())
                assert data["type"] == "pong"


# ── Chat WebSocket: error handling ──────────────────────────────────────────


@pytest.mark.integration
class TestChatWebSocketErrors:
    """Tests for invalid message handling on /ws/chat."""

    def test_invalid_json_returns_error(self, client: TestClient):
        """Non-JSON text (not 'ping') should return an error."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text("not-valid-json{{{")
            data = json.loads(ws.receive_text())
            assert data["type"] == "error"
            assert "Invalid JSON" in data["message"]

    def test_missing_message_field_returns_error(self, client: TestClient):
        """Chat envelope without 'message' field should return error."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text(json.dumps({"type": "chat"}))
            data = json.loads(ws.receive_text())
            assert data["type"] == "error"
            assert "message" in data["message"].lower()

    def test_empty_message_returns_error(self, client: TestClient):
        """Chat envelope with empty/whitespace message should return error."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text(json.dumps({"type": "chat", "message": "   "}))
            data = json.loads(ws.receive_text())
            assert data["type"] == "error"

    def test_unknown_type_returns_error(self, client: TestClient):
        """Unknown message type should return error."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text(json.dumps({"type": "unknown_xyz"}))
            data = json.loads(ws.receive_text())
            assert data["type"] == "error"
            assert "unknown_xyz" in data["message"]


# ── Chat WebSocket: full chat flow ──────────────────────────────────────────


@pytest.mark.integration
class TestChatWebSocketFlow:
    """Tests for the complete chat flow through /ws/chat."""

    def test_chat_message_receives_typing_and_reply(self, client: TestClient):
        """Sending a chat message should produce typing indicator then reply."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text(json.dumps({
                "type": "chat",
                "message": "Hello, what can you do?",
            }))

            messages = []
            # Read messages until we get a 'message' type or timeout
            for _ in range(10):
                raw = ws.receive_text()
                msg = json.loads(raw)
                messages.append(msg)
                if msg.get("type") == "message":
                    break

            types = [m["type"] for m in messages]
            assert "typing" in types, f"Expected typing indicator, got types: {types}"
            assert "message" in types, f"Expected assistant message, got types: {types}"

            reply = next(m for m in messages if m["type"] == "message")
            assert reply["role"] == "assistant"
            assert len(reply["content"]) > 0
            assert reply.get("conversation_id") is not None

    def test_chat_with_task_intent_creates_task(self, client: TestClient):
        """Sending a task-oriented message should create a task."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text(json.dumps({
                "type": "chat",
                "message": "search for latest AI news",
            }))

            messages = []
            for _ in range(10):
                raw = ws.receive_text()
                msg = json.loads(raw)
                messages.append(msg)
                if msg.get("type") == "message":
                    break

            reply = next(m for m in messages if m["type"] == "message")
            assert "task" in reply["content"].lower() or "Task ID" in reply["content"]

    def test_chat_with_reminder_intent(self, client: TestClient):
        """Sending a reminder message should trigger reminder creation."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text(json.dumps({
                "type": "chat",
                "message": "remind me to check emails tomorrow",
            }))

            messages = []
            for _ in range(10):
                raw = ws.receive_text()
                msg = json.loads(raw)
                messages.append(msg)
                if msg.get("type") == "message":
                    break

            reply = next(m for m in messages if m["type"] == "message")
            assert "reminder" in reply["content"].lower() or "remind" in reply["content"].lower()

    def test_chat_with_continuation_conversation_id(self, client: TestClient):
        """Second message with same conversation_id should continue the chat."""
        with _ws(client, "/ws/chat") as ws:
            # First message
            ws.send_text(json.dumps({
                "type": "chat",
                "message": "hello",
            }))

            first_messages = []
            conv_id = None
            for _ in range(10):
                raw = ws.receive_text()
                msg = json.loads(raw)
                first_messages.append(msg)
                if msg.get("type") == "message":
                    conv_id = msg.get("conversation_id")
                    break

            assert conv_id is not None

            # Second message with conversation_id
            ws.send_text(json.dumps({
                "type": "chat",
                "message": "what else can you do?",
                "conversation_id": conv_id,
            }))

            second_messages = []
            for _ in range(10):
                raw = ws.receive_text()
                msg = json.loads(raw)
                second_messages.append(msg)
                if msg.get("type") == "message":
                    break

            reply = next(m for m in second_messages if m["type"] == "message")
            assert reply["conversation_id"] == conv_id


# ── Chat WebSocket: multiple sequential messages ────────────────────────────


@pytest.mark.integration
class TestChatWebSocketSequential:
    """Test multiple sequential messages on the same connection."""

    def test_sequential_ping_and_chat(self, client: TestClient):
        """Ping followed by chat should both work."""
        with _ws(client, "/ws/chat") as ws:
            # Ping
            ws.send_text("ping")
            assert json.loads(ws.receive_text())["type"] == "pong"

            # Chat
            ws.send_text(json.dumps({
                "type": "chat",
                "message": "hi there",
            }))

            messages = []
            for _ in range(10):
                raw = ws.receive_text()
                msg = json.loads(raw)
                messages.append(msg)
                if msg.get("type") == "message":
                    break

            assert any(m["type"] == "typing" for m in messages)
            assert any(m["type"] == "message" for m in messages)

    def test_error_then_valid_message(self, client: TestClient):
        """An error response should not break the connection."""
        with _ws(client, "/ws/chat") as ws:
            # Invalid message
            ws.send_text("not-json")
            error = json.loads(ws.receive_text())
            assert error["type"] == "error"

            # Valid ping after error
            ws.send_text("ping")
            pong = json.loads(ws.receive_text())
            assert pong["type"] == "pong"

    def test_multiple_errors_in_sequence(self, client: TestClient):
        """Multiple invalid messages should each get an error response."""
        with _ws(client, "/ws/chat") as ws:
            for _ in range(3):
                ws.send_text("{{{invalid")
                error = json.loads(ws.receive_text())
                assert error["type"] == "error"
                assert "Invalid JSON" in error["message"]


# ── Chat WebSocket: connection lifecycle ─────────────────────────────────────


@pytest.mark.integration
class TestChatWebSocketLifecycle:
    """Test connection lifecycle behavior."""

    def test_connection_opens_successfully(self, client: TestClient):
        """WebSocket should open without error."""
        with _ws(client, "/ws/chat") as ws:
            # If we get here, the connection opened
            ws.send_text("ping")
            assert json.loads(ws.receive_text())["type"] == "pong"

    def test_connection_close_is_clean(self, client: TestClient):
        """Closing the context manager should cleanly close the connection."""
        with _ws(client, "/ws/chat") as ws:
            ws.send_text("ping")
            ws.receive_text()
        # Context manager exit should not raise

    def test_task_and_chat_websockets_coexist(self, client: TestClient):
        """Both task and chat WebSocket should work simultaneously."""
        task_id = str(uuid.uuid4())
        with _ws(client, f"/ws/tasks/{task_id}") as task_ws:
            with _ws(client, "/ws/chat") as chat_ws:
                task_ws.send_text("ping")
                assert task_ws.receive_text() == "pong"

                chat_ws.send_text(json.dumps({"type": "ping"}))
                assert json.loads(chat_ws.receive_text())["type"] == "pong"
