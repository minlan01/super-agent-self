"""Tests for ExecutionOrchestrator (P3.1) — P2 chain integration with executor."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import Base
from packages.db.session import Base as AppBase
from packages.execution.orchestrator import ExecutionOrchestrator, StepExecutionResult
from packages.executor.tools.base import ToolBase, ToolResult
from packages.policy.capability_token import TokenIssuer
from packages.policy.policy_engine import PolicyEngine
from packages.policy.unified_registry import UnifiedToolRegistry


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


class FakeReadTool(ToolBase):
    name = "file.read"
    description = "read"
    category = "file"
    risk_level = "low"
    enabled = True

    async def execute(self, args, context):
        return ToolResult(success=True, output=f"read {args.get('path', '')}")


class FakeDeleteTool(ToolBase):
    name = "file.delete"
    description = "delete"
    category = "file"
    risk_level = "high"
    enabled = True

    def __init__(self):
        self.deleted = []

    async def execute(self, args, context):
        self.deleted.append(args.get("path"))
        return ToolResult(success=True, output="deleted")


def _build_orchestrator(db: Session, tools: dict[str, ToolBase]) -> ExecutionOrchestrator:
    """Build a full orchestrator wired with in-memory DB."""
    from packages.execution.effect_journal import EffectJournal
    from packages.execution.lease_manager import LeaseManager
    from packages.executor.tool_gateway import ToolGateway
    from packages.policy.grant_issuer import GrantIssuer

    # Simple in-memory registry that satisfies policy_engine's interface.
    class SimpleRegistry:
        def __init__(self, tools_dict):
            self._tools = tools_dict
        def get_tool(self, name):
            t = self._tools.get(name)
            if t is None:
                return None
            # Return a lightweight object with the attributes policy_engine reads.
            class _Meta:
                pass
            m = _Meta()
            m.enabled = t.enabled
            m.risk_level = t.risk_level
            m.category = getattr(t, "category", "")
            m.name = t.name
            m.check_fn = getattr(t, "check_fn", None)
            return m
        def is_available_for_edition(self, name, edition):
            return name in self._tools
        def get_tool_instance(self, name, **kw):
            return self._tools.get(name)

    registry = SimpleRegistry(tools)
    token_issuer = TokenIssuer("test-secret-key-for-testing-only")
    policy_engine = PolicyEngine(registry, token_issuer)

    def _make_gateway(session):
        return ToolGateway(
            db=session,
            grant_issuer=GrantIssuer(session),
            lease_manager=LeaseManager(session),
            effect_journal=EffectJournal(session),
            tool_lookup=registry,
        )

    return ExecutionOrchestrator(
        policy_engine=policy_engine,
        tool_gateway_factory=_make_gateway,
    )


class TestExecutionOrchestrator:
    def test_low_risk_step_completes(self, db_session):
        """file.read (low risk) -> GRANT -> gateway -> completed."""
        tool = FakeReadTool()
        orch = _build_orchestrator(db_session, {"file.read": tool})

        result = orch.execute_step(
            task_id="task-1", step_id="step-1",
            tool_name="file.read", args={"path": "/tmp/test.txt"},
            edition="enterprise", tenant_id="t1",
            db=db_session,
        )

        assert result.status == "completed"
        assert result.effect_id is not None
        assert "read" in str(result.output)

    def test_high_risk_step_suspends_awaiting_approval(self, db_session):
        """file.delete (high risk) -> WAIT_APPROVAL -> suspended."""
        tool = FakeDeleteTool()
        orch = _build_orchestrator(db_session, {"file.delete": tool})

        result = orch.execute_step(
            task_id="task-1", step_id="step-1",
            tool_name="file.delete", args={"path": "/tmp/secret.txt"},
            edition="enterprise", tenant_id="t1",
            db=db_session,
        )

        assert result.status == "awaiting_approval"
        assert result.approval_request_id is not None
        # File was NOT deleted (still awaiting approval)
        assert len(tool.deleted) == 0

    def test_resume_after_approval_executes(self, db_session):
        """After approval resolved APPROVED, resume executes the step."""
        tool = FakeDeleteTool()
        orch = _build_orchestrator(db_session, {"file.delete": tool})

        # Step 1: suspend
        suspended = orch.execute_step(
            task_id="task-1", step_id="step-1",
            tool_name="file.delete", args={"path": "/data/file.txt"},
            edition="enterprise", tenant_id="t1",
            db=db_session,
        )
        assert suspended.status == "awaiting_approval"

        # Step 2: approve externally
        from packages.approval.approval_service import ApprovalService
        from packages.db.models import VoteDecision
        svc = ApprovalService(db_session)
        svc.cast_vote(
            request_id=suspended.approval_request_id,
            voter_principal_id="approver-bob",
            decision=VoteDecision.APPROVE,
        )
        resolution = svc.resolve(suspended.approval_request_id)
        assert resolution.status.value == "approved"

        # Step 3: resume
        result = orch.resume_after_approval(
            approval_request_id=suspended.approval_request_id,
            task_id="task-1", step_id="step-1",
            tool_name="file.delete", args={"path": "/data/file.txt"},
            edition="enterprise", tenant_id="t1",
            db=db_session,
        )

        assert result.status == "completed"
        assert result.effect_id is not None
        # File was now deleted
        assert "/data/file.txt" in tool.deleted

    def test_resume_after_rejection_fails(self, db_session):
        tool = FakeDeleteTool()
        orch = _build_orchestrator(db_session, {"file.delete": tool})

        suspended = orch.execute_step(
            task_id="task-1", step_id="step-1",
            tool_name="file.delete", args={"path": "/data/file.txt"},
            edition="enterprise", tenant_id="t1",
            db=db_session,
        )

        from packages.approval.approval_service import ApprovalService
        from packages.db.models import VoteDecision
        svc = ApprovalService(db_session)
        svc.cast_vote(
            request_id=suspended.approval_request_id,
            voter_principal_id="approver-bob",
            decision=VoteDecision.REJECT,
        )
        svc.resolve(suspended.approval_request_id)

        result = orch.resume_after_approval(
            approval_request_id=suspended.approval_request_id,
            task_id="task-1", step_id="step-1",
            tool_name="file.delete", args={"path": "/data/file.txt"},
            db=db_session,
        )
        assert result.status == "rejected"
        assert len(tool.deleted) == 0

    def test_policy_denied_step_rejected(self, db_session):
        """A tool that fails policy check (not registered) is rejected."""
        orch = _build_orchestrator(db_session, {})

        result = orch.execute_step(
            task_id="task-1", step_id="step-1",
            tool_name="nonexistent.tool", args={},
            db=db_session,
        )
        assert result.status == "rejected"
