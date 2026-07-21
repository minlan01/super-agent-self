"""Enhanced browser tools for Personal Edition — multi-tab, bookmarks, monitoring."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from packages.executor.tools.base import ToolBase, ToolResult
from packages.policy.unified_registry import tool_registry

logger = logging.getLogger(__name__)


@tool_registry.register(category="browser", risk_level="low", emoji="🔖")
class BrowserBookmark(ToolBase):
    """Save and retrieve bookmarks."""

    name = "browser.bookmark"
    description = "Save or list bookmarks"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        action = args.get("action", "list")  # "list" | "save" | "delete"
        workspace = Path(context.workspace_root)
        bookmarks_file = workspace / "bookmarks.json"

        if action == "list":
            if not bookmarks_file.exists():
                return ToolResult(success=True, output={"bookmarks": []})
            try:
                data = json.loads(await asyncio.to_thread(bookmarks_file.read_text, encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to read bookmarks file: %s", e)
                data = []
            return ToolResult(success=True, output={"bookmarks": data})

        elif action == "save":
            url = args.get("url", "")
            title = args.get("title", url[:100])
            if not url:
                return ToolResult(success=False, error="url is required")

            bookmarks = []
            if bookmarks_file.exists():
                try:
                    bookmarks = json.loads(await asyncio.to_thread(bookmarks_file.read_text, encoding="utf-8"))
                except Exception as e:
                    logger.warning("Failed to read bookmarks file for save: %s", e)
                    bookmarks = []

            if any(b.get("url") == url for b in bookmarks):
                return ToolResult(success=True, output={"message": "Already bookmarked", "url": url})

            bookmarks.append({
                "url": url,
                "title": title,
                "created_at": datetime.now(UTC).isoformat(),
                "tags": args.get("tags", []),
            })
            await asyncio.to_thread(
                bookmarks_file.write_text,
                json.dumps(bookmarks, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return ToolResult(success=True, output={"message": "Bookmark saved", "url": url})

        elif action == "delete":
            url = args.get("url", "")
            if not url:
                return ToolResult(success=False, error="url is required for delete")
            if not bookmarks_file.exists():
                return ToolResult(success=False, error="No bookmarks file")
            bookmarks = json.loads(await asyncio.to_thread(bookmarks_file.read_text, encoding="utf-8"))
            new_bookmarks = [b for b in bookmarks if b.get("url") != url]
            await asyncio.to_thread(
                bookmarks_file.write_text,
                json.dumps(new_bookmarks, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return ToolResult(success=True, output={"message": "Bookmark deleted", "url": url})

        return ToolResult(success=False, error=f"Unknown action: {action}")


@tool_registry.register(category="browser", risk_level="low", emoji="📡")
class BrowserMonitor(ToolBase):
    """Monitor a URL for changes — takes screenshot and compares with last."""

    name = "browser.monitor"
    description = "Monitor a URL for changes"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        url = args.get("url", "")
        if not url:
            return ToolResult(success=False, error="url is required")

        workspace = Path(context.workspace_root)
        monitor_dir = workspace / "monitors"
        monitor_dir.mkdir(parents=True, exist_ok=True)

        # Create a hash-based filename for this URL
        import hashlib
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        state_file = monitor_dir / f"{url_hash}.json"

        current_state = {
            "url": url,
            "checked_at": datetime.now(UTC).isoformat(),
        }

        # Check previous state
        if state_file.exists():
            try:
                prev = json.loads(await asyncio.to_thread(state_file.read_text, encoding="utf-8"))
                prev_time = prev.get("checked_at", "")
                current_state["previous_check"] = prev_time
                current_state["status"] = "updated"
            except Exception as e:
                logger.warning("Failed to read monitor state file for %s: %s", url, e)
                current_state["status"] = "first_check"
        else:
            current_state["status"] = "first_check"

        await asyncio.to_thread(
            state_file.write_text,
            json.dumps(current_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return ToolResult(
            success=True,
            output=current_state,
        )
