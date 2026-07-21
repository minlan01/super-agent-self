"""Tests for task WebSocket event broadcasting via ConnectionManager."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from apps.api_server.routes.ws import ConnectionManager

# ── ConnectionManager tests ──────────────────────────────────────────────────


class TestConnectionManagerConnectDisconnect:
    """Tests for connect/disconnect lifecycle of the task ConnectionManager."""

    def test_connect_registers_websocket(self):
        mgr = ConnectionManager()
        ws = AsyncMock()

        async def _test():
            await mgr.connect(ws, "task-1")
            assert "task-1" in mgr._connections
            assert ws in mgr._connections["task-1"]
            assert mgr.active_connections == 1

        asyncio.run(_test())

    def test_disconnect_removes_websocket(self):
        mgr = ConnectionManager()
        ws = AsyncMock()

        async def _test():
            await mgr.connect(ws, "task-1")
            await mgr.disconnect(ws, "task-1")
            assert "task-1" not in mgr._connections
            assert mgr.active_connections == 0

        asyncio.run(_test())

    def test_cleanup_on_disconnect_empty_task(self):
        """When the last watcher disconnects, the task key is removed entirely."""
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        async def _test():
            await mgr.connect(ws1, "task-1")
            await mgr.connect(ws2, "task-1")
            assert len(mgr._connections["task-1"]) == 2

            await mgr.disconnect(ws1, "task-1")
            assert len(mgr._connections["task-1"]) == 1

            await mgr.disconnect(ws2, "task-1")
            assert "task-1" not in mgr._connections

        asyncio.run(_test())


# ── send_update (broadcast) tests ────────────────────────────────────────────


class TestConnectionManagerBroadcast:
    """Tests for send_update broadcasting to multiple watchers."""

    def test_send_update_to_multiple_watchers(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        async def _test():
            await mgr.connect(ws1, "task-1")
            await mgr.connect(ws2, "task-1")

            payload = {"event": "step_completed", "step_id": "s-1", "tool": "bash", "success": True}
            await mgr.send_update("task-1", payload)

            expected = json.dumps(payload, ensure_ascii=False)
            ws1.send_text.assert_awaited_once_with(expected)
            ws2.send_text.assert_awaited_once_with(expected)

        asyncio.run(_test())

    def test_send_update_no_watchers_is_noop(self):
        mgr = ConnectionManager()

        async def _test():
            # Should not raise
            await mgr.send_update("task-unknown", {"event": "step_completed"})
            assert mgr.active_connections == 0

        asyncio.run(_test())

    def test_send_update_prunes_dead_connections(self):
        """Connections that raise on send are automatically removed."""
        mgr = ConnectionManager()
        ws_alive = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = RuntimeError("connection lost")

        async def _test():
            await mgr.connect(ws_alive, "task-1")
            await mgr.connect(ws_dead, "task-1")

            await mgr.send_update("task-1", {"event": "step_failed", "step_id": "s-2"})

            # Dead connection should have been pruned
            assert len(mgr._connections["task-1"]) == 1
            assert ws_alive in mgr._connections["task-1"]

        asyncio.run(_test())


# ── Event format tests ───────────────────────────────────────────────────────


class TestEventFormats:
    """Verify the event payloads sent by _ws_broadcast match expected schema."""

    @pytest.fixture()
    def mgr(self):
        return ConnectionManager()

    def test_step_rejected_event_format(self, mgr: ConnectionManager):
        ws = AsyncMock()

        async def _test():
            await mgr.connect(ws, "task-1")

            payload = {
                "event": "step_rejected",
                "step_id": "step-abc",
                "tool": "bash",
                "reason": "dangerous command detected",
            }
            await mgr.send_update("task-1", payload)

            raw = ws.send_text.call_args[0][0]
            data = json.loads(raw)
            assert data["event"] == "step_rejected"
            assert data["step_id"] == "step-abc"
            assert data["tool"] == "bash"
            assert data["reason"] == "dangerous command detected"

        asyncio.run(_test())

    def test_step_completed_event_format(self, mgr: ConnectionManager):
        ws = AsyncMock()

        async def _test():
            await mgr.connect(ws, "task-1")

            payload = {
                "event": "step_completed",
                "step_id": "step-123",
                "tool": "file_read",
                "success": True,
            }
            await mgr.send_update("task-1", payload)

            raw = ws.send_text.call_args[0][0]
            data = json.loads(raw)
            assert data["event"] == "step_completed"
            assert data["step_id"] == "step-123"
            assert data["tool"] == "file_read"
            assert data["success"] is True

        asyncio.run(_test())

    def test_task_completed_event_format(self, mgr: ConnectionManager):
        ws = AsyncMock()

        async def _test():
            await mgr.connect(ws, "task-1")

            payload = {
                "event": "task_completed",
                "steps_completed": 5,
            }
            await mgr.send_update("task-1", payload)

            raw = ws.send_text.call_args[0][0]
            data = json.loads(raw)
            assert data["event"] == "task_completed"
            assert data["steps_completed"] == 5

        asyncio.run(_test())

    def test_task_failed_event_format(self, mgr: ConnectionManager):
        ws = AsyncMock()

        async def _test():
            await mgr.connect(ws, "task-1")

            payload = {
                "event": "task_failed",
                "steps_completed": 3,
            }
            await mgr.send_update("task-1", payload)

            raw = ws.send_text.call_args[0][0]
            data = json.loads(raw)
            assert data["event"] == "task_failed"
            assert data["steps_completed"] == 3

        asyncio.run(_test())
