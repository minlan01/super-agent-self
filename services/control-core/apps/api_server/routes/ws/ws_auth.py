"""Shared WebSocket authentication helpers."""

from __future__ import annotations

import json
import time

from fastapi import WebSocket


async def _check_ws_permission(websocket: WebSocket, resource: str, action: str):
    """Validate WS token and check RBAC permission.

    Returns the authenticated user on success, or closes the websocket
    and returns None on failure.

    When ``REQUIRE_AUTH=false`` (the default), skips DB/RBAC checks and
    returns a synthetic admin user for backward compatibility.
    """
    from packages.config import get_settings

    settings = get_settings()

    # Auth disabled — return a synthetic admin (backward compatible)
    if not settings.security.require_auth:
        from packages.db.models import User, UserRole

        return User(
            id="default-dev-user",
            username="dev_user",
            email=None,
            hashed_password="",
            role=UserRole.USER,
            is_active=True,
        )

    from packages.db.session import SessionLocal

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return None

    from packages.auth.auth_service import verify_token

    payload = verify_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return None

    db = SessionLocal()
    try:
        from packages.db.repositories.auth_repo import AuthRepository

        user = AuthRepository.get_by_id(db, payload.get("sub"))
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return None

        from packages.auth.rbac import get_rbac_service

        rbac = get_rbac_service()
        if rbac.rbac_enabled and not (
            rbac.legacy_admin_bypass and user.role.value == "admin"
        ):
            if not rbac.check_permission(db, user.id, resource, action):
                await websocket.close(
                    code=4003,
                    reason=f"Permission denied: {resource}:{action}",
                )
                return None
        return user
    finally:
        db.close()


async def _handle_token_refresh(websocket: WebSocket, envelope: dict) -> bool:
    """Handle a ``{"type": "refresh", "token": "<jwt>"}`` message.

    Returns True if the refresh was handled (regardless of success/failure).
    The caller should ``continue`` the loop on True.
    """
    new_token = envelope.get("token")
    if not new_token:
        await websocket.send_text(json.dumps({
            "type": "refresh_error",
            "message": "Missing 'token' field",
        }))
        return True

    from packages.auth.auth_service import verify_token

    payload = verify_token(new_token)
    if payload is None:
        await websocket.send_text(json.dumps({
            "type": "refresh_error",
            "message": "Invalid or expired token",
        }))
        return True

    websocket.state.token_payload = payload
    await websocket.send_text(json.dumps({"type": "refresh_ok"}))
    return True


def _is_token_expired(payload: dict | None) -> bool:
    """Check whether the stored token payload has expired.

    Returns False if *payload* is None (no auth / anonymous).
    """
    if payload is None:
        return False
    exp = payload.get("exp")
    if exp is None:
        return False
    return time.time() > exp


async def _resolve_chat_user(websocket: WebSocket) -> str:
    """Return the authenticated user_id or ``"default"``."""
    token = websocket.query_params.get("token")
    if token:
        from packages.auth.auth_service import verify_token

        payload = verify_token(token)
        if payload is None:
            return "default"
        user_id = payload.get("sub")
        return user_id or "default"
    return "default"
