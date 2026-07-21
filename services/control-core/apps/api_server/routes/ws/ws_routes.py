"""WebSocket route endpoints — tasks, chat, and notifications."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from apps.api_server.routes.ws.ws_auth import (
    _check_ws_permission,
    _handle_token_refresh,
    _is_token_expired,
    _resolve_chat_user,
)

logger = logging.getLogger(__name__)

MAX_MESSAGE_SIZE = 1_000_000
_MAX_CHAT_MESSAGE_LENGTH = 5000

router = APIRouter()


async def _ws_authenticate(
    websocket: WebSocket,
    resource: str,
    action: str,
) -> tuple[dict | None, str] | None:
    """Authenticate a WebSocket connection.

    Returns ``(token_payload, user_id)`` on success, or ``None`` if the
    connection was already closed (caller should return immediately).
    """
    from packages.config import get_settings
    settings = get_settings()

    token = websocket.query_params.get("token")
    if settings.security.require_auth and not token:
        await websocket.close(code=4001, reason="Authentication required")
        return None

    token_payload: dict | None = None
    if token:
        from packages.auth.auth_service import verify_token
        token_payload = verify_token(token)

    if token and token_payload is None:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return None

    if token and token_payload:
        user = await _check_ws_permission(websocket, resource, action)
        if user is None:
            return None

    user_id = (token_payload or {}).get("sub", "default") if token_payload else "default"
    return token_payload, user_id


def _get_managers():
    """Return ``(manager, chat_manager)`` singletons.

    Deferred import from the package so that test patches targeting
    ``apps.api_server.routes.ws.manager`` (and ``chat_manager``) are
    respected — the module-level name in ``__init__.py`` is patched,
    and we read it at call-time rather than at import-time.
    """
    # Import the *package* (not connection_managers directly) so that
    # ``unittest.mock.patch("apps.api_server.routes.ws.manager")`` works.
    from apps.api_server.routes import ws as _ws_pkg
    return _ws_pkg.manager, _ws_pkg.chat_manager


# ── Task WebSocket Endpoint ──────────────────────────────────────────────────


@router.websocket("/ws/tasks/{task_id}")
async def task_websocket(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time task updates.

    Optional auth: pass ``?token=<jwt>`` in the query string.
    When REQUIRE_AUTH=true the token is validated; otherwise any connection
    is accepted for backward compatibility.
    """
    manager, _ = _get_managers()

    auth_result = await _ws_authenticate(websocket, "tasks", "read")
    if auth_result is None:
        return

    await manager.connect(websocket, task_id)
    try:
        while True:
            data = await websocket.receive_text()
            if len(data) > MAX_MESSAGE_SIZE:
                logger.warning("Task WS: oversized message (%d bytes) from task %s", len(data), task_id)
                await websocket.close(code=1009, reason="Message too large")
                break
            if data == "ping":
                await websocket.send_text("pong")
                continue

            try:
                envelope = json.loads(data)
            except json.JSONDecodeError:
                continue

            if envelope.get("type") == "refresh":
                await _handle_token_refresh(websocket, envelope)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, task_id)


