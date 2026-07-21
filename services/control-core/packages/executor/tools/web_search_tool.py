"""Web search tool — multi-backend web search."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any

from packages.policy.unified_registry import tool_registry

from .base import ExecutionContext, ToolBase, ToolResult

logger = logging.getLogger(__name__)

_websearch_client: Any | None = None
_websearch_client_lock = threading.Lock()


async def _get_websearch_client() -> Any:
    import httpx
    global _websearch_client
    with _websearch_client_lock:
        if _websearch_client is None or _websearch_client.is_closed:
            _websearch_client = httpx.AsyncClient(
                timeout=15,
                limits=httpx.Limits(max_connections=3, max_keepalive_connections=1),
            )
    return _websearch_client


@tool_registry.register(
    category="web",
    risk_level="low",
    emoji="🔍",
    params_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (1-10)", "default": 5},
        },
        "additionalProperties": False,
    },
)
class WebSearch(ToolBase):
    """Search the web for information using multiple backends."""

    name = "web.search"
    description = "Search the web for information"

    def __init__(self):
        self._engines = self._detect_engines()

    @staticmethod
    def _detect_engines() -> list[str]:
        """Detect available search engines by checking env vars / deps."""
        engines: list[str] = []
        if os.environ.get("BRAVE_API_KEY"):
            engines.append("brave")
        engines.append("duckduckgo")  # Free, no key required
        return engines

    async def _search_duckduckgo(self, query: str, max_results: int) -> list[dict]:
        try:
            from duckduckgo_search import DDGS  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("duckduckgo-search not installed, skipping")
            return []

        results = []
        try:
            def _do_search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=max_results))

            ddg_results = await asyncio.to_thread(_do_search)
            for r in ddg_results:
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                    "engine": "duckduckgo",
                })
        except Exception as exc:
            logger.warning("DuckDuckGo search failed: %s", exc)
        return results

    async def _search_brave(self, query: str, max_results: int) -> list[dict]:
        """Search via Brave Search API."""
        import httpx

        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return []

        results = []
        try:
            client = await _get_websearch_client()
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                    "engine": "brave",
                })
        except Exception as exc:
            logger.warning("Brave search failed: %s", exc)
        return results

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        query: str = args.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="query is required")

        max_results = min(int(args.get("max_results", 5)), 10)

        # Try each engine in order
        for engine_name in self._engines:
            if engine_name == "duckduckgo":
                results = await self._search_duckduckgo(query, max_results)
            elif engine_name == "brave":
                results = await self._search_brave(query, max_results)
            else:
                continue

            if results:
                return ToolResult(
                    success=True,
                    output={"query": query, "engine": engine_name, "results": results},
                )

        return ToolResult(
            success=False,
            error=f"No results found for query: {query}",
        )
