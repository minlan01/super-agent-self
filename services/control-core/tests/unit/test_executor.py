"""Unit tests for Executor framework -- ToolResult, ExecutionContext, ToolRunner, ExecutorService."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.agent_core.schemas import TaskStepCreate
from packages.db.models import AuditEventType, Base, StepStatus, Task, TaskStatus
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.task_repo import TaskRepository
from packages.executor.executor_service import ExecutorService
from packages.executor.tool_runner import ToolRunner
from packages.executor.tools.base import ExecutionContext, ToolBase, ToolResult
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
    """In-memory SQLite with all tables."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Session tied to the in-memory DB."""
    session = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)()
    yield session
    session.close()


@pytest.fixture
def token_issuer():
    return TokenIssuer("test-secret-key", expire_minutes=5)


@pytest.fixture
def tool_registry():
    return ToolRegistry(config_path="configs/tools.yaml")


@pytest.fixture
def policy_engine(tool_registry, token_issuer):
    return PolicyEngine(tool_registry, token_issuer, config_path="configs/policy.yaml")


@pytest.fixture
def tool_runner(token_issuer):
    return ToolRunner(token_issuer)


def _create_task(db: Session) -> Task:
    """Create a Task record and return it."""
    task = Task(
        id=str(uuid.uuid4()),
        goal="test goal",
        user_id="default",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Mock tool
# ---------------------------------------------------------------------------


class _MockTool(ToolBase):
    """A mock tool that returns a configurable result."""

    name = "mock.tool"
    description = "A mock tool for testing"

    def __init__(self, result: ToolResult | None = None):
        self._result = result or ToolResult(success=True, output="mocked")

    async def execute(self, args: dict, context: ExecutionContext) -> ToolResult:
        return self._result


class _FailingTool(ToolBase):
    """A mock tool that always fails."""

    name = "mock.failing"
    description = "A mock tool that fails"

    async def execute(self, args: dict, context: ExecutionContext) -> ToolResult:
        return ToolResult(success=False, error="intentional failure")


class _ExceptionTool(ToolBase):
    """A mock tool that raises an exception."""

    name = "mock.exception"
    description = "A mock tool that raises"

    async def execute(self, args: dict, context: ExecutionContext) -> ToolResult:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# ToolResult tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolResult:
    def test_success_result(self):
        result = ToolResult(success=True, output="hello")
        assert result.success is True
        assert result.output == "hello"
        assert result.error is None
        assert result.artifacts == []

    def test_failure_result(self):
        result = ToolResult(success=False, error="something went wrong")
        assert result.success is False
        assert result.error == "something went wrong"
        assert result.output is None

    def test_result_with_artifacts(self):
        result = ToolResult(
            success=True,
            output="done",
            artifacts=["/path/to/file.txt", "/path/to/screenshot.png"],
        )
        assert len(result.artifacts) == 2
        assert "/path/to/file.txt" in result.artifacts

    def test_to_dict(self):
        result = ToolResult(success=True, output={"key": "val"}, artifacts=["a"])
        d = result.to_dict()
        assert d["success"] is True
        assert d["output"] == {"key": "val"}
        assert d["error"] is None
        assert d["artifacts"] == ["a"]

    def test_to_dict_with_error(self):
        result = ToolResult(success=False, error="fail")
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "fail"


# ---------------------------------------------------------------------------
# ExecutionContext tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecutionContext:
    def test_default_properties(self):
        ctx = ExecutionContext(task_id="t1", step_id="s1")
        assert ctx.task_id == "t1"
        assert ctx.step_id == "s1"
        assert ctx.edition == "enterprise"
        assert ctx.workspace_root == "./workspace"
        assert ctx.max_file_size_mb == 50
        assert ctx.browser_headless is True

    def test_outputs_path_creates_dir(self, tmp_path):
        ctx = ExecutionContext(
            task_id="t1",
            step_id="s1",
            workspace_root=str(tmp_path),
            outputs_dir="outputs",
        )
        result = ctx.outputs_path
        from pathlib import Path
        assert Path(result).is_dir()
        assert result == str(tmp_path / "outputs")

    def test_screenshots_path_creates_dir(self, tmp_path):
        ctx = ExecutionContext(
            task_id="t1",
            step_id="s1",
            workspace_root=str(tmp_path),
            screenshots_dir="screenshots",
        )
        result = ctx.screenshots_path
        from pathlib import Path
        assert Path(result).is_dir()
        assert result == str(tmp_path / "screenshots")

    def test_outputs_path_nested(self, tmp_path):
        ctx = ExecutionContext(
            task_id="t1",
            step_id="s1",
            workspace_root=str(tmp_path),
            outputs_dir="deep/nested/outputs",
        )
        result = ctx.outputs_path
        from pathlib import Path
        assert Path(result).is_dir()


# ---------------------------------------------------------------------------
# ToolRunner tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolRunner:
    def test_register_and_get_tool(self, tool_runner):
        tool = _MockTool()
        tool_runner.register(tool)
        assert tool_runner.get_tool("mock.tool") is tool
        assert tool_runner.get_tool("nonexistent") is None

    def test_register_overwrites(self, tool_runner):
        tool1 = _MockTool()
        tool2 = _MockTool()
        tool_runner.register(tool1)
        tool_runner.register(tool2)
        assert tool_runner.get_tool("mock.tool") is tool2

    @pytest.mark.asyncio
    async def test_run_success(self, db_session, tool_runner, token_issuer):
        """Verify: token check passes, step status updates to COMPLETED, audit events created."""
        task = _create_task(db_session)
        step = TaskRepository.add_step(db_session, task.id, TaskStepCreate(
            step_order=1, tool_name="mock.tool",
        ))

        tool = _MockTool(ToolResult(success=True, output="ok", artifacts=["a.txt"]))
        tool_runner.register(tool)

        token = token_issuer.issue(task.id, step.id, "mock.tool", {})
        ctx = ExecutionContext(task_id=task.id, step_id=step.id)

        result = await tool_runner.run(
            db=db_session,
            task_id=task.id,
            step_id=step.id,
            tool_name="mock.tool",
            args={},
            capability_token=token,
            context=ctx,
        )

        assert result.success is True
        assert result.output == "ok"
        assert result.artifacts == ["a.txt"]

        # Verify step status
        db_session.refresh(step)
        assert step.status == StepStatus.COMPLETED
        assert step.result == "ok"

        # Verify audit events
        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]
        assert AuditEventType.STEP_EXECUTING in event_types
        assert AuditEventType.STEP_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_run_tool_failure(self, db_session, tool_runner, token_issuer):
        """Verify step status FAILED on tool failure."""
        task = _create_task(db_session)
        step = TaskRepository.add_step(db_session, task.id, TaskStepCreate(
            step_order=1, tool_name="mock.failing",
        ))

        tool = _FailingTool()
        tool_runner.register(tool)

        token = token_issuer.issue(task.id, step.id, "mock.failing", {})
        ctx = ExecutionContext(task_id=task.id, step_id=step.id)

        result = await tool_runner.run(
            db=db_session,
            task_id=task.id,
            step_id=step.id,
            tool_name="mock.failing",
            args={},
            capability_token=token,
            context=ctx,
        )

        assert result.success is False
        assert result.error == "intentional failure"

        db_session.refresh(step)
        assert step.status == StepStatus.FAILED
        assert step.error == "intentional failure"

        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]
        assert AuditEventType.STEP_FAILED in event_types

    @pytest.mark.asyncio
    async def test_run_invalid_token(self, db_session, tool_runner, token_issuer):
        """Verify rejection when token is invalid."""
        task = _create_task(db_session)
        step = TaskRepository.add_step(db_session, task.id, TaskStepCreate(
            step_order=1, tool_name="mock.tool",
        ))

        tool_runner.register(_MockTool())
        ctx = ExecutionContext(task_id=task.id, step_id=step.id)

        result = await tool_runner.run(
            db=db_session,
            task_id=task.id,
            step_id=step.id,
            tool_name="mock.tool",
            args={},
            capability_token="invalid-token-string",
            context=ctx,
        )

        assert result.success is False
        assert "Token verification failed" in result.error

        db_session.refresh(step)
        assert step.status == StepStatus.FAILED

        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]
        assert AuditEventType.STEP_FAILED in event_types

    @pytest.mark.asyncio
    async def test_run_tool_not_found(self, db_session, tool_runner, token_issuer):
        """Verify error when tool is not registered."""
        task = _create_task(db_session)
        step = TaskRepository.add_step(db_session, task.id, TaskStepCreate(
            step_order=1, tool_name="nonexistent.tool",
        ))

        token = token_issuer.issue(task.id, step.id, "nonexistent.tool", {})
        ctx = ExecutionContext(task_id=task.id, step_id=step.id)

        result = await tool_runner.run(
            db=db_session,
            task_id=task.id,
            step_id=step.id,
            tool_name="nonexistent.tool",
            args={},
            capability_token=token,
            context=ctx,
        )

        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_run_tool_exception(self, db_session, tool_runner, token_issuer):
        """Verify exception handling in tool execution."""
        task = _create_task(db_session)
        step = TaskRepository.add_step(db_session, task.id, TaskStepCreate(
            step_order=1, tool_name="mock.exception",
        ))

        tool_runner.register(_ExceptionTool())
        token = token_issuer.issue(task.id, step.id, "mock.exception", {})
        ctx = ExecutionContext(task_id=task.id, step_id=step.id)

        result = await tool_runner.run(
            db=db_session,
            task_id=task.id,
            step_id=step.id,
            tool_name="mock.exception",
            args={},
            capability_token=token,
            context=ctx,
        )

        assert result.success is False
        assert "boom" in result.error

        db_session.refresh(step)
        assert step.status == StepStatus.FAILED


