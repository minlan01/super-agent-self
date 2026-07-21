"""MCP Client — connects to external MCP tool servers via stdio or HTTP."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from packages.agent_core.version import __version__

logger = logging.getLogger(__name__)

_MCP_RESPONSE_TIMEOUT = 30.0
_MCP_PROCESS_CLEANUP_TIMEOUT = 5
_MCP_HTTP_TIMEOUT = 30
_MCP_HTTP_MAX_CONNECTIONS = 5
_MCP_HTTP_MAX_KEEPALIVE = 2
_MCP_RECONNECT_MAX_RETRIES = 5
_MCP_RECONNECT_BASE_DELAY = 1.0
_MCP_RECONNECT_MAX_DELAY = 60.0


class MCPClient:
    """Connect to external MCP servers, discover and call tools.

    Supports:
    - stdio transport (subprocess)
    - HTTP transport (streamable HTTP)
    """

    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None
        self._http_base_url: str | None = None
        self._http_client: Any | None = None
        self._tools: list[dict[str, Any]] = []
        self._request_id = 0
        self._connected = False
        self._connect_params: dict[str, Any] | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._shutting_down = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect_stdio(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> None:
        """Connect to an MCP server via stdio subprocess."""
        import os
        full_cmd = [command] + (args or [])
        _SENSITIVE_ENV_KEYS = {
            "SECRET_KEY", "DB_PASSWORD", "DATABASE_URL",
            "REDIS_URL", "API_KEY", "TOKEN",
        }
        base_env = {
            k: v for k, v in os.environ.items()
            if not any(s in k.upper() for s in _SENSITIVE_ENV_KEYS)
        }
        proc_env = {**base_env, **(env or {})}

        self._process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=proc_env,
        )
        try:
            await self._initialize()
            await self._discover_tools()
            self._connected = True
            self._connect_params = {"transport": "stdio", "command": command, "args": args, "env": env}
            logger.info("MCP stdio connected: %s %s", command, " ".join(args or []))
        except Exception as e:
            self._connected = False
            logger.warning("MCP stdio connection failed: %s", e)
            if self._process is not None:
                self._process.kill()
                self._process = None
            raise

    async def connect_http(self, url: str) -> None:
        """Connect to an MCP server via HTTP."""
        from packages.policy.ssrf_guard import validate_url
        safe, reason = validate_url(url)
        if not safe:
            raise ValueError(f"MCP HTTP URL blocked by SSRF guard: {reason}")
        self._http_base_url = url
        try:
            await self._initialize()
            await self._discover_tools()
            self._connected = True
            self._connect_params = {"transport": "http", "url": url}
            logger.info("MCP HTTP connected: %s", url)
        except Exception as e:
            self._connected = False
            self._http_base_url = None
            logger.warning("MCP HTTP connection failed: %s", e)
            raise

    async def _send_request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC request and return the response."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        if self._process is not None:
            response = await self._send_stdio(request)
        elif self._http_base_url is not None:
            response = await self._send_http(request)
        else:
            raise RuntimeError("MCP client not connected")

        # Validate JSON-RPC response structure
        if "error" in response:
            error = response["error"]
            code = error.get("code", -1)
            message = error.get("message", "Unknown JSON-RPC error")
            raise RuntimeError(f"MCP JSON-RPC error for '{method}' (code={code}): {message}")

        return response

    async def _send_stdio(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send request via stdio to subprocess."""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("MCP stdio process not available")

        line = json.dumps(request) + "\n"
        self._process.stdin.write(line.encode())
        await self._process.stdin.drain()

        if self._process.stdout is None:
            raise RuntimeError("MCP stdout not available")

        try:
            response_line = await asyncio.wait_for(self._process.stdout.readline(), timeout=_MCP_RESPONSE_TIMEOUT)
        except TimeoutError:
            self._mark_disconnected("MCP server response timed out (30s)")
            raise RuntimeError("MCP server response timed out (30s)")

        if not response_line:
            self._mark_disconnected("MCP server closed connection")
            raise RuntimeError("MCP server closed connection")

        return json.loads(response_line.decode())

    async def _send_http(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send request via HTTP (reuses connection pool)."""
        import httpx

        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                base_url=self._http_base_url,
                timeout=_MCP_HTTP_TIMEOUT,
                limits=httpx.Limits(max_connections=_MCP_HTTP_MAX_CONNECTIONS, max_keepalive_connections=_MCP_HTTP_MAX_KEEPALIVE),
            )
        resp = await self._http_client.post("/message", json=request)
        resp.raise_for_status()
        return resp.json()

    async def _initialize(self) -> None:
        """Send MCP initialize handshake."""
        response = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "myself-agent", "version": __version__},
        })
        logger.debug("MCP initialize response: %s", response)

    async def _discover_tools(self) -> None:
        """Discover available tools from the MCP server."""
        response = await self._send_request("tools/list")
        self._tools = response.get("result", {}).get("tools", [])
        logger.info("MCP discovered %d tools", len(self._tools))

    async def list_tools(self) -> list[dict[str, Any]]:
        """Get the list of tools provided by the MCP server."""
        return list(self._tools)

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call an MCP tool by name with the given arguments."""
        response = await self._send_request("tools/call", {
            "name": name,
            "arguments": args,
        })

        # JSON-RPC error is already checked in _send_request
        result = response.get("result", {})
        if "content" in result:
            # MCP format: list of content items
            items = result["content"]
            if len(items) == 1:
                return items[0].get("text", items[0])
            return [item.get("text", item) for item in items]
        return result

    async def _mark_disconnected(self, reason: str) -> None:
        """Mark client as disconnected and schedule reconnection if possible."""
        self._connected = False
        logger.warning("MCP disconnected: %s", reason)

        if self._process is not None:
            try:
                self._process.kill()
                await asyncio.wait_for(self._process.wait(), timeout=_MCP_PROCESS_CLEANUP_TIMEOUT)
            except Exception:
                logger.debug("Failed to kill MCP process on disconnect", exc_info=True)
            self._process = None

        if self._connect_params and not self._shutting_down and self._reconnect_task is None:
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Attempt reconnection with exponential backoff."""
        delay = _MCP_RECONNECT_BASE_DELAY
        for attempt in range(1, _MCP_RECONNECT_MAX_RETRIES + 1):
            if self._shutting_down or self._connected:
                break
            logger.info("MCP reconnect attempt %d/%d in %.1fs", attempt, _MCP_RECONNECT_MAX_RETRIES, delay)
            await asyncio.sleep(delay)
            if self._shutting_down or self._connected:
                break
            try:
                params = self._connect_params
                if params is None:
                    break
                if params["transport"] == "stdio":
                    await self.connect_stdio(params["command"], params.get("args"), params.get("env"))
                elif params["transport"] == "http":
                    await self.connect_http(params["url"])
                logger.info("MCP reconnected successfully on attempt %d", attempt)
                break
            except Exception as e:
                logger.warning("MCP reconnect attempt %d failed: %s", attempt, e)
                delay = min(delay * 2, _MCP_RECONNECT_MAX_DELAY)
        self._reconnect_task = None

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        self._shutting_down = True

        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=_MCP_PROCESS_CLEANUP_TIMEOUT)
            except Exception as e:
                logger.warning("Failed to terminate MCP process gracefully, forcing kill: %s", e)
                self._process.kill()
            self._process = None

        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

        self._http_base_url = None
        self._connected = False
        self._connect_params = None
        self._tools = []
        logger.info("MCP client disconnected")
