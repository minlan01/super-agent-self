"""Export API — export tasks, memories, and audit events as JSON or CSV."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_db, require_permission

router = APIRouter()


def _to_csv_rows(items: list[dict[str, Any]]) -> str:
    """Convert list of dicts to CSV string."""
    if not items:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=items[0].keys())
    writer.writeheader()
    writer.writerows(items)
    return output.getvalue()


def _task_to_dict(task: Any) -> dict[str, Any]:
    return {
        "id": task.id,
        "goal": task.goal,
        "edition": task.edition.value if hasattr(task.edition, "value") else task.edition,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
        "user_id": task.user_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _memory_to_dict(mem: Any) -> dict[str, Any]:
    return {
        "id": mem.id,
        "title": mem.title,
        "summary": mem.summary,
        "memory_type": mem.memory_type.value if hasattr(mem.memory_type, "value") else mem.memory_type,
        "is_active": mem.is_active,
        "user_id": mem.user_id,
        "created_at": mem.created_at.isoformat() if mem.created_at else None,
    }


def _audit_to_dict(event: Any) -> dict[str, Any]:
    return {
        "id": event.id,
        "task_id": event.task_id,
        "edition": event.edition.value if hasattr(event.edition, "value") else event.edition,
        "event_type": event.event_type.value if hasattr(event.event_type, "value") else event.event_type,
        "detail": json.dumps(event.detail) if isinstance(event.detail, dict) else str(event.detail),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


_EXPORT_MAX_LIMIT = 10_000


@router.get("/tasks", dependencies=[Depends(require_permission("export", "read"))])
def export_tasks(
    format: str = Query("json", pattern="^(json|csv)$"),
    limit: int = Query(1000, ge=1, le=_EXPORT_MAX_LIMIT),
    db: Session = Depends(get_db),
):
    from sqlalchemy import select

    from packages.db.models import Task

    tasks = list(db.scalars(select(Task).order_by(Task.created_at.desc()).limit(limit)).all())
    items = [_task_to_dict(t) for t in tasks]

    if format == "csv":
        return StreamingResponse(
            io.BytesIO(_to_csv_rows(items).encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=tasks.csv"},
        )

    return {"success": True, "count": len(items), "data": items}


@router.get("/memories", dependencies=[Depends(require_permission("export", "read"))])
def export_memories(
    format: str = Query("json", pattern="^(json|csv)$"),
    limit: int = Query(1000, ge=1, le=_EXPORT_MAX_LIMIT),
    db: Session = Depends(get_db),
):
    from sqlalchemy import select

    from packages.db.models import Memory

    memories = list(db.scalars(select(Memory).order_by(Memory.created_at.desc()).limit(limit)).all())
    items = [_memory_to_dict(m) for m in memories]

    if format == "csv":
        return StreamingResponse(
            io.BytesIO(_to_csv_rows(items).encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=memories.csv"},
        )

    return {"success": True, "count": len(items), "data": items}


@router.get("/audit", dependencies=[Depends(require_permission("export", "read"))])
def export_audit(
    format: str = Query("json", pattern="^(json|csv)$"),
    limit: int = Query(1000, ge=1, le=_EXPORT_MAX_LIMIT),
    db: Session = Depends(get_db),
):
    from sqlalchemy import select

    from packages.db.models import AuditEvent

    events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all())
    items = [_audit_to_dict(e) for e in events]

    if format == "csv":
        return StreamingResponse(
            io.BytesIO(_to_csv_rows(items).encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit.csv"},
        )

    return {"success": True, "count": len(items), "data": items}
