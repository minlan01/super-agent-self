"""Personal Edition tools — file.search and file.summarize."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from packages.executor.tools.base import ToolBase, ToolResult
from packages.policy.unified_registry import tool_registry

logger = logging.getLogger(__name__)


@tool_registry.register(
    category="file",
    risk_level="low",
    emoji="🔎",
    params_schema={
        "type": "object",
        "required": ["keyword"],
        "properties": {
            "keyword": {"type": "string"},
            "path": {"type": "string", "default": "."},
        },
        "additionalProperties": False,
    },
)
class FileSearch(ToolBase):
    """Search files by name or content keyword within workspace."""

    name = "file.search"
    description = "Search files by name or content keyword"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        keyword = args.get("keyword", "")
        search_path = args.get("path", ".")
        workspace = Path(context.workspace_root)
        target = (workspace / search_path).resolve()

        if not target.is_relative_to(workspace.resolve()):
            return ToolResult(success=False, error="Path outside workspace")

        if not keyword:
            return ToolResult(success=False, error="keyword is required")

        results: list[dict[str, str]] = []
        max_results = 100

        safe_keyword = keyword.replace("*", "").replace("?", "").replace("[", "").replace("]", "")

        def _search_files():
            found: list[dict[str, str]] = []
            for p in target.rglob(f"*{safe_keyword}*"):
                if len(found) >= max_results:
                    break
                if p.is_file():
                    rel = str(p.relative_to(workspace))
                    found.append({"path": rel, "match": "filename"})
            return found

        results = await asyncio.to_thread(_search_files)

        text_extensions = {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".csv", ".html", ".css", ".js", ".ts"}

        def _search_content():
            found: list[dict[str, str]] = []
            count = 0
            for p in target.rglob("*"):
                if count >= 50:
                    break
                if not p.is_file() or p.suffix not in text_extensions:
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    if keyword.lower() in text.lower():
                        rel = str(p.relative_to(workspace))
                        found.append({"path": rel, "match": "content"})
                        count += 1
                except Exception as e:
                    logger.debug("Skipping file during search: %s", e)
                    continue
            return found

        content_results = await asyncio.to_thread(_search_content)
        existing_paths = {r["path"] for r in results}
        for r in content_results:
            if r["path"] not in existing_paths:
                results.append(r)

        return ToolResult(
            success=True,
            output={"keyword": keyword, "matches": len(results), "results": results[:50]},
        )


@tool_registry.register(
    category="file",
    risk_level="low",
    emoji="📊",
    params_schema={
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {"type": "string"},
        },
        "additionalProperties": False,
    },
)
class FileSummarize(ToolBase):
    """Summarize file content — returns first N lines as quick summary."""

    name = "file.summarize"
    description = "Summarize file content"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        file_path = args.get("path", "")
        if not file_path:
            return ToolResult(success=False, error="path is required")

        workspace = Path(context.workspace_root)
        target = (workspace / file_path).resolve()

        if not target.is_relative_to(workspace.resolve()):
            return ToolResult(success=False, error="Path outside workspace")
        if not target.exists():
            return ToolResult(success=False, error="File not found")
        if not target.is_file():
            return ToolResult(success=False, error="Not a file")

        _MAX_SUMMARIZE_SIZE = 2 * 1024 * 1024

        def _read_and_stat():
            file_size = target.stat().st_size
            if file_size > _MAX_SUMMARIZE_SIZE:
                return None, file_size
            text = target.read_text(encoding="utf-8", errors="ignore")
            return text, file_size

        text, file_size = await asyncio.to_thread(_read_and_stat)
        if text is None:
            return ToolResult(success=False, error=f"File too large to summarize ({file_size} bytes, max {_MAX_SUMMARIZE_SIZE})")

        lines = text.splitlines()
        total_lines = len(lines)
        total_chars = len(text)

        # Quick summary: first 20 lines + stats
        head = "\n".join(lines[:20])
        summary = (
            f"File: {file_path}\n"
            f"Size: {total_chars} chars, {total_lines} lines\n\n"
            f"--- First 20 lines ---\n{head}"
        )
        if total_lines > 20:
            summary += f"\n... ({total_lines - 20} more lines)"

        return ToolResult(success=True, output={"summary": summary, "lines": total_lines, "chars": total_chars})
