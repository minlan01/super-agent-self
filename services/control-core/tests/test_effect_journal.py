"""Tests for EffectJournal (P2.4) — state machine, dispatch trace, terminal immutability."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import (
    Base,
    EffectClassDB,
    EffectStatusDB,
    ReceiptStatusDB,
)
from packages.db.session import Base as AppBase
from packages.execution.effect_journal import EffectJournal, EffectStateError


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _create_grant_and_lease(db: Session) -> tuple[str, str]:
    """Helper: create a minimal grant + lease row for effect FK references."""
    from packages.db.models import CapabilityGrantModel, LeaseModel
    from datetime import UTC, datetime, timedelta
    now = datetime.now(UTC)
    grant = CapabilityGrantModel(
        tenant_id="t1", step_run_id="s1", handle_digest="h" * 64,
        nonce="n" * 16, bound_args_hash="a" * 64, risk_level="low",
        resource_scope={}, security_context_digest="sc" * 32,
        status="issued", issued_at=now, expires_at=now + timedelta(hours=1),
        max_uses=1,
    )
    lease = LeaseModel(
        tenant_id="t1", worker_id="w1", step_run_id="s1",
        fencing_token=1, status="active",
        expires_at=now + timedelta(hours=1),
    )
    db.add_all([grant, lease])
    db.flush()
    return grant.id, lease.id


class TestEffectJournal:
    def _journal(self, db: Session) -> EffectJournal:
        return EffectJournal(db)

    def test_prepare_creates_prepared_effect(self, db_session):
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)
        result = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=1, tool_name="file.read",
            effect_class=EffectClassDB.READ_ONLY,
            security_context_digest="sc" * 32,
        )
        assert result.status == EffectStatusDB.PREPARED
        assert result.effect_id is not None

    def test_full_happy_path_prepared_dispatching_confirmed(self, db_session):
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)

        # 1. PREPARE
        prep = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=1, tool_name="file.read",
            effect_class=EffectClassDB.READ_ONLY,
            security_context_digest="sc" * 32,
        )

        # 2. DISPATCH
        ej.record_dispatch(
            tenant_id="t1", effect_id=prep.effect_id,
            lease_id=lease_id, fencing_token=1,
            grant_digest="h" * 64, worker_id="w1",
            adapter_name="FileAdapter",
        )
        effect = ej.get_effect(prep.effect_id)
        assert effect.status == EffectStatusDB.DISPATCHING

        # 3. FINALIZE (succeeded)
        ej.finalize(
            tenant_id="t1", effect_id=prep.effect_id,
            receipt_status=ReceiptStatusDB.SUCCEEDED,
            result={"content": "hello"},
            tool_name="file.read",
            args_hash="a" * 64,
        )
        effect = ej.get_effect(prep.effect_id)
        assert effect.status == EffectStatusDB.CONFIRMED
        assert effect.finalized_at is not None

    def test_failed_receipt_transitions_to_failed(self, db_session):
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)
        prep = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=1, tool_name="file.read",
            effect_class=EffectClassDB.READ_ONLY,
            security_context_digest="sc" * 32,
        )
        ej.record_dispatch(
            tenant_id="t1", effect_id=prep.effect_id,
            lease_id=lease_id, fencing_token=1,
            grant_digest="h" * 64, worker_id="w1",
            adapter_name="FileAdapter",
        )
        ej.finalize(
            tenant_id="t1", effect_id=prep.effect_id,
            receipt_status=ReceiptStatusDB.FAILED,
            error_code="FILE_NOT_FOUND",
            error_message="No such file",
            tool_name="file.read", args_hash="a" * 64,
        )
        assert ej.get_effect(prep.effect_id).status == EffectStatusDB.FAILED

    def test_unknown_receipt_transitions_to_unknown_outcome(self, db_session):
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)
        prep = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=1, tool_name="file.delete",
            effect_class=EffectClassDB.NON_RETRYABLE,
            security_context_digest="sc" * 32,
        )
        ej.record_dispatch(
            tenant_id="t1", effect_id=prep.effect_id,
            lease_id=lease_id, fencing_token=1,
            grant_digest="h" * 64, worker_id="w1",
            adapter_name="FileAdapter",
        )
        ej.finalize(
            tenant_id="t1", effect_id=prep.effect_id,
            receipt_status=ReceiptStatusDB.UNKNOWN,
            tool_name="file.delete", args_hash="a" * 64,
        )
        assert ej.get_effect(prep.effect_id).status == EffectStatusDB.UNKNOWN_OUTCOME

    def test_terminal_state_is_immutable(self, db_session):
        """CONFIRMED/FAILED/UNKNOWN cannot transition back."""
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)
        prep = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=1, tool_name="file.read",
            effect_class=EffectClassDB.READ_ONLY,
            security_context_digest="sc" * 32,
        )
        ej.record_dispatch(
            tenant_id="t1", effect_id=prep.effect_id,
            lease_id=lease_id, fencing_token=1,
            grant_digest="h" * 64, worker_id="w1",
            adapter_name="FileAdapter",
        )
        # Finalize as CONFIRMED
        ej.finalize(
            tenant_id="t1", effect_id=prep.effect_id,
            receipt_status=ReceiptStatusDB.SUCCEEDED,
            tool_name="file.read", args_hash="a" * 64,
        )
        # Attempt to re-finalize as FAILED -> should NOT change state
        ej.finalize(
            tenant_id="t1", effect_id=prep.effect_id,
            receipt_status=ReceiptStatusDB.FAILED,
            tool_name="file.read", args_hash="a" * 64,
        )
        # Still CONFIRMED (terminal immutability)
        assert ej.get_effect(prep.effect_id).status == EffectStatusDB.CONFIRMED

    def test_dispatch_attempt_persists_audit_fields(self, db_session):
        """Each dispatch must persist effect_id, lease_id, fencing_token, etc."""
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)
        prep = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=42, tool_name="file.read",
            effect_class=EffectClassDB.READ_ONLY,
            security_context_digest="sc" * 32,
        )
        ej.record_dispatch(
            tenant_id="t1", effect_id=prep.effect_id,
            lease_id=lease_id, fencing_token=42,
            grant_digest="hd" * 32, worker_id="worker-abc",
            adapter_name="FileAdapter",
        )
        history = ej.get_dispatch_history(tenant_id="t1", effect_id=prep.effect_id)
        assert len(history) == 1
        att = history[0]
        assert att.fencing_token == 42
        assert att.worker_id == "worker-abc"
        assert att.adapter_name == "FileAdapter"
        assert att.grant_digest == "hd" * 32
        assert att.lease_id == lease_id

    def test_get_unknown_outcomes_returns_queue(self, db_session):
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)
        prep = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=1, tool_name="file.delete",
            effect_class=EffectClassDB.NON_RETRYABLE,
            security_context_digest="sc" * 32,
        )
        ej.record_dispatch(
            tenant_id="t1", effect_id=prep.effect_id,
            lease_id=lease_id, fencing_token=1,
            grant_digest="h" * 64, worker_id="w1",
            adapter_name="FileAdapter",
        )
        ej.finalize(
            tenant_id="t1", effect_id=prep.effect_id,
            receipt_status=ReceiptStatusDB.UNKNOWN,
            tool_name="file.delete", args_hash="a" * 64,
        )
        queue = ej.get_unknown_outcomes(tenant_id="t1")
        assert len(queue) == 1
        assert queue[0].status == EffectStatusDB.UNKNOWN_OUTCOME

    def test_reconcile_unknown_to_confirmed(self, db_session):
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)
        prep = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=1, tool_name="file.delete",
            effect_class=EffectClassDB.NON_RETRYABLE,
            security_context_digest="sc" * 32,
        )
        ej.record_dispatch(
            tenant_id="t1", effect_id=prep.effect_id,
            lease_id=lease_id, fencing_token=1,
            grant_digest="h" * 64, worker_id="w1",
            adapter_name="FileAdapter",
        )
        ej.finalize(
            tenant_id="t1", effect_id=prep.effect_id,
            receipt_status=ReceiptStatusDB.UNKNOWN,
            tool_name="file.delete", args_hash="a" * 64,
        )
        # Operator reconciles
        ej.reconcile(
            tenant_id="t1", effect_id=prep.effect_id,
            final_status=EffectStatusDB.CONFIRMED,
        )
        assert ej.get_effect(prep.effect_id).status == EffectStatusDB.CONFIRMED

    def test_reconcile_non_unknown_rejected(self, db_session):
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)
        prep = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=1, tool_name="file.read",
            effect_class=EffectClassDB.READ_ONLY,
            security_context_digest="sc" * 32,
        )
        ej.record_dispatch(
            tenant_id="t1", effect_id=prep.effect_id,
            lease_id=lease_id, fencing_token=1,
            grant_digest="h" * 64, worker_id="w1",
            adapter_name="FileAdapter",
        )
        ej.finalize(
            tenant_id="t1", effect_id=prep.effect_id,
            receipt_status=ReceiptStatusDB.SUCCEEDED,
            tool_name="file.read", args_hash="a" * 64,
        )
        # Cannot reconcile from CONFIRMED
        with pytest.raises(EffectStateError):
            ej.reconcile(
                tenant_id="t1", effect_id=prep.effect_id,
                final_status=EffectStatusDB.FAILED,
            )

    def test_before_after_hashes_recorded(self, db_session):
        grant_id, lease_id = _create_grant_and_lease(db_session)
        ej = self._journal(db_session)
        prep = ej.prepare(
            tenant_id="t1", step_run_id="s1",
            grant_id=grant_id, lease_id=lease_id,
            fencing_token=1, tool_name="file.delete",
            effect_class=EffectClassDB.NON_RETRYABLE,
            security_context_digest="sc" * 32,
        )
        ej.record_dispatch(
            tenant_id="t1", effect_id=prep.effect_id,
            lease_id=lease_id, fencing_token=1,
            grant_digest="h" * 64, worker_id="w1",
            adapter_name="FileAdapter",
        )
        ej.finalize(
            tenant_id="t1", effect_id=prep.effect_id,
            receipt_status=ReceiptStatusDB.SUCCEEDED,
            before_hash="before123".ljust(64, "0"),
            after_hash="after456".ljust(64, "0"),
            tool_name="file.delete", args_hash="a" * 64,
        )
        effect = ej.get_effect(prep.effect_id)
        assert effect.before_hash is not None
        assert effect.after_hash is not None
        assert effect.before_hash != effect.after_hash
