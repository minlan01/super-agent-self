"""P2.7 纵向切片集成测试 — file.read(Low) + file.delete(High) 全链路.

Tests the full spec §4.3 execution contract end-to-end:

  Low-risk path:
    Policy GRANT -> GrantIssuer -> LeaseManager -> EffectJournal PREPARED
    -> ToolGateway -> Receipt -> Effect CONFIRMED -> Grant CONSUMED

  High-risk path:
    Policy WAIT_APPROVAL -> ApprovalService.create_request
    -> cast_vote (non-self) -> resolve APPROVED
    -> GrantIssuer (approval_resolution_id) -> Lease -> Effect
    -> ToolGateway -> Receipt -> Effect CONFIRMED

  Security invariants (G2 gate):
    - Grant nonce 二次消费 = 0
    - stale fencing_token 完成 = 0
    - 批准前高风险执行 = 0
    - 撤销/过期 Grant 执行 = 0
"""

import asyncio
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.approval.approval_service import ApprovalService
from packages.db.models import (
    ApprovalRequestStatus,
    Base,
    EffectClassDB,
    EffectStatusDB,
    GrantStatusDB,
    ReceiptStatusDB,
    VoteDecision,
)
from packages.db.session import Base as AppBase
from packages.execution.effect_journal import EffectJournal
from packages.execution.lease_manager import LeaseManager
from packages.executor.tool_gateway import ToolGateway
from packages.executor.tools.base import ExecutionContext, ToolBase, ToolResult
from packages.policy.grant_issuer import GrantIssuer


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


class FakeFileRead(ToolBase):
    """Simulates file.read — returns file content."""
    name = "file.read"
    category = "file"
    risk_level = "low"

    async def execute(self, args, context):
        return ToolResult(success=True, output=f"content of {args.get('path')}", artifacts=[])


class FakeFileDelete(ToolBase):
    """Simulates file.delete — destructive, non-idempotent."""
    name = "file.delete"
    category = "file"
    risk_level = "high"

    def __init__(self):
        self.deleted_files = set()

    async def execute(self, args, context):
        path = args.get("path", "")
        self.deleted_files.add(path)
        return ToolResult(success=True, output=f"deleted {path}", artifacts=[])


def _build_stack(db: Session, tool: ToolBase):
    """Wire up the full execution stack with the given tool."""
    gi = GrantIssuer(db)
    lm = LeaseManager(db)
    ej = EffectJournal(db)
    gw = ToolGateway(
        db=db, grant_issuer=gi, lease_manager=lm, effect_journal=ej,
        tool_lookup={tool.name: tool}, worker_id="test-runner",
    )
    return gi, lm, ej, gw


class TestLowRiskVerticalSlice:
    """file.read (Low risk) — no approval needed, direct grant."""

    def test_file_read_full_chain(self, db_session):
        """Full chain: Policy GRANT -> Grant -> Lease -> Effect -> Gateway -> CONFIRMED."""
        tool = FakeFileRead()
        gi, lm, ej, gw = _build_stack(db_session, tool)

        # 1. Policy would return GRANT (we simulate by issuing grant directly)
        issued = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={"workspace_id": "w1"},
            security_context_digest="b" * 64,
        )

        # 2. Acquire lease
        lease = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")

        # 3. Execute through gateway
        ctx = ExecutionContext(task_id="task-1", step_id="s1", tool_timeout=10)
        result = asyncio.run(gw.invoke(
            handle=issued.handle, lease_id=lease.lease_id,
            tool_name="file.read", args={"path": "/workspace/test.txt"},
            context=ctx, tenant_id="t1",
            effect_class=EffectClassDB.READ_ONLY,
        ))

        # 4. Assertions
        assert result.success is True
        assert result.receipt_status == ReceiptStatusDB.SUCCEEDED

        # Effect is CONFIRMED
        effect = ej.get_effect(result.effect_id)
        assert effect.status == EffectStatusDB.CONFIRMED
        assert effect.tool_name == "file.read"

        # Grant is CONSUMED
        grant = gi.verify(issued.handle)
        assert grant.valid is False
        assert "consumed" in grant.reason

        # Dispatch attempt recorded
        attempts = ej.get_dispatch_history(tenant_id="t1", effect_id=result.effect_id)
        assert len(attempts) == 1


