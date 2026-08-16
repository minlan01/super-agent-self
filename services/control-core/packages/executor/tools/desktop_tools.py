"""Desktop tools backed by typed platform capabilities and stale-state gates."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from packages.executor.tools.base import ToolBase, ToolResult
from packages.platform.runtime import get_platform_adapter
from packages.platform.shared.contracts import (
    PlatformAdapter,
    ScreenshotArtifact,
    WindowInfo,
)
from packages.platform.shared.errors import StaleUIState
from packages.policy.unified_registry import tool_registry

logger = logging.getLogger(__name__)

MAX_ACTIONS_PER_EXECUTION = 10
_MAX_TEXT_LENGTH = 500


def _selectors(args: dict[str, Any]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for key in ("automation_id", "control_type", "name", "class_name"):
        value = args.get(key)
        result[key] = str(value) if value not in (None, "") else None
    return result


def _window_output(info: WindowInfo) -> dict[str, Any]:
    return {
        "window_id": info.window_id,
        "title": info.title,
        "pid": info.pid,
        "ui_digest": info.ui_digest,
    }


def _stale_result(exc: StaleUIState) -> ToolResult:
    return ToolResult(
        success=False,
        error=f"STALE_UI_STATE: {exc}; re-bind the window; do not retry this action",
    )


class _PlatformTool(ToolBase):
    def __init__(self, *, adapter: PlatformAdapter | Any | None = None) -> None:
        self._adapter = adapter

    @property
    def adapter(self) -> PlatformAdapter:
        return self._adapter or get_platform_adapter()


@tool_registry.register(category="desktop", risk_level="high", emoji="🖱️")
class DesktopClick(_PlatformTool):
    """Invoke a semantic UIA target or an explicitly approved coordinate fallback."""

    name = "desktop.click"
    description = "Invoke a stale-gated UI Automation control"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        window_id = args.get("window_id")
        expected_digest = args.get("expected_ui_digest")
        if not window_id or not expected_digest:
            return ToolResult(
                success=False,
                error="window_id and expected_ui_digest are required",
            )

        try:
            provider = self.adapter.window_provider()
            has_coordinates = args.get("x") is not None or args.get("y") is not None
            if has_coordinates:
                if args.get("x") is None or args.get("y") is None:
                    return ToolResult(success=False, error="both x and y coordinates are required")
                if not bool(args.get("coordinate_fallback_approved", False)):
                    return ToolResult(
                        success=False,
                        error="coordinate fallback requires explicit approval",
                    )
                try:
                    x = int(args["x"])
                    y = int(args["y"])
                except (TypeError, ValueError):
                    return ToolResult(success=False, error="x and y must be integers")
                result = await provider.coordinate_click(
                    str(window_id),
                    str(expected_digest),
                    x=x,
                    y=y,
                    approved=True,
                )
                output = asdict(result)
                output["action"] = "coordinate_click"
                return ToolResult(success=result.success, output=output, error=result.error)

            selectors = _selectors(args)
            if not any(selectors.values()):
                return ToolResult(
                    success=False,
                    error="at least one semantic UIA selector is required",
                )
            result = await provider.invoke(
                str(window_id),
                str(expected_digest),
                **selectors,
            )
            return ToolResult(
                success=result.success,
                output=asdict(result),
                error=result.error,
            )
        except StaleUIState as exc:
            return _stale_result(exc)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


@tool_registry.register(category="desktop", risk_level="medium", emoji="⌨️")
class DesktopType(_PlatformTool):
    """Set text through a UIA ValuePattern after stale-state validation."""

    name = "desktop.type"
    description = "Set text on a stale-gated UI Automation control"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        text = args.get("text")
        if not isinstance(text, str) or not text:
            return ToolResult(success=False, error="text is required")
        if len(text) > _MAX_TEXT_LENGTH:
            return ToolResult(success=False, error="Text too long (max 500 chars)")

        window_id = args.get("window_id")
        expected_digest = args.get("expected_ui_digest")
        if not window_id or not expected_digest:
            return ToolResult(
                success=False,
                error="window_id and expected_ui_digest are required",
            )
        selectors = _selectors(args)
        if not any(selectors.values()):
            return ToolResult(
                success=False,
                error="at least one semantic UIA selector is required",
            )

        try:
            result = await self.adapter.window_provider().set_text(
                str(window_id),
                str(expected_digest),
                text,
                **selectors,
            )
            output = asdict(result)
            output["chars"] = len(text)
            return ToolResult(success=result.success, output=output, error=result.error)
        except StaleUIState as exc:
            return _stale_result(exc)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


@tool_registry.register(category="desktop", risk_level="low", emoji="📸")
class DesktopScreenshot(_PlatformTool):
    """Capture through WGC and persist only inside the task workspace."""

    name = "desktop.screenshot"
    description = "Capture a confidential Windows Graphics Capture screenshot"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        try:
            screenshot = await self.adapter.screen_capture().grab(
                window_id=args.get("window_id"),
            )
            workspace = Path(context.workspace_root).resolve()
            output_dir = (workspace / "screenshots").resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            if not output_dir.is_relative_to(workspace):
                raise PermissionError("screenshot path escapes task workspace")

            filename = f"desktop_{uuid.uuid4().hex}.png"
            output_path = (output_dir / filename).resolve()
            if not output_path.is_relative_to(workspace):
                raise PermissionError("screenshot path escapes task workspace")
            with output_path.open("xb") as handle:
                handle.write(screenshot.data)

            relative_path = output_path.relative_to(workspace).as_posix()
            artifact = ScreenshotArtifact(
                artifact_id=uuid.uuid4().hex,
                relative_path=relative_path,
                mime_type=screenshot.mime_type,
                width=screenshot.width,
                height=screenshot.height,
                sha256=hashlib.sha256(screenshot.data).hexdigest(),
                classification=screenshot.classification,  # type: ignore[arg-type]
                size_bytes=len(screenshot.data),
            )
            artifact_output = asdict(artifact)
            artifact_output["classification"] = screenshot.classification.value
            return ToolResult(
                success=True,
                output={"artifact": artifact_output},
                artifacts=[relative_path],
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


@tool_registry.register(category="desktop", risk_level="medium", emoji="📁")
class FileSystemTool(ToolBase):
    """File system operations within workspace (list, read, write)."""

    name = "desktop.files"
    description = "List, read, or write files within the workspace"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        action = args.get("action", "list")
        path = args.get("path", ".")
        workspace = Path(context.workspace_root).resolve()
        target = (workspace / path).resolve()
        if not target.is_relative_to(workspace):
            return ToolResult(success=False, error="Path outside workspace")

        try:
            if action == "list":
                if not target.is_dir():
                    return ToolResult(success=False, error=f"Not a directory: {path}")
                entries = [
                    {
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else None,
                    }
                    for item in sorted(target.iterdir())
                ]
                return ToolResult(success=True, output={"path": path, "entries": entries})

            if action == "read":
                if not target.is_file():
                    return ToolResult(success=False, error=f"Not a file: {path}")
                size = target.stat().st_size
                if size > 1_000_000:
                    return ToolResult(
                        success=False,
                        error=f"File too large: {size} bytes (max 1MB)",
                    )
                content = target.read_text(encoding="utf-8", errors="replace")
                return ToolResult(
                    success=True,
                    output={"path": path, "content": content, "size": size},
                )

            if action == "write":
                content = args.get("content", "")
                if not content:
                    return ToolResult(success=False, error="content is required for write")
                if len(content) > 100_000:
                    return ToolResult(success=False, error="Content too large (max 100KB)")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return ToolResult(
                    success=True,
                    output={"path": path, "written": len(content)},
                )

            return ToolResult(
                success=False,
                error=f"Unknown action: {action}. Use list/read/write.",
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


@tool_registry.register(category="desktop", risk_level="medium", emoji="🪟")
class WindowManagerTool(_PlatformTool):
    """List windows or bind one to obtain a fresh stale-state digest."""

    name = "desktop.windows"
    description = "List or bind desktop windows through the platform provider"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        action = args.get("action", "list")
        try:
            provider = self.adapter.window_provider()
            if action == "list":
                windows = await provider.list_windows()
                return ToolResult(
                    success=True,
                    output={"windows": [_window_output(window) for window in windows]},
                )
            if action == "bind":
                window_id = args.get("window_id")
                if not window_id:
                    return ToolResult(success=False, error="window_id is required for bind")
                window = await provider.bind_window(str(window_id))
                return ToolResult(success=True, output={"window": _window_output(window)})
            return ToolResult(
                success=False,
                error=f"Unknown action: {action}. Use list/bind.",
            )
        except Exception as exc:
            logger.warning("Desktop window operation failed: %s", exc)
            return ToolResult(success=False, error=str(exc))
