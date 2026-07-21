"""File download API — serve workspace output files with path traversal protection."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from apps.api_server.dependencies import require_permission

router = APIRouter()

_WORKSPACE_ROOT = Path("./workspace").resolve()

_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30
_rate_limit_store: dict[str, list[float]] = {}
_rate_limit_last_cleanup = 0.0
_RATE_LIMIT_CLEANUP_INTERVAL = 300


def _check_rate_limit(client_ip: str) -> None:
    global _rate_limit_last_cleanup
    now = time.time()

    if now - _rate_limit_last_cleanup > _RATE_LIMIT_CLEANUP_INTERVAL:
        stale_keys = [k for k, v in _rate_limit_store.items() if not v or now - v[-1] > _RATE_LIMIT_WINDOW]
        for k in stale_keys:
            del _rate_limit_store[k]
        _rate_limit_last_cleanup = now

    window = _rate_limit_store.setdefault(client_ip, [])
    window[:] = [t for t in window if now - t < _RATE_LIMIT_WINDOW]
    if len(window) >= _RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Too many file requests")
    window.append(now)


def _safe_path(relative_path: str) -> Path:
    target = (_WORKSPACE_ROOT / relative_path).resolve()
    if not target.is_relative_to(_WORKSPACE_ROOT):
        raise HTTPException(status_code=403, detail="Path outside workspace")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return target


@router.get("/{file_path:path}", dependencies=[Depends(require_permission("files", "read"))])
def download_file(file_path: str, request: Request):
    _check_rate_limit(request.client.host if request.client else "unknown")
    full_path = _safe_path(file_path)
    return FileResponse(
        path=str(full_path),
        filename=full_path.name,
        media_type="application/octet-stream",
    )
