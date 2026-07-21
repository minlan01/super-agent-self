"""Desktop Control — safety-restricted mouse and keyboard automation."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from packages.executor.tools.base import ToolBase, ToolResult
from packages.policy.unified_registry import tool_registry

logger = logging.getLogger(__name__)

MAX_ACTIONS_PER_EXECUTION = 10
_WINDOW_LIST_TIMEOUT_WINDOWS = 10
_WINDOW_LIST_TIMEOUT_UNIX = 5


@tool_registry.register(category="desktop", risk_level="high", emoji="🖱️")
class DesktopClick(ToolBase):
    """Click at screen coordinates (safety-restricted)."""

    name = "desktop.click"
    description = "Click at screen coordinates"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.5
        except ImportError:
            return ToolResult(success=False, error="pyautogui not installed")

        x = args.get("x")
        y = args.get("y")
        if x is None or y is None:
            return ToolResult(success=False, error="x and y coordinates required")

        try:
            x_int = int(x)
            y_int = int(y)
        except (ValueError, TypeError):
            return ToolResult(success=False, error="x and y must be integers")

        if x_int < 0 or y_int < 0 or x_int > 7680 or y_int > 4320:
            return ToolResult(success=False, error="Coordinates out of reasonable screen range")

        button = args.get("button", "left")
        if button not in ("left", "right", "middle"):
            return ToolResult(success=False, error="button must be 'left', 'right', or 'middle'")

        clicks = args.get("clicks", 1)
        try:
            clicks_int = int(clicks)
        except (ValueError, TypeError):
            return ToolResult(success=False, error="clicks must be an integer")
        if clicks_int < 1 or clicks_int > 5:
            return ToolResult(success=False, error="clicks must be between 1 and 5")

        try:
            pyautogui.click(x=x_int, y=y_int, button=button, clicks=clicks_int)
            return ToolResult(success=True, output={"action": "click", "x": x, "y": y})
        except Exception as e:
            return ToolResult(success=False, error=str(e))


@tool_registry.register(category="desktop", risk_level="medium", emoji="⌨️")
class DesktopType(ToolBase):
    """Type text via keyboard (safety-restricted)."""

    name = "desktop.type"
    description = "Type text using keyboard"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.3
        except ImportError:
            return ToolResult(success=False, error="pyautogui not installed")

        text = args.get("text", "")
        if not text:
            return ToolResult(success=False, error="text is required")

        # Safety: limit text length
        if len(text) > 500:
            return ToolResult(success=False, error="Text too long (max 500 chars)")

        # Safety: block dangerous characters/commands
        dangerous = ["ctrl", "alt", "delete", "command", "win", "super"]
        text_lower = text.lower()
        for d in dangerous:
            if d in text_lower:
                return ToolResult(success=False, error=f"Blocked: contains '{d}'")

        try:
            pyautogui.typewrite(text, interval=0.05)
            return ToolResult(success=True, output={"action": "type", "chars": len(text)})
        except Exception as e:
            return ToolResult(success=False, error=str(e))


@tool_registry.register(category="desktop", risk_level="low", emoji="📸")
class DesktopScreenshot(ToolBase):
    """Take a desktop screenshot."""

    name = "desktop.screenshot"
    description = "Capture desktop screenshot"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        try:
            from pathlib import Path

            import pyautogui
        except ImportError:
            return ToolResult(success=False, error="pyautogui not installed")

        workspace = Path(context.workspace_root)
        output_dir = workspace / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"desktop_{int(time.time())}.png"
        output_path = output_dir / filename

        try:
            img = pyautogui.screenshot()
            img.save(str(output_path))
            return ToolResult(
                success=True,
                output={"path": str(output_path)},
                artifacts=[str(output_path)],
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


@tool_registry.register(category="desktop", risk_level="medium", emoji="📁")
class FileSystemTool(ToolBase):
    """File system operations within workspace (list, read, write)."""

    name = "desktop.files"
    description = "List, read, or write files within the workspace"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        from pathlib import Path

        action = args.get("action", "list")
        path = args.get("path", ".")
        workspace = Path(context.workspace_root).resolve()

        # Safety: resolve and verify path is within workspace
        target = (workspace / path).resolve()
        if not target.is_relative_to(workspace):
            return ToolResult(success=False, error="Path outside workspace")

        try:
            if action == "list":
                if not target.is_dir():
                    return ToolResult(success=False, error=f"Not a directory: {path}")
                entries = []
                for item in sorted(target.iterdir()):
                    entries.append({
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else None,
                    })
                return ToolResult(success=True, output={"path": path, "entries": entries})

            elif action == "read":
                if not target.is_file():
                    return ToolResult(success=False, error=f"Not a file: {path}")
                # Safety: limit file size
                size = target.stat().st_size
                if size > 1_000_000:  # 1MB limit
                    return ToolResult(success=False, error=f"File too large: {size} bytes (max 1MB)")
                content = target.read_text(encoding="utf-8", errors="replace")
                return ToolResult(success=True, output={"path": path, "content": content, "size": size})

            elif action == "write":
                content = args.get("content", "")
                if not content:
                    return ToolResult(success=False, error="content is required for write")
                # Safety: limit write size
                if len(content) > 100_000:  # 100KB limit
                    return ToolResult(success=False, error="Content too large (max 100KB)")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return ToolResult(success=True, output={"path": path, "written": len(content)})

            else:
                return ToolResult(success=False, error=f"Unknown action: {action}. Use list/read/write.")

        except Exception as e:
            return ToolResult(success=False, error=str(e))


@tool_registry.register(category="desktop", risk_level="medium", emoji="🪟")
class WindowManagerTool(ToolBase):
    """List and manage desktop windows."""

    name = "desktop.windows"
    description = "List open windows and get window information"

    async def execute(self, args: dict[str, Any], context: Any) -> ToolResult:
        action = args.get("action", "list")

        try:
            if action == "list":
                # Use platform-specific window listing
                import platform
                windows = []
                system = platform.system()

                if system == "Windows":
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            "powershell", "-Command",
                            "Get-Process | Where-Object {$_.MainWindowTitle} | "
                            "Select-Object Id, ProcessName, MainWindowTitle | "
                            "ConvertTo-Json",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=_WINDOW_LIST_TIMEOUT_WINDOWS)
                        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
                        if proc.returncode == 0 and stdout:
                            data = json.loads(stdout)
                            if isinstance(data, dict):
                                data = [data]
                            for w in data:
                                windows.append({
                                    "id": w.get("Id"),
                                    "name": w.get("ProcessName", ""),
                                    "title": w.get("MainWindowTitle", ""),
                                })
                    except Exception as e:
                        logger.warning("Failed to list Windows windows: %s", e)
                elif system == "Linux":
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            "wmctrl", "-l",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=_WINDOW_LIST_TIMEOUT_UNIX)
                        stdout = stdout_bytes.decode("utf-8", errors="replace")
                        if proc.returncode == 0:
                            for line in stdout.strip().split("\n"):
                                parts = line.split(None, 3)
                                if len(parts) >= 4:
                                    windows.append({
                                        "id": parts[0],
                                        "name": parts[2],
                                        "title": parts[3],
                                    })
                    except Exception as e:
                        logger.warning("Failed to list Linux windows: %s", e)
                elif system == "Darwin":
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            "osascript", "-e",
                            'tell application "System Events" to get name of every window of every process whose visible is true',
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=_WINDOW_LIST_TIMEOUT_UNIX)
                        stdout = stdout_bytes.decode("utf-8", errors="replace")
                        if proc.returncode == 0:
                            for title in stdout.strip().split(", "):
                                if title:
                                    windows.append({"id": None, "name": "", "title": title.strip()})
                    except Exception as e:
                        logger.warning("Failed to list macOS windows: %s", e)

                return ToolResult(success=True, output={"windows": windows, "platform": system})

            else:
                return ToolResult(success=False, error=f"Unknown action: {action}. Use list.")

        except Exception as e:
            return ToolResult(success=False, error=str(e))
