"""Orchestrator — connects Planner → Policy → Executor for full task lifecycle."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from packages.agent_core.schemas import AuditEventCreate, TaskCreate, TaskUpdate
from packages.agent_core.task_state import InvalidTransition, TaskStateMachine
from packages.db.models import AuditEventType, TaskStatus
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.task_repo import TaskRepository
from packages.db.session import run_async
from packages.executor.executor_service import ExecutorService
from packages.executor.tools.base import ExecutionContext
from packages.planner.plan_validator import Plan
from packages.planner.planner_service import PlannerService

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def _emit_plugin_hook(hook_name: str, **kwargs: Any) -> None:
    """Fire-and-forget plugin hook emission."""
    try:
        from packages.plugins.loader import PluginLoader
        loader = PluginLoader.get_instance()
        if loader is None:
            return
        loop = asyncio.get_running_loop()
        task = loop.create_task(loader.emit(hook_name, **kwargs))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except RuntimeError:
        pass
    except Exception as e:
        logger.warning("Plugin hook emission failed: %s", e)


class Orchestrator:
    """Full lifecycle orchestrator: create → plan → execute → complete/fail."""

    def __init__(
        self,
        planner_service: PlannerService,
        executor_service: ExecutorService,
        context_compressor: Any | None = None,
    ):
        self.planner = planner_service
        self.executor = executor_service
        self.context_compressor = context_compressor
        self._test_db: Any = None  # injected by tests for session sharing

        # Wire compressor into planner if provided
        if context_compressor is not None and self.planner.context_compressor is None:
            self.planner.context_compressor = context_compressor

    def _ra(self):
        """Return run_async bound to the optional test db session."""
        if self._test_db is not None:
            _db = self._test_db
            async def _bound(func, *args, **kwargs):
                return await run_async(func, *args, _db=_db, **kwargs)
            return _bound
        return run_async

    async def run(
        self,
        goal: str,
        edition: str = "enterprise",
        user_id: str = "default",
        context: ExecutionContext | None = None,
        memories: list[dict[str, Any]] | None = None,
        skills: list[dict[str, Any]] | None = None,
        db: Any = None,  # shared session for test backward-compat
    ) -> dict[str, Any]:
        """Execute full task lifecycle: create → plan → policy → execute.

        Returns dict with task_id, status, plan, and execution results.
        """
        self._test_db = db
        ra = self._ra()

        task = await ra(
            TaskRepository.create, TaskCreate(
                goal=goal, edition=edition, user_id=user_id,
            )
        )
        await ra(
            AuditRepository.create, AuditEventCreate(
                task_id=task.id, edition=edition,
                event_type=AuditEventType.TASK_CREATED,
                detail={"goal": goal},
            )
        )
        logger.info("Task created: %s — %s", task.id, goal[:80])
        _emit_plugin_hook("on_task_create", task_id=task.id, goal=goal)

        try:
            task = await self._transition(task, TaskStatus.PLANNING)
        except InvalidTransition as e:
            await self._rollback_to_failed(task.id)
            return {"task_id": task.id, "status": "failed", "error": f"Invalid state transition: {e}"}
        plan = await self._plan_phase(task, goal, edition, memories, skills)
        if plan is None:
            _emit_plugin_hook("on_task_fail", task_id=task.id, phase="planning")
            return {"task_id": task.id, "status": "failed", "error": "Planning failed"}

        try:
            task = await self._transition(task, TaskStatus.EXECUTING)
        except InvalidTransition as e:
            await self._rollback_to_failed(task.id)
            return {"task_id": task.id, "status": "failed", "error": f"Invalid state transition: {e}"}
        if context is None:
            context = ExecutionContext(
                task_id=task.id,
                step_id="orchestrator",
                principal_id=user_id,
                workspace_id=task.id,
                edition=edition,
            )

        result = await self.executor.execute_plan(task.id, plan, context, db=db)

        task = await ra(TaskRepository.get_by_id, task.id, False)
        if task is None:
            return {
                "task_id": "unknown",
                "status": "failed",
                "error": "Task not found after execution",
            }

        if task.status == TaskStatus.CANCELLED:
            logger.info("Task %s was cancelled during execution, skipping hooks", task.id)
            return {
                "task_id": task.id,
                "status": TaskStatus.CANCELLED.value,
                "plan": {
                    "steps": [
                        {"step_id": s.step_id, "tool": s.tool_name}
                        for s in plan.steps
                    ]
                },
                "results": result.get("results", []),
                "success": False,
            }

        if task.status == TaskStatus.COMPLETED:
            _emit_plugin_hook("on_task_complete", task_id=task.id)
        elif task.status == TaskStatus.FAILED:
            _emit_plugin_hook("on_task_fail", task_id=task.id, phase="execution")

        for s in plan.steps:
            _emit_plugin_hook(
                "on_tool_execute",
                task_id=task.id,
                tool=s.tool_name,
                step_id=s.step_id,
            )

        return {
            "task_id": task.id,
            "status": task.status.value,
            "plan": {"steps": [{"step_id": s.step_id, "tool": s.tool_name} for s in plan.steps]},
            "results": result.get("results", []),
            "success": result.get("success", False),
        }

    async def run_with_plan(
        self,
        task_id: str,
        plan: Plan,
        context: ExecutionContext,
        db: Any = None,  # shared session for test backward-compat
    ) -> dict[str, Any]:
        """Execute an already-created task with a pre-built plan."""
        self._test_db = db
        ra = self._ra()

        task = await ra(TaskRepository.get_by_id, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        try:
            if task.status == TaskStatus.PENDING:
                task = await self._transition(task, TaskStatus.PLANNING)
            task = await self._transition(task, TaskStatus.EXECUTING)
        except InvalidTransition as e:
            logger.error("Task %s: invalid transition — %s", task_id, e)
            await self._rollback_to_failed(task_id)
            return {"task_id": task_id, "status": "failed", "error": f"Invalid state transition: {e}"}

        result = await self.executor.execute_plan(task.id, plan, context, db=db)

        task = await ra(TaskRepository.get_by_id, task.id)
        if task is None:
            raise ValueError(f"Task {task_id} not found after execution")

        if task.status == TaskStatus.CANCELLED:
            return {
                "task_id": task.id,
                "status": TaskStatus.CANCELLED.value,
                "results": result.get("results", []),
                "success": False,
            }

        return {
            "task_id": task.id,
            "status": task.status.value,
            "results": result.get("results", []),
            "success": result.get("success", False),
        }

    async def _plan_phase(
        self,
        task: Any,
        goal: str,
        edition: str,
        memories: list[dict[str, Any]] | None,
        skills: list[dict[str, Any]] | None,
    ) -> Plan | None:
        ra = self._ra()
        try:
            plan = await self.planner.plan(
                goal=goal, edition=edition,
                memories=memories, skills=skills,
            )
            await ra(
                AuditRepository.create, AuditEventCreate(
                    task_id=task.id, edition=edition,
                    event_type=AuditEventType.PLAN_GENERATED,
                    detail={"steps_count": len(plan.steps)},
                )
            )
            logger.info("Plan generated for task %s: %d steps", task.id, len(plan.steps))
            _emit_plugin_hook("on_plan_generate", task_id=task.id, steps_count=len(plan.steps))
            return plan
        except Exception as e:
            logger.exception("Planning failed for task %s", task.id)
            await ra(
                TaskRepository.update, task.id, TaskUpdate(
                    status=TaskStatus.FAILED, error=f"Planning failed: {e}",
                )
            )
            await ra(
                AuditRepository.create, AuditEventCreate(
                    task_id=task.id, event_type=AuditEventType.TASK_FAILED,
                    detail={"phase": "planning", "error": str(e)},
                )
            )
            return None

    async def _transition(self, task: Any, target: TaskStatus) -> Any:
        """Transition task status with validation and atomic CAS."""
        ra = self._ra()
        current = task.status
        TaskStateMachine.transition(current, target)
        updated = await ra(
            TaskRepository.atomic_status_transition, task.id, current, target
        )
        if updated is None:
            raise InvalidTransition(current, target)
        logger.info("Task %s: %s → %s", task.id, current.value, target.value)
        return updated

    async def _rollback_to_failed(self, task_id: str) -> None:
        """Attempt to mark a stuck task as FAILED after a failed transition."""
        ra = self._ra()
        try:
            await ra(
                TaskRepository.update, task_id, TaskUpdate(status=TaskStatus.FAILED)
            )
        except Exception as e:
            logger.warning("Failed to rollback task %s to FAILED: %s", task_id, e)
