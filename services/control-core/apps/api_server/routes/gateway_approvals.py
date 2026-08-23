"""Gateway Approval API — high-risk step approval endpoints (P3.2).

These routes expose the P2.6 ApprovalService for the ToolGateway execution
chain.  They are separate from the legacy ``approvals`` router (which handles
skill marketplace approvals).

Endpoints:
  GET    /api/v1/gateway-approvals              List pending approval requests
  POST   /api/v1/gateway-approvals/{id}/vote    Cast a vote (approve/reject)
  POST   /api/v1/gateway-approvals/{id}/resolve Check quorum and resolve
  GET    /api/v1/gateway-approvals/{id}         Get request detail + votes

Security:
  - Voter identity comes from ActorScope (server-side JWT), never from
    request body (anti-forgery, spec §2.3).
  - Self-approval is rejected by ApprovalService (SelfApprovalError).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_current_actor_scope, get_db, get_orchestrator
from packages.approval.approval_service import (
    ApprovalService,
    DuplicateVoteError,
    SelfApprovalError,
)
from packages.auth.actor_scope import ActorScope
from packages.db.models import ApprovalRequestStatus, VoteDecision

router = APIRouter(tags=["gateway-approvals"])


# ── Request/Response schemas ──────────────────────────────────────────────


class VoteRequest(BaseModel):
    """Body for casting a vote. Voter identity comes from ActorScope, NOT body."""
    decision: VoteDecision
    reason: str | None = Field(None, max_length=500)


class ApprovalRequestResponse(BaseModel):
    id: str
    step_run_id: str
    tool_name: str
    risk_level: str
    status: ApprovalRequestStatus
    requester_principal_id: str
    required_quorum: int
    resolution_id: str | None = None

    class Config:
        from_attributes = True


class VoteResponse(BaseModel):
    vote_id: str
    request_id: str
    decision: VoteDecision
    accepted: bool
    reason: str = ""


class ResolutionResponse(BaseModel):
    request_id: str
    status: ApprovalRequestStatus
    resolution_id: str | None
    reason: str = ""


class ApprovalListResponse(BaseModel):
    items: list[ApprovalRequestResponse]
    total: int


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("", response_model=ApprovalListResponse)
def list_pending_approvals(
    status_filter: ApprovalRequestStatus | None = Query(
        ApprovalRequestStatus.PENDING, alias="status"
    ),
    db: Session = Depends(get_db),
    scope: ActorScope = Depends(get_current_actor_scope),
):
    """List approval requests for the current tenant."""
    from packages.db.repositories.approval_request_repo import (
        ApprovalRequestRepository,
    )

    if status_filter == ApprovalRequestStatus.PENDING:
        items = ApprovalRequestRepository.get_pending(
            db, tenant_id=scope.tenant_id,
        )
    else:
        # For non-pending, do a simple scan (production would add pagination).
        from sqlalchemy import select

        from packages.db.models import ApprovalRequestModel

        items = list(db.scalars(
            select(ApprovalRequestModel)
            .where(
                ApprovalRequestModel.tenant_id == scope.tenant_id,
                ApprovalRequestModel.status == status_filter,
            )
            .order_by(ApprovalRequestModel.created_at.desc())
            .limit(100)
        ))

    return ApprovalListResponse(
        items=[ApprovalRequestResponse.model_validate(i) for i in items],
        total=len(items),
    )


@router.get("/{request_id}", response_model=ApprovalRequestResponse)
def get_approval(
    request_id: str,
    db: Session = Depends(get_db),
    scope: ActorScope = Depends(get_current_actor_scope),
):
    """Get a single approval request by ID."""
    from packages.db.repositories.approval_request_repo import (
        ApprovalRequestRepository,
    )

    req = ApprovalRequestRepository.get_by_id(db, request_id)
    if req is None or req.tenant_id != scope.tenant_id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return ApprovalRequestResponse.model_validate(req)


@router.post("/{request_id}/vote", response_model=VoteResponse)
def cast_vote(
    request_id: str,
    body: VoteRequest,
    db: Session = Depends(get_db),
    scope: ActorScope = Depends(get_current_actor_scope),
):
    """Cast a vote on an approval request.

    Voter identity is taken from the ActorScope (JWT-derived), NOT from the
    request body.  This prevents identity forgery (spec §2.3 G E-04).
    """
    svc = ApprovalService(db)

    try:
        result = svc.cast_vote(
            request_id=request_id,
            voter_principal_id=scope.principal_id,
            decision=body.decision,
            reason=body.reason,
        )
    except SelfApprovalError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except DuplicateVoteError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if not result.accepted:
        raise HTTPException(status_code=409, detail=result.reason)

    db.commit()
    return VoteResponse(
        vote_id=result.vote_id,
        request_id=result.request_id,
        decision=result.decision,
        accepted=True,
    )


@router.post("/{request_id}/resolve", response_model=ResolutionResponse)
async def resolve_approval(
    request_id: str,
    db: Session = Depends(get_db),
    scope: ActorScope = Depends(get_current_actor_scope),
):
    """Check quorum and resolve an approval request.

    This is idempotent — calling it multiple times is safe.  If quorum is
    not yet reached, returns PENDING.  Once resolved, returns the final
    status and resolution_id (if APPROVED).
    """
    svc = ApprovalService(db)

    # Verify tenant access.
    from packages.db.repositories.approval_request_repo import (
        ApprovalRequestRepository,
    )
    req = ApprovalRequestRepository.get_by_id(db, request_id)
    if req is None or req.tenant_id != scope.tenant_id:
        raise HTTPException(status_code=404, detail="Approval request not found")

    result = svc.resolve(request_id)
    db.commit()

    # Only task-bound gateway approvals trigger execution resumption.  The
    # legacy/API fixture approvals may intentionally have no TaskStep row.
    if result.status in (ApprovalRequestStatus.APPROVED, ApprovalRequestStatus.REJECTED):
        from packages.db.models import TaskStep
        if db.get(TaskStep, req.step_run_id) is not None:
            await get_orchestrator().resume_after_approval(request_id)

    return ResolutionResponse(
        request_id=result.request_id,
        status=result.status,
        resolution_id=result.resolution_id,
        reason=result.reason,
    )
