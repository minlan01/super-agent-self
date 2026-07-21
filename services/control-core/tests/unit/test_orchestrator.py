"""Tests for the Orchestrator module."""

import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.agent_core.orchestrator import Orchestrator
from packages.agent_core.schemas import TaskUpdate
from packages.db.models import Base, TaskStatus
from packages.db.repositories.task_repo import TaskRepository
from packages.planner.plan_validator import Plan, PlanStep


def _make_session():
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_file.close()
    engine = create_engine(f"sqlite:///{db_file.name}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _make_mock_executor(success: bool = True, db=None):
    """Create a mock executor that properly updates task status in DB."""
    executor = MagicMock()
    _test_db = db

    async def _execute(task_id, plan, context, db=None):
        # Update task status via the test's session
        from packages.db.models import TaskStatus as TS
        from packages.db.repositories.task_repo import TaskRepository as TR
        from packages.agent_core.schemas import TaskUpdate as TU
        effective_db = db or _test_db
        if effective_db is not None:
            status = TS.COMPLETED if success else TS.FAILED
            TR.update(effective_db, task_id, TU(status=status))
            effective_db.commit()
        return {
            "task_id": task_id,
            "results": [{"step": 1, "tool": "browser.open", "status": "completed" if success else "failed"}],
            "success": success,
        }

    executor.execute_plan = AsyncMock(side_effect=_execute)
    return executor


@pytest.fixture
def mock_planner():
    p = MagicMock()
    p.plan = AsyncMock(return_value=Plan(
        reasoning="test",
        steps=[PlanStep(step_id=1, tool_name="browser.open", args={"url": "https://example.com"})],
    ))
    return p


class TestOrchestratorRun:
    @pytest.mark.asyncio
    async def test_full_lifecycle_success(self, mock_planner):
        session = _make_session()
        executor = _make_mock_executor(success=True, db=session)
        orchestrator = Orchestrator(planner_service=mock_planner, executor_service=executor)

        result = await orchestrator.run(
            db=session, goal="Open example.com and extract text", edition="enterprise",
        )
        assert result["success"] is True
        assert result["task_id"] is not None
        assert result["status"] == "completed"
        mock_planner.plan.assert_called_once()
        session.close()

    @pytest.mark.asyncio
    async def test_planning_failure(self, mock_planner):
        mock_planner.plan = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        session = _make_session()
        executor = _make_mock_executor(success=True, db=session)
        orchestrator = Orchestrator(planner_service=mock_planner, executor_service=executor)

        result = await orchestrator.run(db=session, goal="Do something impossible")
        assert result["status"] == "failed"
        assert "Planning failed" in result["error"]
        session.close()

    @pytest.mark.asyncio
    async def test_execution_failure(self, mock_planner):
        session = _make_session()
        executor = _make_mock_executor(success=False, db=session)
        orchestrator = Orchestrator(planner_service=mock_planner, executor_service=executor)

        result = await orchestrator.run(db=session, goal="Open slow website")
        assert result["success"] is False
        assert result["status"] == "failed"
        session.close()


class TestOrchestratorRunWithPlan:
    @pytest.mark.asyncio
    async def test_run_with_existing_plan(self, mock_planner):
        from packages.agent_core.schemas import TaskCreate
        from packages.executor.tools.base import ExecutionContext

        session = _make_session()
        executor = _make_mock_executor(success=True, db=session)
        orchestrator = Orchestrator(planner_service=mock_planner, executor_service=executor)

        task = TaskRepository.create(session, TaskCreate(goal="test task"))
        session.commit()  # commit so run_async's independent session can see it
        plan = Plan(steps=[
            PlanStep(step_id=1, tool_name="file.write_markdown", args={
                "path": "test.md", "content": "hello",
            }),
        ])
        ctx = ExecutionContext(task_id=task.id, step_id="test")
        result = await orchestrator.run_with_plan(
            db=session, task_id=task.id, plan=plan, context=ctx,
        )
        assert result["success"] is True
        assert result["status"] == "completed"
        session.close()

    @pytest.mark.asyncio
    async def test_run_with_missing_task(self, mock_planner):
        executor = _make_mock_executor(success=True)
        orchestrator = Orchestrator(planner_service=mock_planner, executor_service=executor)
        session = _make_session()

        plan = Plan(steps=[PlanStep(step_id=1, tool_name="browser.open", args={})])
        with pytest.raises(ValueError, match="not found"):
            await orchestrator.run_with_plan(
                db=session, task_id="nonexistent", plan=plan,
                context=MagicMock(),
            )
        session.close()
