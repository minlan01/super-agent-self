"""Desktop Automation API — file system, windows, screenshots."""

import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from apps.api_server.dependencies import require_permission
from packages.agent_core.schemas import TaskExecutionResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_READ_SIZE = 10 * 1024 * 1024  # 10 MB

_WRITE_RATE_WINDOW = 60
_WRITE_RATE_MAX = 20
_write_rate_store: dict[str, list[float]] = {}
_write_rate_lock = threading.Lock()
_write_rate_last_cleanup = 0.0
_WRITE_RATE_CLEANUP_INTERVAL = 300


def _check_write_rate(client_ip: str) -> None:
    global _write_rate_last_cleanup
    now = time.time()

    with _write_rate_lock:
        if now - _write_rate_last_cleanup > _WRITE_RATE_CLEANUP_INTERVAL:
            stale_keys = [
                key
                for key, values in _write_rate_store.items()
                if not values or now - values[-1] > _WRITE_RATE_WINDOW
            ]
            for k in stale_keys:
                del _write_rate_store[k]
            _write_rate_last_cleanup = now

        window = _write_rate_store.setdefault(client_ip, [])
        window[:] = [t for t in window if now - t < _WRITE_RATE_WINDOW]
        if len(window) >= _WRITE_RATE_MAX:
            raise HTTPException(status_code=429, detail="Too many write requests")
        window.append(now)


class FileSystemRequest(BaseModel):
    action: str = Field(..., pattern="^(list|read|write)$")
    path: str = Field(default=".", max_length=500)
    content: str | None = Field(default=None, max_length=100000)


class WindowRequest(BaseModel):
    action: str = Field(default="list", pattern="^(list|bind)$")
    window_id: str | None = Field(default=None, max_length=64)


@router.post(
    "/files",
    response_model=TaskExecutionResponse,
    dependencies=[Depends(require_permission("desktop", "write"))],
)
async def file_system_operation(body: FileSystemRequest, request: Request) -> dict[str, Any]:
    """File system operations within workspace."""
    from pathlib import Path

    from packages.config import get_settings

    if body.action == "write":
        _check_write_rate(request.client.host if request.client else "unknown")

    settings = get_settings()
    workspace = Path(settings.workspace_root).resolve()
    target = (workspace / body.path).resolve()

    if not target.is_relative_to(workspace):
        raise HTTPException(status_code=403, detail="Path outside workspace")

    if body.action == "list":
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")
        entries = [
            {"name": item.name, "type": "dir" if item.is_dir() else "file",
             "size": item.stat().st_size if item.is_file() else None}
            for item in sorted(target.iterdir())
        ]
        return {"success": True, "data": {"path": body.path, "entries": entries}}

    elif body.action == "read":
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        file_size = target.stat().st_size
        if file_size > _MAX_READ_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {file_size} bytes (max {_MAX_READ_SIZE})",
            )
        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "success": True,
            "data": {"path": body.path, "content": content, "size": len(content)},
        }

    elif body.action == "write":
        if not body.content:
            raise HTTPException(status_code=400, detail="content required for write")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.content, encoding="utf-8")
        return {"success": True, "data": {"path": body.path, "written": len(body.content)}}


@router.post(
    "/windows",
    response_model=TaskExecutionResponse,
    dependencies=[Depends(require_permission("desktop", "read"))],
)
async def list_windows(body: WindowRequest) -> dict[str, Any]:
    """List desktop windows."""
    from packages.executor.tools.desktop_tools import WindowManagerTool

    tool = WindowManagerTool()

    class _Ctx:
        workspace_root = "."

    result = await tool.execute(body.model_dump(), _Ctx())

    if not result.success:
        logger.warning("Window list failed: %s", result.error)
        raise HTTPException(status_code=500, detail="Window list failed")

    return {"success": True, "data": result.output}


@router.get(
    "/screenshot",
    response_model=TaskExecutionResponse,
    dependencies=[Depends(require_permission("desktop", "read"))],
)
async def take_screenshot(window_id: str | None = None) -> dict[str, Any]:
    """Take a desktop screenshot."""
    from packages.executor.tools.desktop_tools import DesktopScreenshot

    tool = DesktopScreenshot()

    from packages.config import get_settings

    class _Ctx:
        workspace_root = get_settings().workspace_root

    result = await tool.execute({"window_id": window_id}, _Ctx())

    if not result.success:
        logger.warning("Screenshot failed: %s", result.error)
        raise HTTPException(status_code=500, detail="Screenshot failed")

    return {"success": True, "data": result.output}
