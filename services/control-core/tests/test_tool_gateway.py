"""Tests for ToolGateway (P2.5) — sole entry point, full security chain."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import (
    Base,
    EffectClassDB,
    EffectStatusDB,
    GrantStatusDB,
    ReceiptStatusDB,
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


class FakeTool(ToolBase):
    """A controllable fake tool for testing."""
    name = "file.read"
    description = "fake read"
    category = "file"
    risk_level = "low"

    def __init__(self, result: ToolResult | None = None):
        self._result = result or ToolResult(success=True, output="ok", artifacts=[])
        self.invoked = False

    async def execute(self, args, context):
        self.invoked = True
        return self._result


class FailingTool(ToolBase):
    name = "file.read"
    description = "always fails"
    category = "file"
    risk_level = "low"

    async def execute(self, args, context):
        return ToolResult(success=False, output="", error="File not found", artifacts=[])


class CrashingTool(ToolBase):
    name = "file.read"
    description = "crashes"
    category = "file"
    risk_level = "low"

    async def execute(self, args, context):
        raise RuntimeError("Adapter exploded")


def _setup_gateway(db: Session, tool: ToolBase) -> tuple[ToolGateway, GrantIssuer, LeaseManager]:
    """Set up a fully wired ToolGateway with grant/lease/effect managers."""
    gi = GrantIssuer(db)
    lm = LeaseManager(db)
    ej = EffectJournal(db)
    gateway = ToolGateway(
        db=db,
        grant_issuer=gi,
        lease_manager=lm,
        effect_journal=ej,
        tool_lookup={"file.read": tool},
        worker_id="test-worker",
    )
    return gateway, gi, lm


def _issue_grant_and_lease(gi, lm, db, risk="low"):
    """Helper: issue a grant + acquire a lease, return (handle, lease_id)."""
    issued = gi.issue(
        tenant_id="t1", step_run_id="s1", tool_name="file.read",
        bound_args_hash="a" * 64, risk_level=risk,
        resource_scope={}, security_context_digest="b" * 64,
        approval_resolution_id="res-1" if risk in ("high", "critical") else None,
    )
    lease = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
    return issued.handle, lease.lease_id, lease.fencing_token


class TestToolGateway:
    def test_successful_invocation_full_chain(self, db_session):
        """file.read(Low): grant -> lease -> effect -> adapter -> CONFIRMED."""
        tool = FakeTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        handle, lease_id, _ = _issue_grant_and_lease(gi, lm, db_session)

        ctx = ExecutionContext(task_id="t1", step_id="s1", tool_timeout=10)
        result = pytest.run_coroutine_as_async = None  # placeholder

        import asyncio
        result = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={"path": "/tmp/test.txt"},
            context=ctx, tenant_id="t1",
        ))

        assert result.success is True
        assert result.receipt_status == ReceiptStatusDB.SUCCEEDED
        assert result.effect_id is not None
        assert tool.invoked is True

        # Effect should be CONFIRMED
        ej = EffectJournal(db_session)
        effect = ej.get_effect(result.effect_id)
        assert effect.status == EffectStatusDB.CONFIRMED

        # Grant should be CONSUMED
        from packages.db.repositories.grant_repo import GrantRepository
        grant = GrantRepository.get_by_handle_digest(
            db_session, gi._digest(handle),
        )
        assert grant.status == GrantStatusDB.CONSUMED

    def test_invalid_handle_rejected(self, db_session):
        """Unknown handle -> rejected, no Effect, no invocation."""
        tool = FakeTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        lease = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        import asyncio
        result = asyncio.run(gw.invoke(
            handle="invalid-handle", lease_id=lease.lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))

        assert result.success is False
        assert "Grant rejected" in result.error
        assert tool.invoked is False

    def test_consumed_grant_rejected(self, db_session):
        """Already-consumed grant -> rejected (nonce replay protection)."""
        tool = FakeTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        handle, lease_id, _ = _issue_grant_and_lease(gi, lm, db_session)

        # Pre-consume the grant
        gi.consume(handle)

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        import asyncio
        result = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))

        assert result.success is False
        assert "consumed" in result.error.lower()
        assert tool.invoked is False

    def test_revoked_grant_rejected(self, db_session):
        tool = FakeTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        handle, lease_id, _ = _issue_grant_and_lease(gi, lm, db_session)

        # Revoke the grant
        verified = gi.verify(handle)
        gi.revoke(verified.grant_id)

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        import asyncio
        result = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))

        assert result.success is False
        assert "revoked" in result.error.lower()

    def test_invalid_lease_rejected(self, db_session):
        """Released lease -> rejected, no Effect."""
        tool = FakeTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        handle, lease_id, _ = _issue_grant_and_lease(gi, lm, db_session)

        # Release the lease
        lm.release(lease_id)

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        import asyncio
        result = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))

        assert result.success is False
        assert "lease" in result.error.lower()
        assert tool.invoked is False

    def test_stale_fencing_token_rejected(self, db_session):
        """Old fencing token (from superseded lease) -> rejected."""
        tool = FakeTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        handle, lease_id, token1 = _issue_grant_and_lease(gi, lm, db_session)

        # Release and re-acquire -> new fencing_token (token2 > token1)
        lm.release(lease_id)
        l2 = lm.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        assert l2.fencing_token > token1

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        # Old lease_id is now inactive -> rejected
        import asyncio
        result = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))
        assert result.success is False
        assert "lease" in result.error.lower()

    def test_tool_failure_transitions_to_failed(self, db_session):
        tool = FailingTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        handle, lease_id, _ = _issue_grant_and_lease(gi, lm, db_session)

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        import asyncio
        result = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))

        assert result.success is False
        assert result.receipt_status == ReceiptStatusDB.FAILED

        ej = EffectJournal(db_session)
        effect = ej.get_effect(result.effect_id)
        assert effect.status == EffectStatusDB.FAILED

    def test_adapter_crash_transitions_to_unknown(self, db_session):
        """Adapter exception -> UNKNOWN_OUTCOME (we don't know if it executed)."""
        tool = CrashingTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        handle, lease_id, _ = _issue_grant_and_lease(gi, lm, db_session)

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        import asyncio
        result = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))

        assert result.success is False
        # Crash -> unknown outcome (not failed, because we don't know)
        assert result.receipt_status == ReceiptStatusDB.UNKNOWN

        ej = EffectJournal(db_session)
        effect = ej.get_effect(result.effect_id)
        assert effect.status == EffectStatusDB.UNKNOWN_OUTCOME

    def test_grant_consumed_exactly_once(self, db_session):
        """Double invocation with same handle: second must fail."""
        tool = FakeTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        handle, lease_id, _ = _issue_grant_and_lease(gi, lm, db_session)

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        import asyncio
        r1 = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))
        assert r1.success is True

        # Second invocation with same handle -> grant consumed
        r2 = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))
        assert r2.success is False
        assert "consumed" in r2.error.lower() or "grant" in r2.error.lower()

    def test_effect_recorded_before_invocation(self, db_session):
        """Effect must be in PREPARED state before the adapter runs.

        We verify this indirectly: if the tool crashes, an Effect record
        still exists (it was created before invocation).
        """
        tool = CrashingTool()
        gw, gi, lm = _setup_gateway(db_session, tool)
        handle, lease_id, _ = _issue_grant_and_lease(gi, lm, db_session)

        ctx = ExecutionContext(task_id="t1", step_id="s1")
        import asyncio
        result = asyncio.run(gw.invoke(
            handle=handle, lease_id=lease_id,
            tool_name="file.read", args={},
            context=ctx, tenant_id="t1",
        ))

        # Even though adapter crashed, Effect exists and is in a terminal state
        assert result.effect_id is not None
        ej = EffectJournal(db_session)
        effect = ej.get_effect(result.effect_id)
        assert effect is not None
        # Should have dispatch attempts recorded
        attempts = ej.get_dispatch_history(tenant_id="t1", effect_id=result.effect_id)
        assert len(attempts) >= 1
