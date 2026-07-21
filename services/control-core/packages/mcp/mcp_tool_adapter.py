"""MCP Tool Adapter — wraps MCP tools as ToolBase instances for the ToolRunner."""

from __future__ import annotations

import logging
from typing import Any

from packages.executor.tools.base import ExecutionContext, ToolBase, ToolResult

logger = logging.getLogger(__name__)


class MCPToolAdapter(ToolBase):
    """Adapts an MCP tool to the ToolBase interface.

    Allows MCP tools to be registered in the ToolRunner alongside native tools.
    """

    def __init__(self, mcp_client: Any, tool_info: dict[str, Any]):
        self.name: str = tool_info.get("name", "mcp.unknown")
        self.description: str = tool_info.get("description", "")
        self._client = mcp_client
        self._input_schema: dict = tool_info.get("inputSchema", {})

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        """Execute the MCP tool via the MCP client."""
        try:
            result = await self._client.call_tool(self.name, args)
            return ToolResult(success=True, output=result)
        except Exception as exc:
            logger.error("MCP tool '%s' failed: %s", self.name, exc)
            return ToolResult(success=False, error=str(exc))


def register_mcp_tools(tool_runner: Any, mcp_client: Any) -> list[MCPToolAdapter]:
    """Discover and register all tools from an MCP client into a ToolRunner.

    Returns the list of registered adapters.
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                tools = pool.submit(asyncio.run, mcp_client.list_tools()).result()
        else:
            tools = loop.run_until_complete(mcp_client.list_tools())
    except RuntimeError:
        tools = asyncio.run(mcp_client.list_tools())
    adapters = []
    for tool_info in tools:
        adapter = MCPToolAdapter(mcp_client, tool_info)
        tool_runner.register(adapter)
        adapters.append(adapter)
        logger.info("Registered MCP tool: %s", adapter.name)
    return adapters


async def register_mcp_tools_async(tool_runner: Any, mcp_client: Any) -> list[MCPToolAdapter]:
    """Async version of register_mcp_tools."""
    tools = await mcp_client.list_tools()
    adapters = []
    for tool_info in tools:
        adapter = MCPToolAdapter(mcp_client, tool_info)
        tool_runner.register(adapter)
        adapters.append(adapter)
        logger.info("Registered MCP tool: %s", adapter.name)
    return adapters