# ── Chat WebSocket Endpoint ─────────────────────────────────────────────────


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """Bidirectional chat over WebSocket.

    Protocol (JSON messages sent by the client):
    - ``{"type": "chat", "message": "...", "conversation_id": "..."}``
      → the server processes the message via intent classification and
        streams back the assistant reply.
    - ``{"type": "ping"}``
      → the server replies with ``{"type": "pong"}``.
    - ``{"type": "refresh", "token": "<new_jwt>"}``
      → server validates the new token and replies ``{"type": "refresh_ok"}``
        or ``{"type": "refresh_error", "message": "..."}``.

    Server→client messages:
    - ``{"type": "typing"}`` — sent before the LLM starts generating.
    - ``{"type": "message", "role": "assistant", "content": "...", "conversation_id": "..."}``
    - ``{"type": "pong"}`` — heartbeat reply.
    - ``{"type": "task_status", "task_id": "...", "status": "...", ...}``
      — forwarded when a task is created via chat.
    - ``{"type": "token_expired", "message": "Token expired, please refresh"}``
      — sent when the initial token has expired.

    Auth: pass ``?token=<jwt>`` to identify the user.  Without a token the
    user is treated as ``"default"`` (backward-compatible).
    """
    _, chat_manager = _get_managers()

    auth_result = await _ws_authenticate(websocket, "chat", "write")
    if auth_result is None:
        return
    token_payload, user_id = auth_result

    await chat_manager.connect(websocket, user_id)
    try:
        while True:
            raw = await websocket.receive_text()

            if len(raw) > MAX_MESSAGE_SIZE:
                logger.warning("Chat WS: oversized message (%d bytes) from user %s", len(raw), user_id)
                await websocket.close(code=1009, reason="Message too large")
                break

            # --- Heartbeat ---
            if raw == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            # --- Parse JSON envelope ---
            try:
                envelope = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON",
                }))
                continue

            msg_type = envelope.get("type")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            if msg_type == "refresh":
                handled = await _handle_token_refresh(websocket, envelope)
                if handled:
                    # Update stored payload on successful refresh
                    new_token = envelope.get("token")
                    if new_token:
                        from packages.auth.auth_service import verify_token
                        new_payload = verify_token(new_token)
                        if new_payload is not None:
                            token_payload = new_payload
                            user_id = new_payload.get("sub") or user_id
                    continue

            # --- Token expiry check (chat & notification WS only) ---
            if _is_token_expired(token_payload):
                await websocket.send_text(json.dumps({
                    "type": "token_expired",
                    "message": "Token expired, please refresh",
                }))
                # Do NOT close — give the client a chance to send refresh

            if msg_type == "chat":
                message_text = envelope.get("message", "").strip()
                conversation_id = envelope.get("conversation_id")

                if not message_text:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Missing or empty 'message' field",
                    }))
                    continue

                if len(message_text) > _MAX_CHAT_MESSAGE_LENGTH:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": f"Message too long (max {_MAX_CHAT_MESSAGE_LENGTH} chars)",
                    }))
                    continue

                # Forward to the chat handler (reuses chat.py logic)
                try:
                    await _handle_chat_message(
                        websocket=websocket,
                        user_id=user_id,
                        message=message_text,
                        conversation_id=conversation_id,
                    )
                except Exception as exc:
                    logger.exception("Error handling chat message: %s", exc)
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Internal error processing your message",
                    }))
                continue

            # Unknown message type
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"Unknown message type: {msg_type!r}",
            }))

    except WebSocketDisconnect:
        pass
    finally:
        await chat_manager.disconnect(websocket, user_id)


# ── Chat message handler (reuses chat.py functions) ─────────────────────────


