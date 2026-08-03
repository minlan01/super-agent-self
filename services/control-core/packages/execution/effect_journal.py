"""EffectJournal — side-effect protocol record state machine.

Spec §4.3 + v3 M9 + PROJECT-CONTEXT §外部副作用与恢复不变量:

  State machine:
    PREPARED -> DISPATCHING -> CONFIRMED | FAILED | UNKNOWN_OUTCOME
                                          (terminal, irreversible)
    UNKNOWN_OUTCOME -> RECONCILED         (manual reconciliation, terminal)

  Key invariants:
    - EffectRecord must be persisted (PREPARED) BEFORE adapter invocation.
    - Every dispatch attempt persists: effect_id, attempt_ordinal, lease_id,
      fencing_token, grant_digest, worker_id, adapter_name, dispatched_at.
    - UNKNOWN_OUTCOME on non-idempotent effects -> reconciliation queue,
      NO auto-replay.
    - EffectJournal does NOT close Leases (WorkerBroker owns that).
    - Terminal states are irreversible (enforced by EffectRepository).

  "No ToolReceipt" does NOT imply "tool did not execute" — only Effect
  status and the tool's idempotency contract determine whether a retry
  is safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from packages.db.models import (
    EffectClassDB,
    EffectStatusDB,
    ReceiptStatusDB,
)
from packages.db.repositories.dispatch_repo import DispatchAttemptRepository
from packages.db.repositories.effect_repo import EffectRepository
from packages.db.repositories.receipt_repo import ReceiptRepository

logger = structlog.get_logger()


@dataclass(frozen=True)
class PreparedEffect:
    """Result of prepare(): the effect ID for the caller to track."""
    effect_id: str
    step_run_id: str
    grant_id: str
    lease_id: str
    fencing_token: int
    status: EffectStatusDB


class EffectJournal:
    """Owns the effect_records + dispatch_attempts + tool_receipts write path.

    Does NOT own: leases (LeaseManager), grants (GrantRepository).
    Does NOT close leases or grants — only transitions its own Effect state.
    """

    def __init__(self, db: Session):
        self.db = db

    def prepare(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
        grant_id: str,
        lease_id: str,
        fencing_token: int,
        tool_name: str,
        effect_class: EffectClassDB,
        security_context_digest: str,
        provider_idempotency_key: str | None = None,
    ) -> PreparedEffect:
        """Create an EffectRecord in PREPARED state before adapter invocation.

        This must be called BEFORE the adapter runs, so that even if the
        adapter crashes immediately, there is a durable record proving we
        INTENDED to dispatch (spec §外部副作用与恢复不变量).
        """
        effect = EffectRepository.create(
            self.db,
            tenant_id=tenant_id,
            step_run_id=step_run_id,
            grant_id=grant_id,
            lease_id=lease_id,
            fencing_token=fencing_token,
            status=EffectStatusDB.PREPARED,
            effect_class=effect_class,
            tool_name=tool_name,
            provider_idempotency_key=provider_idempotency_key,
            security_context_digest=security_context_digest,
            before_hash=None,   # set by ToolGateway for side-effects
            after_hash=None,
            created_at=datetime.now(UTC),
        )

        logger.info(
            "Effect PREPARED: effect=%s step=%s tool=%s class=%s",
            effect.id, step_run_id, tool_name, effect_class.value,
        )

        return PreparedEffect(
            effect_id=effect.id,
            step_run_id=step_run_id,
            grant_id=grant_id,
            lease_id=lease_id,
            fencing_token=fencing_token,
            status=EffectStatusDB.PREPARED,
        )

    def record_dispatch(
        self,
        *,
        tenant_id: str,
        effect_id: str,
        lease_id: str,
        fencing_token: int,
        grant_digest: str,
        worker_id: str,
        adapter_name: str,
    ) -> Any:
        """Transition PREPARED -> DISPATCHING and append a dispatch attempt.

        The dispatch_attempt row is the audit-grade trace required by
        PROJECT-CONTEXT: effect_id, attempt_ordinal, lease_id, fencing_token,
        grant_digest, worker_id, adapter_name, dispatched_at.
        """
        # Transition to DISPATCHING (PREPARED is the only valid source state).
        effect = EffectRepository.update_status(
            self.db, effect_id, EffectStatusDB.DISPATCHING,
        )
        if effect is None:
            raise ValueError(f"effect {effect_id} not found")

        if effect.status != EffectStatusDB.DISPATCHING:
            # update_status rejected the transition (already terminal).
            raise EffectStateError(
                f"effect {effect_id} is in state {effect.status}, "
                f"cannot transition to DISPATCHING"
            )

        # Append dispatch attempt.
        ordinal = DispatchAttemptRepository.next_ordinal(self.db, effect_id=effect_id)
        attempt = DispatchAttemptRepository.create(
            self.db,
            tenant_id=tenant_id,
            effect_id=effect_id,
            attempt_ordinal=ordinal,
            lease_id=lease_id,
            fencing_token=fencing_token,
            grant_digest=grant_digest,
            worker_id=worker_id,
            adapter_name=adapter_name,
            dispatched_at=datetime.now(UTC),
        )

        logger.info(
            "Effect DISPATCHING: effect=%s attempt=%d lease=%s token=%d adapter=%s",
            effect_id, ordinal, lease_id, fencing_token, adapter_name,
        )
        return attempt

    def finalize(
        self,
        *,
        tenant_id: str,
        effect_id: str,
        receipt_status: ReceiptStatusDB,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        content_provenance: str | None = None,
        before_hash: str | None = None,
        after_hash: str | None = None,
        tool_name: str = "",
        args_hash: str = "",
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> Any:
        """Record the ToolReceipt and transition Effect to terminal state.

        Mapping (spec §4.3):
          receipt SUCCEEDED -> Effect CONFIRMED
          receipt FAILED    -> Effect FAILED
          receipt UNKNOWN   -> Effect UNKNOWN_OUTCOME

        Terminal states are irreversible (enforced by EffectRepository).
        """
        now = datetime.now(UTC)

        # 1. Persist the ToolReceipt (always, even on unknown).
        ReceiptRepository.create(
            self.db,
            tenant_id=tenant_id,
            effect_id=effect_id,
            tool_name=tool_name,
            args_hash=args_hash,
            status=receipt_status,
            result=result,
            error_code=error_code,
            error_message=error_message,
            content_provenance=content_provenance,
            started_at=started_at or now,
            ended_at=ended_at or now,
        )

        # 2. Update before/after hashes (for side-effect verification).
        if before_hash is not None or after_hash is not None:
            EffectRepository.set_hashes(
                self.db, effect_id,
                before_hash=before_hash, after_hash=after_hash,
            )

        # 3. Map receipt status to effect terminal status.
        status_map = {
            ReceiptStatusDB.SUCCEEDED: EffectStatusDB.CONFIRMED,
            ReceiptStatusDB.FAILED: EffectStatusDB.FAILED,
            ReceiptStatusDB.UNKNOWN: EffectStatusDB.UNKNOWN_OUTCOME,
        }
        effect_status = status_map[receipt_status]

        effect = EffectRepository.update_status(self.db, effect_id, effect_status)

        # 4. Update dispatch attempt result_status (latest attempt).
        latest = DispatchAttemptRepository.get_latest(
            self.db, tenant_id=tenant_id, effect_id=effect_id,
        )
        if latest is not None:
            DispatchAttemptRepository.set_result(
                self.db, latest.id, receipt_status.value,
            )

        logger.info(
            "Effect %s: effect=%s receipt=%s",
            effect_status.value, effect_id, receipt_status.value,
        )
        return effect

    def reconcile(
        self,
        *,
        tenant_id: str,
        effect_id: str,
        final_status: EffectStatusDB,
    ) -> Any:
        """Manually reconcile an UNKNOWN_OUTCOME effect (operator action).

        Only allowed from UNKNOWN_OUTCOME -> CONFIRMED | FAILED.
        Not allowed for arbitrary transitions (terminal states are immutable).
        """
        effect = EffectRepository.get_by_id(self.db, effect_id)
        if effect is None:
            raise ValueError(f"effect {effect_id} not found")
        if effect.status != EffectStatusDB.UNKNOWN_OUTCOME:
            raise EffectStateError(
                f"effect {effect_id} is {effect.status}, "
                f"reconcile only allowed from UNKNOWN_OUTCOME"
            )
        if final_status not in (EffectStatusDB.CONFIRMED, EffectStatusDB.FAILED):
            raise ValueError(
                f"reconcile target must be CONFIRMED or FAILED, got {final_status}"
            )

        return EffectRepository.update_status(self.db, effect_id, final_status)

    def get_unknown_outcomes(self, *, tenant_id: str) -> list[Any]:
        """Get all UNKNOWN_OUTCOME effects (reconciliation queue)."""
        return EffectRepository.get_unknown_outcomes(self.db, tenant_id=tenant_id)

    def get_dispatch_history(self, *, tenant_id: str, effect_id: str) -> list[Any]:
        """Get all dispatch attempts for an effect (audit trail)."""
        return DispatchAttemptRepository.get_by_effect(
            self.db, tenant_id=tenant_id, effect_id=effect_id,
        )

    def get_effect(self, effect_id: str) -> Any:
        """Read-only access to an effect record."""
        return EffectRepository.get_by_id(self.db, effect_id)


class EffectStateError(Exception):
    """Raised when an illegal Effect state transition is attempted."""
