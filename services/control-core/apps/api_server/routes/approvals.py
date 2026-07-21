"""Approval API routes — list, approve, reject, batch-resolve."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api_server.dependencies import (
    CommonQueryParams,
    get_current_user,
    get_db,
    require_permission,
)
from packages.agent_core.schemas import (
    ApprovalListResponse,
    ApprovalResolve,
    ApprovalResponse,
    AuditEventCreate,
    BatchApprovalRequest,
    BatchApprovalResultResponse,
    ResponseBase,
    TaskExecutionResponse,
)
from packages.db.models import ApprovalStatus, ApprovalType, AuditEventType, User
from packages.db.repositories.approval_repo import ApprovalRepository
from packages.db.repositories.audit_repo import AuditRepository

router = APIRouter()


@router.get("", response_model=ApprovalListResponse, dependencies=[Depends(require_permission("approvals", "read"))])
def list_approvals(
    commons: CommonQueryParams = Depends(),
    edition: str | None = None,
    status: str | None = None,
    approval_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """List approvals with optional filters."""
    skip = (commons.page - 1) * commons.page_size

    from sqlalchemy import func, select

    from packages.db.models import Approval

    stmt = select(Approval).order_by(Approval.created_at.desc())
    count_stmt = select(func.count()).select_from(Approval)

    if edition:
        stmt = stmt.where(Approval.edition == edition)
        count_stmt = count_stmt.where(Approval.edition == edition)
    if status:
        stmt = stmt.where(Approval.status == ApprovalStatus(status))
        count_stmt = count_stmt.where(Approval.status == ApprovalStatus(status))
    if approval_type:
        try:
            at = ApprovalType(approval_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid approval_type: {approval_type}")
        stmt = stmt.where(Approval.approval_type == at)
        count_stmt = count_stmt.where(Approval.approval_type == at)

    total = db.scalar(count_stmt) or 0
    approvals = list(db.scalars(stmt.offset(skip).limit(commons.page_size)).all())

    return ApprovalListResponse(
        data=[ApprovalResponse.model_validate(a) for a in approvals],
        total=total,
    )


@router.get("/{approval_id}", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("approvals", "read"))])
def get_approval(approval_id: str, db: Session = Depends(get_db)):
    """Get approval detail."""
    approval = ApprovalRepository.get_by_id(db, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return {"success": True, "data": ApprovalResponse.model_validate(approval).model_dump()}


@router.post("/{approval_id}/resolve", response_model=ResponseBase, dependencies=[Depends(require_permission("approvals", "write"))])
def resolve_approval(
    approval_id: str,
    body: ApprovalResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    approval = ApprovalRepository.get_by_id(db, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Approval already {approval.status.value}")

    if not body.approved_by or body.approved_by == "system":
        body.approved_by = current_user.id

    resolved = ApprovalRepository.resolve(db, approval_id, body)
    if resolved is None:
        raise HTTPException(status_code=409, detail="Approval was already resolved by another request")
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.APPROVAL_GRANTED if body.approved else AuditEventType.APPROVAL_REJECTED,
        actor=body.approved_by,
        detail={"approval_id": approval_id, "approved": body.approved},
    ))
    return ResponseBase(
        message=f"Approval {'approved' if body.approved else 'rejected'} by {body.approved_by}"
    )


@router.post("/batch-resolve", response_model=BatchApprovalResultResponse, dependencies=[Depends(require_permission("approvals", "write"))])
def batch_resolve(
    body: BatchApprovalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Batch resolve multiple approvals.

    Pre-loads all referenced approvals in a single SELECT to avoid N+1
    queries, then issues per-row UPDATEs (each guarded by the
    PENDING-status race-check).  Audit events are flushed in a single
    ``add_all`` call at the end.
    """
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    ids = [item.approval_id for item in body.items]
    approvals_by_id = ApprovalRepository.get_many_by_ids(db, ids)

    results = []
    audit_events: list[AuditEventCreate] = []
    for item in body.items:
        approval = approvals_by_id.get(item.approval_id)
        if approval is None:
            results.append({"approval_id": item.approval_id, "status": "not_found"})
            continue
        if approval.status != ApprovalStatus.PENDING:
            results.append({
                "approval_id": item.approval_id,
                "status": "already_resolved",
                "current_status": approval.status.value,
            })
            continue

        resolve_body = ApprovalResolve(
            approved=item.approved,
            approved_by=item.approved_by or current_user.id,
            reason=item.reason,
        )
        resolved = ApprovalRepository.resolve(db, item.approval_id, resolve_body)
        if resolved is None:
            results.append({"approval_id": item.approval_id, "status": "conflict"})
            continue

        audit_events.append(AuditEventCreate(
            event_type=AuditEventType.APPROVAL_GRANTED if item.approved else AuditEventType.APPROVAL_REJECTED,
            actor=resolve_body.approved_by,
            detail={"approval_id": item.approval_id, "approved": item.approved, "batch": True},
        ))
        results.append({"approval_id": item.approval_id, "status": "resolved"})

    if audit_events:
        AuditRepository.batch_create(db, audit_events)

    resolved_count = len([r for r in results if r['status'] == 'resolved'])
    return {
        "success": True,
        "message": f"Batch resolved {resolved_count}/{len(body.items)} approvals",
        "resolved": resolved_count,
        "results": results,
    }