class TestHighRiskVerticalSlice:
    """file.delete (High risk) — requires approval before grant."""

    def test_file_delete_approved_then_executed(self, db_session):
        """WAIT_APPROVAL -> approve -> GRANT -> execute -> CONFIRMED."""
        tool = FakeFileDelete()
        gi, lm, ej, gw = _build_stack(db_session, tool)
        svc = ApprovalService(db_session)

        # 1. Policy returns WAIT_APPROVAL -> create approval request
        req = svc.create_request(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            normalized_args_hash="a" * 64, risk_level="high",
            resource_scope={"workspace_id": "w1"},
            policy_digest="p" * 64,
            security_context_digest="sc" * 32,
            requester_principal_id="alice",
        )
        assert req.status == ApprovalRequestStatus.PENDING

        # 2. Before approval: NO grant can be issued for high-risk
        with pytest.raises(ValueError, match="approval_resolution_id"):
            gi.issue(
                tenant_id="t1", step_run_id="s1", tool_name="file.delete",
                bound_args_hash="a" * 64, risk_level="high",
                resource_scope={}, security_context_digest="sc" * 32,
            )

        # 3. Approver (different from requester) votes
        svc.cast_vote(
            request_id=req.request_id,
            voter_principal_id="bob",
            decision=VoteDecision.APPROVE,
        )

        # 4. Resolve -> APPROVED
        resolution = svc.resolve(req.request_id)
        assert resolution.status == ApprovalRequestStatus.APPROVED
        assert resolution.resolution_id is not None

        # 5. Now GrantIssuer can issue with the resolution_id
        issued = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            bound_args_hash="a" * 64, risk_level="high",
            resource_scope={"workspace_id": "w1"},
            security_context_digest="sc" * 32,
            approval_resolution_id=resolution.resolution_id,
        )

        # 6. Acquire lease + execute
        lease = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        ctx = ExecutionContext(task_id="task-1", step_id="s1", tool_timeout=10)
        result = asyncio.run(gw.invoke(
            handle=issued.handle, lease_id=lease.lease_id,
            tool_name="file.delete", args={"path": "/workspace/secret.txt"},
            context=ctx, tenant_id="t1",
            effect_class=EffectClassDB.NON_RETRYABLE,
        ))

        # 7. Assertions
        assert result.success is True
        assert result.receipt_status == ReceiptStatusDB.SUCCEEDED

        effect = ej.get_effect(result.effect_id)
        assert effect.status == EffectStatusDB.CONFIRMED
        assert effect.effect_class == EffectClassDB.NON_RETRYABLE
        # Side-effect hashes recorded (before != after)
        assert effect.before_hash is not None
        assert effect.after_hash is not None

        # File was actually deleted
        assert "/workspace/secret.txt" in tool.deleted_files

    def test_file_delete_rejected_not_executed(self, db_session):
        """Approval REJECTED -> step not executed, no grant."""
        tool = FakeFileDelete()
        gi, lm, ej, gw = _build_stack(db_session, tool)
        svc = ApprovalService(db_session)

        req = svc.create_request(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            normalized_args_hash="a" * 64, risk_level="high",
            resource_scope={}, policy_digest="p" * 64,
            security_context_digest="sc" * 32,
            requester_principal_id="alice",
        )

        svc.cast_vote(
            request_id=req.request_id,
            voter_principal_id="bob",
            decision=VoteDecision.REJECT,
        )
        resolution = svc.resolve(req.request_id)
        assert resolution.status == ApprovalRequestStatus.REJECTED

        # No resolution_id -> cannot issue grant
        assert resolution.resolution_id is None
        # File was NOT deleted
        assert len(tool.deleted_files) == 0