async def _handle_chat_message(
    *,
    websocket: WebSocket,
    user_id: str,
    message: str,
    conversation_id: str | None,
) -> None:
    """Process a single chat message and stream the response back.

    Imports and calls functions from ``chat.py`` without modifying that
    module.  DB operations are wrapped in ``asyncio.to_thread()`` with
    thread-local sessions to avoid sharing sessions across threads.
    """
    from packages.db.repositories.conversation_repo import ConversationRepository
    from packages.db.session import run_async

    manager, chat_manager = _get_managers()

    conv_id = conversation_id
    if conv_id:
        conv = await run_async(ConversationRepository.get_conversation, conv_id)
    else:
        conv = None

    if conv is None:
        conv = await run_async(
            ConversationRepository.create_conversation,
            user_id=user_id, edition="personal",
        )

    await run_async(
        ConversationRepository.add_message,
        conv.id, "user", message,
    )

    await websocket.send_text(json.dumps({"type": "typing"}))

    from apps.api_server.routes.chat import _classify_intent

    classification = await _classify_intent(message)
    intent = classification["intent"]
    extracted = classification.get("extracted", message)

    logger.info(
        "WS Chat intent: %s (confidence=%.2f) user=%s msg=%s",
        intent, classification.get("confidence", 0), user_id, message[:50],
    )

    from apps.api_server.routes.chat import (
        ChatRequest,
        _handle_info,
        _handle_preference,
        _handle_reminder,
        _handle_task,
    )

    body = ChatRequest(
        message=message,
        user_id=user_id,
        edition="personal",
        conversation_id=conv.id,
    )

    if intent == "reminder":
        response = await run_async(_handle_reminder, body, extracted)
    elif intent == "preference":
        from packages.db.session import SessionLocal
        db = SessionLocal()
        try:
            response = await _handle_preference(body, extracted, db)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    elif intent == "task":
        response = await run_async(_handle_task, body, extracted)
    else:
        from packages.db.session import SessionLocal
        db = SessionLocal()
        try:
            response = await _handle_info(body, db)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    await run_async(
        ConversationRepository.add_message,
        conv.id, "assistant", response.reply,
    )

    await websocket.send_text(json.dumps({
        "type": "message",
        "role": "assistant",
        "content": response.reply,
        "conversation_id": conv.id,
    }))

    if response.task_id and response.action == "task_created":
        task_status_msg = {
            "type": "task_status",
            "task_id": response.task_id,
            "status": "pending",
            "goal": message,
        }
        await manager.send_update(response.task_id, task_status_msg)
        await chat_manager.send_to_user(user_id, task_status_msg)


# ── Notification WebSocket Endpoint ──────────────────────────────────────


@router.websocket("/ws/notifications")
async def notification_ws(
    websocket: WebSocket,
    token: str | None = Query(None),
):
    """Dedicated WebSocket for real-time notification push.

    Protocol (client -> server):
    - ``{"type": "ping"}`` or plain text ``"ping"``
      -> server replies ``{"type": "pong"}``
    - ``{"type": "refresh", "token": "<new_jwt>"}``
      -> server validates the new token and replies ``{"type": "refresh_ok"}``
         or ``{"type": "refresh_error", "message": "..."}``.

    Server -> client messages:
    - ``{"type": "notification", "data": {…notification dict}}``
    - ``{"type": "unread_count", "count": N}``
    - ``{"type": "pong"}``
    - ``{"type": "token_expired", "message": "Token expired, please refresh"}``
      — sent when the initial token has expired.

    Auth: pass ``?token=<jwt>`` to identify the user.
    Without a valid token the connection is rejected (code 4001).
    """
    auth_result = await _ws_authenticate(websocket, "notifications", "read")
    if auth_result is None:
        return
    token_payload, user_id = auth_result

    from packages.notification.notification_service import notification_service
    from packages.notification.notification_ws_manager import notification_ws_manager

    await notification_ws_manager.connect(user_id, websocket)

    # Send initial unread count
    unread = notification_service.get_unread_count(user_id)
    await websocket.send_text(json.dumps({
        "type": "unread_count",
        "count": unread,
    }))

    try:
        while True:
            raw = await websocket.receive_text()

            if len(raw) > MAX_MESSAGE_SIZE:
                logger.warning("Notification WS: oversized message (%d bytes) from user %s", len(raw), user_id)
                await websocket.close(code=1009, reason="Message too large")
                break

            # Heartbeat
            if raw == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            try:
                envelope = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON",
                }))
                continue

            if envelope.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            if envelope.get("type") == "refresh":
                handled = await _handle_token_refresh(websocket, envelope)
                if handled:
                    # Update stored payload on successful refresh
                    new_token = envelope.get("token")
                    if new_token:
                        from packages.auth.auth_service import verify_token
                        new_payload = verify_token(new_token)
                        if new_payload is not None:
                            token_payload = new_payload
                    continue

            # --- Token expiry check ---
            if _is_token_expired(token_payload):
                await websocket.send_text(json.dumps({
                    "type": "token_expired",
                    "message": "Token expired, please refresh",
                }))

    except WebSocketDisconnect:
        pass
    finally:
        await notification_ws_manager.disconnect(user_id, websocket)
