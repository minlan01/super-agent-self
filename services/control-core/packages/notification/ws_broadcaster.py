"""Broadcast notifications over WebSocket to connected users."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.notification.notification_service import Notification

logger = logging.getLogger(__name__)


class NotificationBroadcaster:
    """Sends real-time notification payloads to user WebSocket connections.

    Pushes to **both** the legacy ``ChatConnectionManager`` (``/ws/chat``)
    and the dedicated ``NotificationWSManager`` (``/ws/notifications``).
    """

    async def broadcast_notification(self, user_id: str, notification: Notification) -> None:
        """Push a notification to all of *user_id*'s WebSocket connections.

        Message format: ``{"type": "notification", "data": {…notification dict}}``

        Failures are logged but never raised — broadcasting is fire-and-forget.
        """
        payload = {
            "type": "notification",
            "data": notification.to_dict(),
        }

        # Legacy: /ws/chat consumers (backward compat)
        try:
            from apps.api_server.routes.ws import chat_manager
            await chat_manager.send_to_user(user_id, payload)
        except Exception:
            logger.exception("WebSocket broadcast error (legacy /ws/chat) for user %s", user_id)

        # Dedicated: /ws/notifications consumers
        try:
            from packages.notification.notification_ws_manager import notification_ws_manager
            await notification_ws_manager.send_to_user(user_id, payload)
            logger.debug("Notification %s broadcast to user %s", notification.id, user_id)
        except Exception:
            logger.exception("WebSocket broadcast error (/ws/notifications) for user %s", user_id)


# Module-level singleton
notification_broadcaster = NotificationBroadcaster()
