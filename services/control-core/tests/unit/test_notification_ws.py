"""Tests for notification WebSocket real-time push — broadcaster, executor user_id, and composable logic."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.notification.notification_service import (
    Notification,
    NotificationService,
)
from packages.notification.ws_broadcaster import NotificationBroadcaster

# ── NotificationBroadcaster message format tests ────────────────────────────


@pytest.mark.unit
class TestNotificationBroadcasterFormat:
    def test_broadcast_sends_correct_envelope_type(self):
        """broadcast_notification must wrap payload in {"type": "notification", "data": ...}."""
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
        payload = mock_manager.send_to_user.call_args[0][1]
        assert payload["type"] == "notification"
        assert "data" in payload

    def test_broadcast_includes_full_notification_in_data(self):
        """The 'data' field must contain all notification fields."""
        broadcaster = NotificationBroadcaster()
        notification = Notification(
            id="n-42", type="task_failed", title="Fail", message="Task X failed",
            data={"task_id": "t-1"}, created_at="2026-05-13T10:00:00+00:00", read=False,
        )

        mock_manager = MagicMock()
        mock_manager.send_to_user = AsyncMock()

        with patch("apps.api_server.routes.ws.chat_manager", mock_manager):
            asyncio.run(broadcaster.broadcast_notification("user-1", notification))

        payload = mock_manager.send_to_user.call_args[0][1]
        assert payload["data"]["id"] == "n-42"
        assert payload["data"]["type"] == "task_failed"
        assert payload["data"]["title"] == "Fail"
        assert payload["data"]["message"] == "Task X failed"
        assert payload["data"]["data"] == {"task_id": "t-1"}
        assert payload["data"]["read"] is False

    def test_broadcast_targets_correct_user(self):
        """The broadcaster must send to the specified user_id, not broadcast to all."""
        broadcaster = NotificationBroadcaster()
        notification = Notification(
            id="n-1", type="info", title="T", message="M",
            data=None, created_at="2026-01-01T00:00:00+00:00", read=False,
        )

        mock_manager = MagicMock()
        mock_manager.send_to_user = AsyncMock()

        with patch("apps.api_server.routes.ws.chat_manager", mock_manager):
            asyncio.run(broadcaster.broadcast_notification("alice", notification))

        # Verify the first positional arg is the target user_id
        call_args = mock_manager.send_to_user.call_args[0]
        assert call_args[0] == "alice"
        # Verify the payload has the right shape
        payload = call_args[1]
        assert payload["type"] == "notification"
        assert payload["data"]["id"] == "n-1"


# ── Executor _notify user_id tests ──────────────────────────────────────────


@pytest.mark.unit
class TestExecutorNotifyUserId:
    def test_executor_uses_task_user_id_on_failure(self):
        """When a task fails, _notify must use the task's user_id, not hardcoded 'default'."""
        from packages.executor.executor_service import _notify

        mock_task = MagicMock()
        mock_task.user_id = "alice"

        mock_task_repo = MagicMock()
        mock_task_repo.get_by_id.return_value = mock_task

        mock_notification = Notification(
            id="n-1", type="task_failed", title="T", message="M",
            data=None, created_at="2026-01-01T00:00:00+00:00", read=False,
        )

        with patch("packages.executor.executor_service.TaskRepository", mock_task_repo), \
             patch("packages.notification.notification_service.notification_service") as mock_svc, \
             patch("packages.notification.ws_broadcaster.notification_broadcaster") as mock_bc:
            mock_svc.create.return_value = mock_notification
            mock_bc.broadcast_notification = AsyncMock()

            asyncio.run(_notify("alice", "task_failed", "Task Failed", "msg"))

        mock_svc.create.assert_called_once()
        call_kwargs = mock_svc.create.call_args[1]
        assert call_kwargs["user_id"] == "alice"

    def test_executor_falls_back_to_default_when_task_missing(self):
        """If TaskRepository.get_by_id returns None, _notify must use 'default'."""
        from packages.executor.executor_service import _notify

        mock_task_repo = MagicMock()
        mock_task_repo.get_by_id.return_value = None

        mock_notification = Notification(
            id="n-2", type="task_completed", title="T", message="M",
            data=None, created_at="2026-01-01T00:00:00+00:00", read=False,
        )

        with patch("packages.executor.executor_service.TaskRepository", mock_task_repo), \
             patch("packages.notification.notification_service.notification_service") as mock_svc, \
             patch("packages.notification.ws_broadcaster.notification_broadcaster") as mock_bc:
            mock_svc.create.return_value = mock_notification
            mock_bc.broadcast_notification = AsyncMock()

            asyncio.run(_notify("default", "task_completed", "Done", "msg"))

        call_kwargs = mock_svc.create.call_args[1]
        assert call_kwargs["user_id"] == "default"


# ── Composable logic tests (unread count management) ────────────────────────


@pytest.mark.unit
class TestUnreadCountLogic:
    def test_notification_service_increment_unread(self):
        """Creating a notification should increase unread count."""
        svc = NotificationService()
        assert svc.get_unread_count("user-1") == 0
        svc.create("user-1", "info", "First", "M")
        assert svc.get_unread_count("user-1") == 1
        svc.create("user-1", "info", "Second", "M")
        assert svc.get_unread_count("user-1") == 2

    def test_notification_service_decrement_via_mark_read(self):
        """Marking a notification as read should decrease unread count by 1."""
        svc = NotificationService()
        n1 = svc.create("user-1", "info", "A", "M")
        svc.create("user-1", "info", "B", "M")
        assert svc.get_unread_count("user-1") == 2

        svc.mark_read("user-1", n1.id)
        assert svc.get_unread_count("user-1") == 1

    def test_notification_service_reset_via_mark_all_read(self):
        """Marking all notifications as read should reset unread count to 0."""
        svc = NotificationService()
        svc.create("user-1", "info", "A", "M")
        svc.create("user-1", "info", "B", "M")
        svc.create("user-1", "info", "C", "M")
        assert svc.get_unread_count("user-1") == 3

        svc.mark_all_read("user-1")
        assert svc.get_unread_count("user-1") == 0

    def test_notification_to_dict_serializes_for_ws(self):
        """Notification.to_dict() must produce JSON-serializable output suitable for WS payload."""
        n = Notification(
            id="n-1", type="task_completed", title="Done",
            message="Task finished", data={"task_id": "t-1"},
            created_at="2026-05-13T10:00:00+00:00", read=False,
        )
        d = n.to_dict()
        # Must be JSON-serializable
        import json
        serialized = json.dumps(d)
        parsed = json.loads(serialized)
        assert parsed["type"] == "task_completed"
        assert parsed["data"]["task_id"] == "t-1"
