"""Tests for MCP client and tool adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.executor.tools.base import ExecutionContext
from packages.mcp.mcp_client import MCPClient
from packages.mcp.mcp_tool_adapter import MCPToolAdapter


@pytest.fixture
def context(tmp_path):
    return ExecutionContext(
        task_id="t1",
        step_id="s1",
        edition="enterprise",
        workspace_root=str(tmp_path),
    )


# ── MCPClient ──────────────────────────────────────────────────────────────


class TestMCPClient:
    def test_initial_state(self):
        client = MCPClient()
        assert not client.connected
        assert client._tools == []

    @pytest.mark.asyncio
    async def test_list_tools_empty(self):
        client = MCPClient()
        client._connected = True
        client._tools = []
        tools = await client.list_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_list_tools_with_tools(self):
        client = MCPClient()
        client._tools = [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
        ]
        tools = await client.list_tools()
        assert len(tools) == 2
        assert tools[0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_call_tool(self):
        client = MCPClient()
        client._connected = True

        mock_response = {
            "result": {
                "content": [{"type": "text", "text": "file contents here"}]
            }
        }
        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            result = await client.call_tool("read_file", {"path": "/tmp/test.txt"})
            assert result == "file contents here"

    @pytest.mark.asyncio
    async def test_call_tool_multiple_content(self):
        client = MCPClient()
        client._connected = True

        mock_response = {
            "result": {
                "content": [
                    {"type": "text", "text": "part1"},
                    {"type": "text", "text": "part2"},
                ]
            }
        }
        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response
            result = await client.call_tool("multi", {})
            assert result == ["part1", "part2"]

    @pytest.mark.asyncio
    async def test_disconnect(self):
        client = MCPClient()
        client._connected = True
        client._tools = [{"name": "x"}]
        await client.disconnect()
        assert not client.connected
        assert client._tools == []


# ── MCPToolAdapter ─────────────────────────────────────────────────────────


class TestMCPToolAdapter:
    def test_adapter_properties(self):
        mock_client = MagicMock()
        tool_info = {
            "name": "fs.read",
            "description": "Read a file from filesystem",
            "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
        adapter = MCPToolAdapter(mock_client, tool_info)
        assert adapter.name == "fs.read"
        assert adapter.description == "Read a file from filesystem"

    @pytest.mark.asyncio
    async def test_execute_success(self, context):
        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(return_value="file content")
        tool_info = {"name": "fs.read", "description": "Read file"}
        adapter = MCPToolAdapter(mock_client, tool_info)

        result = await adapter.execute({"path": "/tmp/test.txt"}, context)
        assert result.success
        assert result.output == "file content"

    @pytest.mark.asyncio
    async def test_execute_failure(self, context):
        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))
        tool_info = {"name": "fs.read", "description": "Read file"}
        adapter = MCPToolAdapter(mock_client, tool_info)

        result = await adapter.execute({"path": "/tmp/test.txt"}, context)
        assert not result.success
        assert "connection lost" in result.error
