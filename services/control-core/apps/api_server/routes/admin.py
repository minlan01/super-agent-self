"""Admin routes — database backup, restore, and rate-limit management."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_db, require_permission
from packages.agent_core.schemas import (
    AuditEventCreate,
    TaskExecutionResponse,
)
from packages.admin.backup_service import BackupError, BackupService, RestoreError
from packages.config import get_settings
from packages.db.models import AuditEventType, User
from packages.db.repositories.audit_repo import AuditRepository
from packages.middleware.rate_limiter import get_active_limiter

logger = logging.getLogger(__name__)

router = APIRouter()

# Default backup directory
_DEFAULT_BACKUP_DIR = "data/backups"


def _safe_backup_id(backup_id: str) -> str:
    """Validate backup_id contains only safe characters to prevent path traversal.

    Only allows alphanumeric, underscores, hyphens, and dots.
    Rejects path separators, parent directory references, and null bytes.
    """
    import re
    if not backup_id or not re.match(r'^[a-zA-Z0-9_\-.]+$', backup_id):
        raise HTTPException(status_code=400, detail="Invalid backup ID format")
    return backup_id


def _get_backup_dir() -> str:
    """Return the backup directory from settings or the default."""
    settings = get_settings()
    # Derive backup dir from the database path's parent
    db_path = settings.database.url
    if db_path.startswith("sqlite:///"):
        db_parent = db_path[len("sqlite:///"):].rsplit("/", 1)[0]
        return db_parent + "/backups"
    return _DEFAULT_BACKUP_DIR


# ── Request / Response schemas ───────────────────────────────────────────


class RestoreRequest(BaseModel):
    backup_path: str


# ── Routes ────────────────────────────────────────────────────────────────


@router.post("/backup", response_model=TaskExecutionResponse)
async def create_backup(
    _user: User = Depends(require_permission("system", "admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a timestamped backup of the SQLite database."""
    settings = get_settings()
    backup_dir = _get_backup_dir()

    try:
        backup_path = await asyncio.to_thread(
            BackupService.create_backup,
            settings.database.url,
            backup_dir,
        )
    except BackupError as exc:
        logger.error("Backup failed: %s", exc)
        raise HTTPException(status_code=500, detail="Backup creation failed")

    try:
        AuditRepository.create(db, AuditEventCreate(
            event_type=AuditEventType.DB_BACKUP,
            actor=_user.id,
            detail={"backup_path": backup_path},
        ))
    except Exception:
        logger.warning("Failed to write backup audit event", exc_info=True)

    return {"success": True, "data": {"backup_path": backup_path}}


@router.post("/restore", response_model=TaskExecutionResponse)
async def restore_backup(
    body: RestoreRequest,
    _user: User = Depends(require_permission("system", "admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restore the database from a backup file.

    Accepts ``{"backup_path": "..."}`` in the request body.
    Only allows restoring from the designated backup directory.
    """
    from pathlib import Path

    settings = get_settings()
    backup_dir = Path(_get_backup_dir()).resolve()

    # Resolve and validate the backup path stays within backup_dir
    resolved = Path(body.backup_path).resolve()
    if not resolved.is_relative_to(backup_dir):
        raise HTTPException(status_code=400, detail="Backup path must be within the backup directory")

    try:
        await asyncio.to_thread(
            BackupService.restore_backup,
            settings.database.url,
            str(resolved),
            str(backup_dir),
        )
    except RestoreError as exc:
        logger.error("Restore failed: %s", exc)
        raise HTTPException(status_code=400, detail="Database restore failed")
    except BackupError as exc:
        logger.error("Backup error during restore: %s", exc)
        raise HTTPException(status_code=400, detail="Database restore failed")

    try:
        AuditRepository.create(db, AuditEventCreate(
            event_type=AuditEventType.DB_RESTORE,
            actor=_user.id,
            detail={"backup_path": body.backup_path},
        ))
    except Exception:
        logger.warning("Failed to write restore audit event", exc_info=True)

    return {"success": True, "data": {"message": "Database restored successfully"}}


@router.get("/backups", response_model=TaskExecutionResponse)
async def list_backups(
    _user: User = Depends(require_permission("system", "admin")),
) -> dict[str, Any]:
    """List all available database backups."""
    backup_dir = _get_backup_dir()

    backups = await asyncio.to_thread(
        BackupService.list_backups,
        backup_dir,
    )

    return {"success": True, "data": {"backups": backups, "total": len(backups)}}


@router.get("/backups/{backup_id}/validate", response_model=TaskExecutionResponse)
async def validate_backup(
    backup_id: str,
    _user: User = Depends(require_permission("system", "admin")),
) -> dict[str, Any]:
    """Validate a single backup's SQLite integrity on demand."""
    _safe_backup_id(backup_id)
    backup_dir = _get_backup_dir()

    from pathlib import Path
    backup_path = str(Path(backup_dir) / f"{backup_id}.db")

    try:
        result = await asyncio.to_thread(
            BackupService.validate_backup,
            backup_path,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup not found")

    return {"success": True, "data": result}


@router.delete("/backups/{backup_id}", response_model=TaskExecutionResponse)
async def delete_backup(
    backup_id: str,
    _user: User = Depends(require_permission("system", "admin")),
) -> dict[str, Any]:
    """Delete a specific backup by its ID (filename stem).

    For example, ``backup_id = "agent_platform_20260512_120000"``.
    """
    _safe_backup_id(backup_id)
    backup_dir = _get_backup_dir()

    # Reconstruct the full path from the backup_id
    from pathlib import Path
    backup_path = str(Path(backup_dir) / f"{backup_id}.db")

    try:
        await asyncio.to_thread(
            BackupService.delete_backup,
            backup_path,
            backup_dir,
        )
    except BackupError as exc:
        logger.error("Backup deletion failed: %s", exc)
        raise HTTPException(status_code=400, detail="Backup deletion failed")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup not found")

    return {"success": True, "data": {"message": f"Backup '{backup_id}' deleted"}}


# ── Rate-limit management ────────────────────────────────────────────────


@router.get("/rate-limits", response_model=TaskExecutionResponse)
async def get_rate_limits(
    _user: User = Depends(require_permission("system", "admin")),
) -> dict[str, Any]:
    """View current rate limit configuration."""
    limiter = get_active_limiter()
    if limiter is None:
        raise HTTPException(status_code=503, detail="Rate limiter not initialised")
    config = limiter.get_current_config()
    return {"success": True, "data": config}


@router.post("/rate-limits/reload", response_model=TaskExecutionResponse)
async def reload_rate_limits(
    _user: User = Depends(require_permission("system", "admin")),
) -> dict[str, Any]:
    """Trigger manual reload of rate_limits.yaml."""
    limiter = get_active_limiter()
    if limiter is None:
        raise HTTPException(status_code=503, detail="Rate limiter not initialised")
    config = limiter.reload_config()
    return {"success": True, "data": config}
