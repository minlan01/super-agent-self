"""Dedicated WebSocket manager for real-time notification push.

Separate from ``ChatConnectionManager`` so that notification consumers
can subscribe without participating in chat.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_MAX_CONNECTIONS_PER_USER = 5
_MAX_TOTAL_CONNECTIONS = 500


class NotificationWSManager:
    """Per-user WebSocket connection manager for the ``/ws/notifications`` endpoint.

    Thread-safe via an ``asyncio.Lock`` that serialises mutations to the
    internal connection map.  Supports heartbeat (ping/pong) and three
    outbound message types:

    * ``{"type": "notification", "data": ...}``
    * ``{"type": "unread_count", "count": N}``
    * ``{"type": "pong"}``
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    # ── Connection lifecycle ──────────────────────────────────────────────

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        """Accept *ws* and register it under *user_id*."""
        await ws.accept()
        async with self._lock:
            total = sum(len(conns) for conns in self._connections.values())
            if total >= _MAX_TOTAL_CONNECTIONS:
                try:
                    await ws.close(code=1013, reason="Server overloaded")
                except Exception:
                    logger.debug("Failed to close overloaded notification WS", exc_info=True)
                logger.warning("Notification WS: total connection limit reached (%d)", _MAX_TOTAL_CONNECTIONS)
                return
            per_user = len(self._connections.get(user_id, []))
            if per_user >= _MAX_CONNECTIONS_PER_USER:
                try:
                    await ws.close(code=1013, reason="Too many connections")
                except Exception:
                    logger.debug("Failed to close per-user-limit notification WS", exc_info=True)
                logger.warning("Notification WS: per-user limit reached for %s (%d)", user_id, _MAX_CONNECTIONS_PER_USER)
                return
            if user_id not in self._connections:
                self._connections[user_id] = []
            self._connections[user_id].append(ws)
        logger.info("Notification WS connected for user %s", user_id)

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        """Remove *ws* from *user_id*'s connection list."""
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id] = [
                    w for w in self._connections[user_id] if w is not ws
                ]
                if not self._connections[user_id]:
                    del self._connections[user_id]
        logger.info("Notification WS disconnected for user %s", user_id)

    # ── Sending ───────────────────────────────────────────────────────────

    async def send_to_user(self, user_id: str, data: dict[str, Any]) -> None:
        """Send *data* to every active connection owned by *user_id*.

        Sends are issued concurrently via ``asyncio.gather`` so a single slow
        client cannot stall the others.  Dead sockets are automatically pruned.
        """
        async with self._lock:
            connections = list(self._connections.get(user_id, []))
        if not connections:
            return

        message = json.dumps(data, ensure_ascii=False)
        results = await asyncio.gather(
            *(ws.send_text(message) for ws in connections),
            return_exceptions=True,
        )
        disconnected = [
            ws for ws, res in zip(connections, results) if isinstance(res, Exception)
        ]
        for res in results:
            if isinstance(res, Exception):
                logger.warning("Notification WS send failed: %s", res)
        for ws in disconnected:
            await self.disconnect(user_id, ws)

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send *data* to every connected user (concurrently)."""
        async with self._lock:
            snapshot: list[tuple[str, WebSocket]] = [
                (uid, ws)
                for uid, conns in self._connections.items()
                for ws in conns
            ]
        if not snapshot:
            return

        message = json.dumps(data, ensure_ascii=False)
        results = await asyncio.gather(
            *(ws.send_text(message) for _uid, ws in snapshot),
            return_exceptions=True,
        )
        disconnected: list[tuple[WebSocket, str]] = []
        for (uid, ws), res in zip(snapshot, results):
            if isinstance(res, Exception):
                logger.warning("Notification WS broadcast send failed: %s", res)
                disconnected.append((ws, uid))
        for ws, user_id in disconnected:
            await self.disconnect(user_id, ws)

    # ── Helpers ───────────────────────────────────────────────────────────

    def get_active_count(self) -> int:
        """Return total number of active connections across all users."""
        return sum(len(conns) for conns in self._connections.values())

    @property
    def active_users(self) -> int:
        return len(self._connections)


# Module-level singleton
notification_ws_manager = NotificationWSManager()
