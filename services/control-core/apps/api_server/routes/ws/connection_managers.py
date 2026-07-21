"""Generic connection managers for WebSocket endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

MAX_CONNECTIONS_PER_KEY = 20
MAX_TOTAL_CONNECTIONS = 500


class ConnectionManager:
    """Manages active WebSocket connections grouped by an arbitrary key.

    Used for both task and chat endpoints.  Each key (task_id, user_id, etc.)
    maps to a list of active ``WebSocket`` instances.

    Enforces connection limits to prevent resource exhaustion.
    All mutations and broadcasts are serialized via an asyncio.Lock to
    prevent race conditions (e.g. concurrent connect/disconnect during
    broadcast iteration).
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, key: str) -> None:
        """Accept *websocket* and register it under *key*.

        Limit checks and registration share a single lock to eliminate the
        TOCTOU race where two concurrent connects could both pass the check
        and both register.  ``accept()`` is performed outside the lock; if
        a limit is exceeded after the accept, the socket is closed cleanly.
        """
        await websocket.accept()
        async with self._lock:
            total = sum(len(conns) for conns in self._connections.values())
            if total >= MAX_TOTAL_CONNECTIONS:
                logger.warning("WebSocket rejected: global limit %d reached", MAX_TOTAL_CONNECTIONS)
                try:
                    await websocket.close(code=1013, reason="Server overloaded")
                except Exception:
                    logger.debug("Failed to close overloaded WS", exc_info=True)
                return

            per_key = len(self._connections.get(key, []))
            if per_key >= MAX_CONNECTIONS_PER_KEY:
                logger.warning(
                    "WebSocket rejected: per-key limit %d reached for key %s",
                    MAX_CONNECTIONS_PER_KEY, key,
                )
                try:
                    await websocket.close(code=1013, reason="Too many connections")
                except Exception:
                    logger.debug("Failed to close per-key-limit WS", exc_info=True)
                return

            if key not in self._connections:
                self._connections[key] = []
            self._connections[key].append(websocket)
            logger.info("WebSocket connected for key %s (total=%d)", key, total + 1)

    async def disconnect(self, websocket: WebSocket, key: str) -> None:
        """Remove *websocket* from the connection list for *key*.

        Cleans up the key entry when the list becomes empty.
        """
        async with self._lock:
            if key in self._connections:
                self._connections[key] = [
                    ws for ws in self._connections[key] if ws is not websocket
                ]
                if not self._connections[key]:
                    del self._connections[key]
        logger.info("WebSocket disconnected for key %s", key)

    async def broadcast(self, message: dict[str, Any], key: str | None = None) -> None:
        """Send *message* to connections concurrently via ``asyncio.gather``.

        If *key* is given, only connections registered under that key receive
        the message.  Otherwise the message is sent to every connection.
        """
        text = json.dumps(message, ensure_ascii=False)

        async with self._lock:
            if key is not None:
                pairs: list[tuple[str, WebSocket]] = [
                    (key, ws) for ws in self._connections.get(key, [])
                ]
            else:
                pairs = [
                    (k, ws)
                    for k, conns in self._connections.items()
                    for ws in conns
                ]

        if not pairs:
            return

        results = await asyncio.gather(
            *(ws.send_text(text) for _k, ws in pairs),
            return_exceptions=True,
        )
        disconnected: list[tuple[WebSocket, str]] = []
        for (group_key, ws), res in zip(pairs, results):
            if isinstance(res, Exception):
                logger.warning("WebSocket send failed for key %s: %s", group_key, res)
                disconnected.append((ws, group_key))

        for ws, group_key in disconnected:
            await self.disconnect(ws, group_key)

    async def send_personal(self, message: dict[str, Any], websocket: WebSocket) -> None:
        """Send *message* to a single *websocket*."""
        text = json.dumps(message, ensure_ascii=False)
        await websocket.send_text(text)

    async def send_update(self, key: str, data: dict[str, Any]) -> None:
        await self.broadcast(data, key=key)

    async def send_to_user(self, key: str, data: dict[str, Any]) -> None:
        await self.broadcast(data, key=key)

    @property
    def active_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())

    @property
    def active_users(self) -> int:
        return len(self._connections)


manager = ConnectionManager()
chat_manager = ConnectionManager()

ChatConnectionManager = ConnectionManager
