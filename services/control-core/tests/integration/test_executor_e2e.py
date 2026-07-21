"""Integration tests for full E2E execution chain -- Plan -> Policy -> Executor -> verify output."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.db.models import AuditEventType, Base, StepStatus, Task, TaskStatus
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.task_repo import TaskRepository
from packages.executor.executor_service import ExecutorService
from packages.executor.tool_runner import ToolRunner
from packages.executor.tools.base import ExecutionContext
from packages.executor.tools.file_tools import FileWriteMarkdown
from packages.planner.plan_validator import Plan, PlanStep
from packages.policy.capability_token import TokenIssuer
from packages.policy.policy_engine import PolicyEngine
from packages.policy.tool_registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    session = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)()
    yield session
    session.close()


@pytest.fixture
def tool_registry():
    return ToolRegistry(config_path="configs/tools.yaml")


@pytest.fixture
def token_issuer():
    return TokenIssuer("e2e-test-secret", expire_minutes=5)


@pytest.fixture
def policy_engine(tool_registry, token_issuer):
    return PolicyEngine(tool_registry, token_issuer, config_path="configs/policy.yaml")


@pytest.fixture
def tool_runner(token_issuer):
    runner = ToolRunner(token_issuer)
    runner.register(FileWriteMarkdown())
    return runner


def _create_task(db: Session) -> Task:
    task = Task(id=str(uuid.uuid4()), goal="e2e test", user_id="default")
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# E2E: Full execution chain with file.write_markdown
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExecutorE2E:
    @pytest.mark.asyncio
    async def test_full_chain_write_markdown(self, db_session, tool_runner, policy_engine, tmp_path):
        """Create plan -> PolicyEngine check -> ExecutorService.execute_plan -> verify file output."""
        task = _create_task(db_session)

        service = ExecutorService(tool_runner=tool_runner, policy_engine=policy_engine)
        ctx = ExecutionContext(
            task_id=task.id,
            step_id="s1",
            workspace_root=str(tmp_path),
            outputs_dir="outputs",
        )

        plan = Plan(
            reasoning="Write a markdown file",
            steps=[
                PlanStep(
                    step_id=1,
                    tool_name="file.write_markdown",
                    args={"output_path": "greeting.md", "content": "# Hello\n\nThis is an E2E test."},
                ),
            ],
        )

        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        # Verify overall success
        assert result["success"] is True
        assert result["task_id"] == task.id
        assert len(result["results"]) == 1
        assert result["results"][0]["status"] == "completed"

        # Verify task status
        db_session.refresh(task)
        assert task.status == TaskStatus.COMPLETED

        # Verify file was actually written
        output_file = tmp_path / "outputs" / "greeting.md"
        assert output_file.is_file()
        content = output_file.read_text(encoding="utf-8")
        assert "# Hello" in content
        assert "This is an E2E test." in content

        # Verify complete audit trail
        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]
        assert AuditEventType.POLICY_APPROVED in event_types
        assert AuditEventType.STEP_EXECUTING in event_types
        assert AuditEventType.STEP_COMPLETED in event_types
        assert AuditEventType.TASK_COMPLETED in event_types

        # Verify step record
        steps = TaskRepository.get_steps(db_session, task.id)
        assert len(steps) == 1
        assert steps[0].status == StepStatus.COMPLETED
        assert steps[0].tool_name == "file.write_markdown"
        assert steps[0].capability_token_hash is not None

    @pytest.mark.asyncio
    async def test_forbidden_tool_rejected(self, db_session, tool_runner, policy_engine, tmp_path):
        """Plan with forbidden tool (shell.run) -> step rejected, task failed."""
        task = _create_task(db_session)

        service = ExecutorService(tool_runner=tool_runner, policy_engine=policy_engine)
        ctx = ExecutionContext(
            task_id=task.id,
            step_id="s1",
            workspace_root=str(tmp_path),
        )

        plan = Plan(
            reasoning="Try to run a shell command",
            steps=[
                PlanStep(
                    step_id=1,
                    tool_name="shell.run",
                    args={"command": "echo hello"},
                ),
            ],
        )

        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        assert result["success"] is False
        assert result["results"][0]["status"] == "rejected"

        db_session.refresh(task)
        assert task.status == TaskStatus.FAILED

        # Verify audit trail has POLICY_REJECTED
        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]
        assert AuditEventType.POLICY_REJECTED in event_types
        assert AuditEventType.TASK_FAILED in event_types

        # Verify step record
        steps = TaskRepository.get_steps(db_session, task.id)
        assert len(steps) == 1
        assert steps[0].status == StepStatus.REJECTED

    @pytest.mark.asyncio
    async def test_multi_step_safe_execution(self, db_session, tool_runner, policy_engine, tmp_path):
        """Plan with multiple safe file tools -> all completed, audit trail complete."""
        task = _create_task(db_session)

        service = ExecutorService(tool_runner=tool_runner, policy_engine=policy_engine)
        ctx = ExecutionContext(
            task_id=task.id,
            step_id="s1",
            workspace_root=str(tmp_path),
            outputs_dir="outputs",
        )

        plan = Plan(
            reasoning="Write two markdown files",
            steps=[
                PlanStep(
                    step_id=1,
                    tool_name="file.write_markdown",
                    args={"output_path": "first.md", "content": "# First\n\nContent 1"},
                ),
                PlanStep(
                    step_id=2,
                    tool_name="file.write_markdown",
                    args={"output_path": "second.md", "content": "# Second\n\nContent 2"},
                ),
            ],
        )

        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        assert result["success"] is True
        assert len(result["results"]) == 2
        assert all(r["status"] == "completed" for r in result["results"])

        # Verify both files exist
        assert (tmp_path / "outputs" / "first.md").is_file()
        assert (tmp_path / "outputs" / "second.md").is_file()

        # Verify task completed
        db_session.refresh(task)
        assert task.status == TaskStatus.COMPLETED

        # Verify audit trail: 2 policy_approved + 2 step_executing + 2 step_completed + 1 task_completed
        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]
        assert event_types.count(AuditEventType.POLICY_APPROVED) == 2
        assert event_types.count(AuditEventType.STEP_EXECUTING) == 2
        assert event_types.count(AuditEventType.STEP_COMPLETED) == 2
        assert AuditEventType.TASK_COMPLETED in event_types

        # Verify step records
        steps = TaskRepository.get_steps(db_session, task.id)
        assert len(steps) == 2
        assert all(s.status == StepStatus.COMPLETED for s in steps)
        assert all(s.capability_token_hash is not None for s in steps)
