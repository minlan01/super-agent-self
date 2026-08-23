"""Effect reconciliation API (spec P2.6: unknown_outcome → operator queue).

Endpoints (all tenant-scoped via ActorScope):
  GET  /api/v1/effects/unknown-outcomes       Queue of UNKNOWN_OUTCOME effects
  GET  /api/v1/effects/{id}                   Detail incl. dispatch history
  POST /api/v1/effects/{id}/reconcile         Operator marks confirmed|failed

Security: reconcile is an operator action on an uncertain external side
effect — audit-logged with actor identity; final states are immutable.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_current_actor_scope, get_db
from packages.auth.actor_scope import ActorScope
from packages.db.models import EffectClassDB, EffectStatusDB
from packages.execution.effect_journal import EffectJournal

router = APIRouter(tags=["effects"])


class UnknownOutcomeItem(BaseModel):
    effect_id: str
    step_run_id: str
    tool_name: str
    effect_class: str
    status: str
    created_at: str | None = None
    before_hash: str | None = None
    after_hash: str | None = None


class UnknownOutcomeListResponse(BaseModel):
    items: list[UnknownOutcomeItem]
    total: int


class DispatchAttemptItem(BaseModel):
    attempt_ordinal: int
    lease_id: str
    fencing_token: int
    worker_id: str
    adapter_name: str
    dispatched_at: str | None = None
    result_status: str | None = None


class EffectDetailResponse(BaseModel):
    effect_id: str
    step_run_id: str
    grant_id: str
    lease_id: str
    fencing_token: int
    status: str
    effect_class: str
    tool_name: str
    created_at: str | None = None
    finalized_at: str | None = None
    dispatch_history: list[DispatchAttemptItem]


class ReconcileRequest(BaseModel):
    final_status: EffectStatusDB = Field(..., description="confirmed | failed")
    note: str | None = Field(None, max_length=500)


class ReconcileResponse(BaseModel):
    effect_id: str
    status: str
    reconciled: bool


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@router.get("/unknown-outcomes", response_model=UnknownOutcomeListResponse)
async def list_unknown_outcomes(
    db: Session = Depends(get_db),
    scope: ActorScope = Depends(get_current_actor_scope),
):
    """Reconciliation queue: effects whose external outcome is uncertain."""
    journal = EffectJournal(db)
    effects = journal.get_unknown_outcomes(tenant_id=scope.tenant_id)
    return UnknownOutcomeListResponse(
        items=[
            UnknownOutcomeItem(
                effect_id=e.id,
                step_run_id=e.step_run_id,
                tool_name=e.tool_name,
                effect_class=str(getattr(e.effect_class, "value", e.effect_class)),
                status=str(getattr(e.status, "value", e.status)),
                created_at=_iso(e.created_at),
                before_hash=e.before_hash,
                after_hash=e.after_hash,
            )
            for e in effects
        ],
        total=len(effects),
    )


@router.get("/{effect_id}", response_model=EffectDetailResponse)
async def get_effect(
    effect_id: str,
    db: Session = Depends(get_db),
    scope: ActorScope = Depends(get_current_actor_scope),
):
    journal = EffectJournal(db)
    effect = journal.get_effect(effect_id)
    if effect is None:
        raise HTTPException(status_code=404, detail="Effect not found")
    # tenant check via step mapping: effect rows carry tenant on the model
    tenant = getattr(effect, "tenant_id", None)
    if tenant is not None and tenant != scope.tenant_id:
        raise HTTPException(status_code=404, detail="Effect not found")

    history = journal.get_dispatch_history(
        tenant_id=scope.tenant_id, effect_id=effect_id,
    )
    return EffectDetailResponse(
        effect_id=effect.id,
        step_run_id=effect.step_run_id,
        grant_id=effect.grant_id,
        lease_id=effect.lease_id,
        fencing_token=effect.fencing_token,
        status=str(getattr(effect.status, "value", effect.status)),
        effect_class=str(getattr(effect.effect_class, "value", e_class := effect.effect_class)),
        tool_name=effect.tool_name,
        created_at=_iso(effect.created_at),
        finalized_at=_iso(effect.finalized_at),
        dispatch_history=[
            DispatchAttemptItem(
                attempt_ordinal=a.attempt_ordinal,
                lease_id=a.lease_id,
                fencing_token=a.fencing_token,
                worker_id=a.worker_id,
                adapter_name=a.adapter_name,
                dispatched_at=_iso(a.dispatched_at),
                result_status=a.result_status,
            )
            for a in history
        ],
    )


@router.post("/{effect_id}/reconcile", response_model=ReconcileResponse)
async def reconcile_effect(
    effect_id: str,
    body: ReconcileRequest,
    db: Session = Depends(get_db),
    scope: ActorScope = Depends(get_current_actor_scope),
):
    """Operator resolves an UNKNOWN_OUTCOME effect to confirmed|failed.

    Refuses anything but UNKNOWN_OUTCOME → terminal (state machine guard),
    and audit-logs the decision with the acting principal.
    """
    if body.final_status not in (EffectStatusDB.CONFIRMED, EffectStatusDB.FAILED):
        raise HTTPException(
            status_code=422,
            detail="final_status must be confirmed or failed",
        )

    journal = EffectJournal(db)
    effect = journal.get_effect(effect_id)
    if effect is None:
        raise HTTPException(status_code=404, detail="Effect not found")

    # Capture attributes before reconcile(): its UPDATE expires ORM state,
    # and post-commit attribute access on the stale instance would detach.
    step_run_for_audit = effect.step_run_id

    try:
        journal.reconcile(
            tenant_id=scope.tenant_id,
            effect_id=effect_id,
            final_status=body.final_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # EffectStateError and friends
        raise HTTPException(status_code=409, detail=str(exc))

    # Audit the reconciliation decision (same-session sync write — the
    # request session must not be smuggled into another thread).
    from packages.agent_core.schemas import AuditEventCreate
    from packages.db.models import AuditEventType
    from packages.db.repositories.audit_repo import AuditRepository
    AuditRepository.create(db, AuditEventCreate(
        task_id=None,
        step_id=step_run_for_audit,
        edition=None,
        event_type=AuditEventType.POLICY_APPROVED,  # closest: operator decision
        actor=scope.principal_id,
        detail={
            "action": "effect_reconciled",
            "effect_id": effect_id,
            "final_status": body.final_status.value,
            "note": body.note,
        },
    ))
    db.commit()

    return ReconcileResponse(
        effect_id=effect_id,
        status=body.final_status.value,
        reconciled=True,
    )
