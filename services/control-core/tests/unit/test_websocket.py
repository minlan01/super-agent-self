"""Tests for WebSocket connection manager."""

import json
from unittest.mock import AsyncMock

from apps.api_server.routes.ws import ConnectionManager


class TestConnectionManager:
    def test_connect_adds_connection(self):
        manager = ConnectionManager()
        ws = AsyncMock()
        # Simulate accept
        import asyncio

        async def _test():
            await manager.connect(ws, "task-1")
            assert "task-1" in manager._connections
            assert len(manager._connections["task-1"]) == 1
            assert manager.active_connections == 1

        asyncio.run(_test())

    def test_disconnect_removes_connection(self):
        manager = ConnectionManager()
        ws = AsyncMock()

        import asyncio

        async def _test():
            await manager.connect(ws, "task-1")
            await manager.disconnect(ws, "task-1")
            assert "task-1" not in manager._connections
            assert manager.active_connections == 0

        asyncio.run(_test())

    def test_disconnect_last_removes_key(self):
        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        import asyncio

        async def _test():
            await manager.connect(ws1, "task-1")
            await manager.connect(ws2, "task-1")
            assert len(manager._connections["task-1"]) == 2

            await manager.disconnect(ws1, "task-1")
            assert len(manager._connections["task-1"]) == 1

            await manager.disconnect(ws2, "task-1")
            assert "task-1" not in manager._connections

        asyncio.run(_test())

    def test_send_update_broadcasts(self):
        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        import asyncio

        async def _test():
            await manager.connect(ws1, "task-1")
            await manager.connect(ws2, "task-1")
            await manager.send_update("task-1", {"status": "completed"})

            expected = json.dumps({"status": "completed"})
            ws1.send_text.assert_called_once_with(expected)
            ws2.send_text.assert_called_once_with(expected)

        asyncio.run(_test())

    def test_send_update_no_connections(self):
        manager = ConnectionManager()

        import asyncio

        async def _test():
            # Should not raise
            await manager.send_update("task-999", {"status": "ok"})

        asyncio.run(_test())

    def test_send_update_removes_dead_connections(self):
        manager = ConnectionManager()
        ws = AsyncMock()
        ws.send_text.side_effect = Exception("Connection closed")

        import asyncio

        async def _test():
            await manager.connect(ws, "task-1")
            await manager.send_update("task-1", {"status": "ok"})
            # Dead connection should be removed
            assert manager.active_connections == 0

        asyncio.run(_test())

    def test_active_connections_count(self):
        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        import asyncio

        async def _test():
            await manager.connect(ws1, "task-1")
            await manager.connect(ws2, "task-2")
            assert manager.active_connections == 2

        asyncio.run(_test())