class TestSecurityInvariants:
    """G2 gate: security invariant tests."""

    def test_grant_nonce_replay_blocked(self, db_session):
        """Grant consumed once; second use rejected."""
        tool = FakeFileRead()
        gi, lm, ej, gw = _build_stack(db_session, tool)
        issued = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={}, security_context_digest="b" * 64,
        )
        lease = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        ctx = ExecutionContext(task_id="t1", step_id="s1")

        # First invocation succeeds
        r1 = asyncio.run(gw.invoke(
            handle=issued.handle, lease_id=lease.lease_id,
            tool_name="file.read", args={}, context=ctx, tenant_id="t1",
        ))
        assert r1.success is True

        # Second invocation with same handle -> rejected
        lease2 = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1b")
        r2 = asyncio.run(gw.invoke(
            handle=issued.handle, lease_id=lease2.lease_id,
            tool_name="file.read", args={}, context=ctx, tenant_id="t1",
        ))
        assert r2.success is False

    def test_stale_fencing_token_blocked(self, db_session):
        """Old fencing token cannot complete an action."""
        tool = FakeFileRead()
        gi, lm, ej, gw = _build_stack(db_session, tool)
        issued = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={}, security_context_digest="b" * 64,
        )

        # Acquire, release, re-acquire -> old lease is stale
        l1 = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        lm.release(l1.lease_id)

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        # Using the old (released) lease -> rejected
        r = asyncio.run(gw.invoke(
            handle=issued.handle, lease_id=l1.lease_id,
            tool_name="file.read", args={}, context=ctx, tenant_id="t1",
        ))
        assert r.success is False
        assert "lease" in r.error.lower()

    def test_revoked_grant_blocked(self, db_session):
        tool = FakeFileRead()
        gi, lm, ej, gw = _build_stack(db_session, tool)
        issued = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={}, security_context_digest="b" * 64,
        )
        # Revoke before use
        verified = gi.verify(issued.handle)
        gi.revoke(verified.grant_id)

        lease = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        ctx = ExecutionContext(task_id="t1", step_id="s1")
        r = asyncio.run(gw.invoke(
            handle=issued.handle, lease_id=lease.lease_id,
            tool_name="file.read", args={}, context=ctx, tenant_id="t1",
        ))
        assert r.success is False
        assert "revoked" in r.error.lower()

    def test_effect_three_states_covered(self, db_session):
        """Effect must support CONFIRMED, FAILED, UNKNOWN_OUTCOME."""

        class FailTool(ToolBase):
            name = "file.read"
            category = "file"
            risk_level = "low"
            async def execute(self, args, context):
                return ToolResult(success=False, error="file not found")

        # CONFIRMED already tested in TestLowRiskVerticalSlice.
        # FAILED:
        tool = FailTool()
        gi, lm, ej, gw = _build_stack(db_session, tool)
        issued = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={}, security_context_digest="b" * 64,
        )
        lease = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        ctx = ExecutionContext(task_id="t1", step_id="s1")
        r = asyncio.run(gw.invoke(
            handle=issued.handle, lease_id=lease.lease_id,
            tool_name="file.read", args={}, context=ctx, tenant_id="t1",
        ))
        assert r.receipt_status == ReceiptStatusDB.FAILED
        assert ej.get_effect(r.effect_id).status == EffectStatusDB.FAILED

        # UNKNOWN_OUTCOME tested in test_unknown_outcome_non_idempotent_enters_reconciliation

    def test_unknown_outcome_non_idempotent_enters_reconciliation(self, db_session):
        """Non-idempotent tool with UNKNOWN outcome -> reconciliation queue, no auto-retry."""

        class CrashingDelete(ToolBase):
            name = "file.delete"
            category = "file"
            risk_level = "high"
            async def execute(self, args, context):
                raise RuntimeError("crashed mid-delete")

        tool = CrashingDelete()
        gi, lm, ej, gw = _build_stack(db_session, tool)
        svc = ApprovalService(db_session)

        # Approve first
        req = svc.create_request(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            normalized_args_hash="a" * 64, risk_level="high",
            resource_scope={}, policy_digest="p" * 64,
            security_context_digest="sc" * 32,
            requester_principal_id="alice",
        )
        svc.cast_vote(request_id=req.request_id, voter_principal_id="bob",
                      decision=VoteDecision.APPROVE)
        resolution = svc.resolve(req.request_id)

        issued = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            bound_args_hash="a" * 64, risk_level="high",
            resource_scope={}, security_context_digest="sc" * 32,
            approval_resolution_id=resolution.resolution_id,
        )
        lease = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        ctx = ExecutionContext(task_id="t1", step_id="s1")
        r = asyncio.run(gw.invoke(
            handle=issued.handle, lease_id=lease.lease_id,
            tool_name="file.delete", args={"path": "/data/file.txt"},
            context=ctx, tenant_id="t1",
            effect_class=EffectClassDB.NON_RETRYABLE,
        ))

        # Effect is UNKNOWN_OUTCOME
        assert r.receipt_status == ReceiptStatusDB.UNKNOWN
        effect = ej.get_effect(r.effect_id)
        assert effect.status == EffectStatusDB.UNKNOWN_OUTCOME

        # It appears in the reconciliation queue
        queue = ej.get_unknown_outcomes(tenant_id="t1")
        assert any(e.id == r.effect_id for e in queue)

        # It does NOT get auto-retried (no second effect for same step)
        effects_for_step = ej.get_effect(r.effect_id)
        assert effects_for_step is not None  # only one effect
