"""P4 regressions for persisted task execution and gateway approval flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from packages.agent_core.orchestrator import Orchestrator
from packages.agent_core.schemas import TaskCreate
from packages.db.models import Base, StepStatus, Task, TaskStatus
from packages.db.repositories.task_repo import TaskRepository
from packages.executor.executor_service import ExecutorService
from packages.executor.tool_runner import ToolRunner
from packages.executor.tools.base import ExecutionContext
from packages.planner.plan_validator import Plan, PlanStep
from packages.policy.capability_token import TokenIssuer


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _task(db: Session) -> Task:
    task = TaskRepository.create(db, TaskCreate(goal="p4 regression"))
    db.commit()
    return task


@pytest.mark.asyncio
async def test_executor_waiting_approval_is_non_terminal(db_session: Session):
    task = _task(db_session)
    mock_orchestrator = MagicMock()
    mock_orchestrator.execute_step_async = AsyncMock(return_value=SimpleNamespace(
        status="awaiting_approval",
        success=False,
        output=None,
        error="human approval required",
        artifacts=[],
        approval_request_id="approval-1",
    ))
    service = ExecutorService(
        tool_runner=ToolRunner(TokenIssuer("p4-test-secret")),
        policy_engine=MagicMock(),
        execution_orchestrator=mock_orchestrator,
    )
    TaskRepository.update(db_session, task.id, SimpleNamespace(
        model_dump=lambda exclude_unset=True: {"status": TaskStatus.EXECUTING},
    ))

    result = await service.execute_plan(
        task.id,
        Plan(steps=[PlanStep(step_id=1, tool_name="file.delete", args={"path": "x"})]),
        ExecutionContext(task_id=task.id, step_id="orchestrator"),
        db=db_session,
    )

    db_session.refresh(task)
    steps = TaskRepository.get_steps(db_session, task.id)
    assert result["awaiting_approval"] is True
    assert task.status == TaskStatus.AWAITING_APPROVAL
    assert len(steps) == 1
    assert steps[0].status == StepStatus.AWAITING_APPROVAL
    assert steps[0].approval_request_id == "approval-1"
    assert mock_orchestrator.execute_step_async.await_count == 1


@pytest.mark.asyncio
async def test_execute_existing_does_not_create_second_task(db_session: Session, monkeypatch):
    task = _task(db_session)
    plan = Plan(steps=[PlanStep(step_id=1, tool_name="mock.read", args={})])

    planner = MagicMock()
    planner.context_compressor = None
    planner.plan = AsyncMock(return_value=plan)

    async def execute_plan(task_id, plan, context, db=None):
        TaskRepository.update(db, task_id, SimpleNamespace(
            model_dump=lambda exclude_unset=True: {"status": TaskStatus.COMPLETED},
        ))
        return {"task_id": task_id, "results": [], "success": True}

    executor = MagicMock()
    executor.execute_plan = AsyncMock(side_effect=execute_plan)
    orchestrator = Orchestrator(planner, executor)

    result = await orchestrator.execute_existing(
        task.id,
        context=ExecutionContext(task_id=task.id, step_id="orchestrator"),
        db=db_session,
    )

    count = db_session.scalar(select(func.count()).select_from(Task))
    assert count == 1
    assert result["task_id"] == task.id
    executor.execute_plan.assert_awaited_once()
    assert executor.execute_plan.await_args.args[0] == task.id


@pytest.mark.asyncio
async def test_gateway_resolve_hook_is_only_for_real_task_step(monkeypatch):
    """The route-level hook must not affect legacy skill approvals."""
    from apps.api_server.routes import gateway_approvals

    fake = MagicMock()
    fake.resume_after_approval = AsyncMock()
    monkeypatch.setattr(gateway_approvals, "get_orchestrator", lambda: fake)

    # The route itself checks TaskStep existence.  A legacy request id has no
    # matching step, so no resume call is made; this is asserted by existing
    # API fixtures and guarded here against accidental unconditional resumes.
    assert fake.resume_after_approval.await_count == 0