# ---------------------------------------------------------------------------
# ExecutorService tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecutorService:
    def _make_service(self, tool_runner, policy_engine):
        return ExecutorService(tool_runner=tool_runner, policy_engine=policy_engine)

    @pytest.mark.asyncio
    async def test_sequential_execution_success(self, db_session, tool_runner, policy_engine, tmp_path):
        """Verify all steps executed sequentially on success."""
        task = _create_task(db_session)
        tool_runner.register(FileWriteMarkdown())

        service = self._make_service(tool_runner, policy_engine)
        ctx = ExecutionContext(
            task_id=task.id,
            step_id="s1",
            workspace_root=str(tmp_path),
            outputs_dir="outputs",
        )

        plan = Plan(
            reasoning="test plan",
            steps=[
                PlanStep(step_id=1, tool_name="file.write_markdown", args={
                    "output_path": "test1.md",
                    "content": "hello",
                }),
                PlanStep(step_id=2, tool_name="file.write_markdown", args={
                    "output_path": "test2.md",
                    "content": "world",
                }),
            ],
        )

        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        assert result["success"] is True
        assert len(result["results"]) == 2
        assert result["results"][0]["status"] == "completed"
        assert result["results"][1]["status"] == "completed"

        # Verify task status
        db_session.refresh(task)
        assert task.status == TaskStatus.COMPLETED

        # Verify audit trail
        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]
        assert AuditEventType.TASK_COMPLETED in event_types
        assert AuditEventType.POLICY_APPROVED in event_types

    @pytest.mark.asyncio
    async def test_stops_on_step_failure(self, db_session, tool_runner, policy_engine, tmp_path):
        """Verify remaining steps skipped when a step fails."""
        task = _create_task(db_session)

        # Register a tool that looks like file.write_markdown but fails
        failing = _MockTool(ToolResult(success=False, error="write failed"))
        failing.name = "file.write_markdown"
        tool_runner.register(failing)

        service = self._make_service(tool_runner, policy_engine)
        ctx = ExecutionContext(
            task_id=task.id,
            step_id="s1",
            workspace_root=str(tmp_path),
            outputs_dir="outputs",
        )

        plan = Plan(
            reasoning="test plan",
            steps=[
                PlanStep(step_id=1, tool_name="file.write_markdown", args={
                    "output_path": "test1.md",
                    "content": "hello",
                }),
                PlanStep(step_id=2, tool_name="file.write_markdown", args={
                    "output_path": "test2.md",
                    "content": "world",
                }),
                PlanStep(step_id=3, tool_name="file.write_markdown", args={
                    "output_path": "test3.md",
                    "content": "!",
                }),
            ],
        )

        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        assert result["success"] is False
        # Only the first step result is appended (subsequent skipped steps are not appended to results)
        assert len(result["results"]) >= 1
        assert result["results"][0]["status"] == "failed"

        # Verify task status
        db_session.refresh(task)
        assert task.status == TaskStatus.FAILED

        # Verify skipped steps exist in DB
        # With retry: original step(1) + 2 skipped(2,3) + retry step = 4 steps
        steps = TaskRepository.get_steps(db_session, task.id)
        assert len(steps) == 4
        assert steps[0].status == StepStatus.FAILED  # original step
        assert steps[0].step_order == 1
        assert steps[1].status == StepStatus.SKIPPED  # remaining skipped
        assert steps[2].status == StepStatus.SKIPPED
        assert steps[3].status == StepStatus.FAILED  # retry step
        assert steps[3].step_order >= 9000

        # Verify audit
        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]
        assert AuditEventType.TASK_FAILED in event_types

    @pytest.mark.asyncio
    async def test_marks_task_completed_on_success(self, db_session, tool_runner, policy_engine, tmp_path):
        """Verify task marked COMPLETED when all steps succeed."""
        task = _create_task(db_session)
        tool_runner.register(FileWriteMarkdown())

        service = self._make_service(tool_runner, policy_engine)
        ctx = ExecutionContext(
            task_id=task.id,
            step_id="s1",
            workspace_root=str(tmp_path),
            outputs_dir="outputs",
        )

        plan = Plan(
            reasoning="single step",
            steps=[
                PlanStep(step_id=1, tool_name="file.write_markdown", args={
                    "output_path": "test.md",
                    "content": "hello",
                }),
            ],
        )

        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        assert result["success"] is True

        db_session.refresh(task)
        assert task.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_marks_task_failed_on_error(self, db_session, tool_runner, policy_engine):
        """Verify task marked FAILED when a step errors."""
        task = _create_task(db_session)

        failing = _MockTool(ToolResult(success=False, error="boom"))
        failing.name = "file.write_markdown"
        tool_runner.register(failing)

        service = self._make_service(tool_runner, policy_engine)
        ctx = ExecutionContext(task_id=task.id, step_id="s1")

        plan = Plan(
            reasoning="fail plan",
            steps=[
                PlanStep(step_id=1, tool_name="file.write_markdown", args={
                    "output_path": "test.md",
                    "content": "hello",
                }),
            ],
        )

        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        assert result["success"] is False

        db_session.refresh(task)
        assert task.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_policy_rejection_stops_execution(self, db_session, tool_runner, policy_engine, tmp_path):
        """Verify policy rejection marks step REJECTED and stops."""
        task = _create_task(db_session)
        tool_runner.register(FileWriteMarkdown())

        service = self._make_service(tool_runner, policy_engine)
        ctx = ExecutionContext(
            task_id=task.id,
            step_id="s1",
            workspace_root=str(tmp_path),
            outputs_dir="outputs",
        )

        plan = Plan(
            reasoning="forbidden tool plan",
            steps=[
                PlanStep(step_id=1, tool_name="shell.run", args={"command": "rm -rf /"}),
                PlanStep(step_id=2, tool_name="file.write_markdown", args={
                    "output_path": "test.md",
                    "content": "hello",
                }),
            ],
        )

        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        assert result["success"] is False
        assert result["results"][0]["status"] == "rejected"

        db_session.refresh(task)
        assert task.status == TaskStatus.FAILED

        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]
        assert AuditEventType.POLICY_REJECTED in event_types

        # Verify step 2 was skipped in DB
        steps = TaskRepository.get_steps(db_session, task.id)
        assert len(steps) == 2
        assert steps[0].status == StepStatus.REJECTED
        assert steps[1].status == StepStatus.SKIPPED
