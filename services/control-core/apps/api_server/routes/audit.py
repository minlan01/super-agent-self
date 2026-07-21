"""Audit API routes — query audit events."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_db, require_permission
from packages.agent_core.schemas import AuditEventResponse, AuditListResponse
from packages.db.repositories.audit_repo import AuditRepository

router = APIRouter()


@router.get(
    "",
    response_model=AuditListResponse,
    summary="List audit events",
    description="Query the audit trail with optional filtering by task ID and event type. Supports pagination.",
    dependencies=[Depends(require_permission("audit", "read"))],
)
def list_audit_events(
    task_id: str | None = None,
    event_type: str | None = None,
    skip: int = Query(0, ge=0, le=10000),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List audit events with optional filters."""
    from packages.db.models import AuditEventType

    et = AuditEventType(event_type) if event_type else None
    events = AuditRepository.list_filters(
        db, task_id=task_id, event_type=et, skip=skip, limit=limit,
    )
    return AuditListResponse(data=[AuditEventResponse.model_validate(e) for e in events])
