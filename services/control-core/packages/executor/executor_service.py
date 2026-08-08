"""Executor Service — orchestrates execution of a plan's steps with retry and re-planning."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import structlog

from packages.agent_core.schemas import (
    AuditEventCreate,
    TaskStepCreate,
    TaskStepUpdate,
    TaskUpdate,
)
from packages.db.models import AuditEventType, StepStatus, TaskStatus
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.task_repo import TaskRepository
from packages.db.session import run_async
from packages.executor.tool_runner import ToolRunner
from packages.executor.tools.base import ExecutionContext
from packages.planner.plan_validator import Plan
from packages.policy.policy_engine import PolicyEngine

logger = structlog.get_logger()

# Type for the optional execution orchestrator (avoid circular import)
ExecutionOrchestratorType = Any  # packages.execution.orchestrator.ExecutionOrchestrator


async def _ws_broadcast(task_id: str, event: str, data: dict[str, Any]) -> None:
    """Fire-and-forget WebSocket broadcast for task updates."""
    try:
        from apps.api_server.routes.ws import manager
        await manager.send_update(task_id, {"event": event, **data})
    except Exception as e:
        logger.warning("WebSocket broadcast failed for task %s: %s", task_id, e)


async def _notify(
    user_id: str,
    ntype: str,
    title: str,
    message: str,
    data: dict | None = None,
) -> None:
    """Fire-and-forget notification creation + WebSocket broadcast.

    Uses lazy imports to avoid circular dependencies at module level.
    """
    try:
        from packages.notification.notification_service import notification_service
        from packages.notification.ws_broadcaster import notification_broadcaster

        notification = notification_service.create(
            user_id=user_id,
            type=ntype,
            title=title,
            message=message,
            data=data,
        )
        await notification_broadcaster.broadcast_notification(user_id, notification)
    except Exception:
        logger.exception("Notification creation failed for user %s", user_id)

MAX_STEP_RETRIES = 1  # retry each failed step once before re-planning
MAX_CONCURRENT_TASKS = 5
_DEFAULT_STEP_TIMEOUT = 300  # 5-minute default per step execution


def _get_step_timeout() -> int:
    """Read step timeout from config, fallback to default."""
    try:
        from packages.config import get_settings
        return getattr(get_settings(), "step_timeout_seconds", _DEFAULT_STEP_TIMEOUT)
    except Exception:
        return _DEFAULT_STEP_TIMEOUT


class ExecutorService:
    def __init__(
        self,
        tool_runner: ToolRunner,
        policy_engine: PolicyEngine,
        planner: Any | None = None,
        max_concurrent_tasks: int = MAX_CONCURRENT_TASKS,
        step_timeout: int | None = None,
        execution_orchestrator: ExecutionOrchestratorType | None = None,
    ):
        self.tool_runner = tool_runner
        self.policy_engine = policy_engine
        self.planner = planner
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self._step_timeout = step_timeout
        self._test_db: Any = None  # injected by tests for session sharing
        self._execution_orchestrator = execution_orchestrator

    # Thread-safe DB helper: each call uses an independent session in production.
    # When a shared _db is injected (tests), reuse it for SQLite visibility.
    def _ra(self, _db=None):
        """Return a bound run_async that carries the optional shared session."""
        if _db is not None:
            self._test_db = _db  # stash for tool_runner compat
            async def _ra_bound(func, *args, **kwargs):
                return await run_async(func, *args, _db=_db, **kwargs)
            return _ra_bound
        self._test_db = None
        return run_async

    async def execute_plan(
        self,
        task_id: str,
        plan: Plan,
        context: ExecutionContext,
        db: Any = None,  # shared session for test backward-compat
    ) -> dict[str, Any]:
        """Execute all steps of a plan sequentially.

        Uses a semaphore to limit concurrent task executions.
        """
        ra = self._ra(db)
        async with self._semaphore:
            try:
                return await self._execute_plan_inner(task_id, plan, context, ra)
            except asyncio.CancelledError:
                logger.warning("Task %s: execution cancelled mid-plan", task_id)
                await self._finalize_task(task_id, [], failed=True, cancelled=True, ra=ra)
                raise

    async def _execute_plan_inner(
        self,
        task_id: str,
        plan: Plan,
        context: ExecutionContext,
        ra,
    ) -> dict[str, Any]:
        logger.info("Task %s: starting execution with %d steps", task_id, len(plan.steps))
        plan_start = time.perf_counter()
        results = []
        failed = False
        cancelled = False

        for plan_step in plan.steps:
            if failed:
                step = await ra(
                    TaskRepository.add_step, task_id, TaskStepCreate(
                        step_order=plan_step.step_id,
                        tool_name=plan_step.tool_name,
                        args=plan_step.args,
                    )
                )
                await ra(
                    TaskRepository.update_step, step.id, TaskStepUpdate(status=StepStatus.SKIPPED)
                )
                continue

            current_task = await ra(TaskRepository.get_by_id, task_id, False)
            if current_task and current_task.status == TaskStatus.CANCELLED:
                logger.info("Task %s: cancelled — skipping remaining steps", task_id)
                failed = True
                cancelled = True
                continue

            step_result, should_fail = await self._execute_single_step(
                task_id, plan_step, context, ra,
            )
            results.append(step_result)
            if should_fail:
                failed = True
                continue

            tool_result = step_result.get("_raw_result")
            if tool_result and not tool_result.success:
                recovery_plan = await self._try_replan(
                    task_id, plan_step, tool_result.error, context, ra,
                )
                if recovery_plan is not None:
                    recovery_results = await self._execute_recovery(
                        task_id, recovery_plan, context, ra,
                    )
                    results.extend(recovery_results)
                    if any(r["status"] == "failed" for r in recovery_results):
                        failed = True
                else:
                    failed = True

        plan_duration = time.perf_counter() - plan_start
        await self._finalize_task(task_id, results, failed, cancelled, ra=ra, plan_duration=plan_duration)
        try:
            from packages.middleware.prometheus import registry
            registry.task_execution_duration_seconds.observe(
                plan_duration, labels={"status": "failed" if failed else "completed"}
            )
        except Exception:
            logger.debug("Prometheus metrics recording failed", exc_info=True)
        return {"task_id": task_id, "results": results, "success": not failed}

    async def _execute_single_step(
        self,
        task_id: str,
        plan_step: Any,
        context: ExecutionContext,
        ra,
    ) -> tuple[dict[str, Any], bool]:
        step = await ra(
            TaskRepository.add_step, task_id, TaskStepCreate(
                step_order=plan_step.step_id,
                tool_name=plan_step.tool_name,
                args=plan_step.args,
            )
        )

        policy_result = self.policy_engine.check(
            task_id=task_id,
            step_id=step.id,
            tool_name=plan_step.tool_name,
            args=plan_step.args,
            edition=context.edition,
        )

        if not policy_result.allowed:
            # P0.5 (G-02 fix): distinguish "denied" from "needs approval".
            # Previously, requires_approval was a returned field that the
            # executor ignored — high-risk tools executed immediately.
            # Now policy_engine returns allowed=False with requires_approval=True
            # for high-risk tools, and we suspend the step instead of rejecting.
            if policy_result.requires_approval:
                # Suspend step: mark AWAITING_APPROVAL, broadcast, do NOT execute.
                # Orchestrator.resume_after_approval (P1) will re-enter here
                # after the approval is resolved.
                await ra(
                    TaskRepository.update_step, step.id, TaskStepUpdate(
                        status=StepStatus.PENDING,  # awaiting approval; P1 adds AWAITING_APPROVAL
                        requires_approval=True,
                        error=policy_result.reason,
                    )
                )
                await ra(
                    AuditRepository.create, AuditEventCreate(
                        task_id=task_id, step_id=step.id,
                        event_type=AuditEventType.POLICY_APPROVED,  # policy passed, awaiting human
                        detail={
                            "tool_name": plan_step.tool_name,
                            "requires_approval": True,
                            "risk_level": policy_result.risk_level,
                        },
                    )
                )
                await _ws_broadcast(task_id, "step_awaiting_approval", {
                    "step_id": step.id, "tool": plan_step.tool_name,
                    "risk_level": policy_result.risk_level,
                    "reason": policy_result.reason,
                })
                logger.info(
                    "Step %s suspended awaiting approval (tool=%s risk=%s)",
                    step.id, plan_step.tool_name, policy_result.risk_level,
                )
                return {
                    "step": plan_step.step_id,
                    "tool": plan_step.tool_name,
                    "status": "awaiting_approval",
                    "reason": policy_result.reason,
                }, True  # should_fail=True stops the plan loop; resume re-enters

            # Genuinely denied by policy
            await ra(
                TaskRepository.update_step, step.id, TaskStepUpdate(
                    status=StepStatus.REJECTED,
                    error=policy_result.reason,
                )
            )
            await ra(
                AuditRepository.create, AuditEventCreate(
                    task_id=task_id, step_id=step.id,
                    event_type=AuditEventType.POLICY_REJECTED,
                    detail={"tool_name": plan_step.tool_name, "reason": policy_result.reason},
                )
            )
            await _ws_broadcast(task_id, "step_rejected", {
                "step_id": step.id, "tool": plan_step.tool_name,
                "reason": policy_result.reason,
            })
            return {
                "step": plan_step.step_id,
                "tool": plan_step.tool_name,
                "status": "rejected",
                "reason": policy_result.reason,
            }, True

        token_hash = hashlib.sha256(policy_result.token.encode()).hexdigest()[:32]
        await ra(
            TaskRepository.update_step, step.id, TaskStepUpdate(
                capability_token_hash=token_hash,
            )
        )
        await ra(
            AuditRepository.create, AuditEventCreate(
                task_id=task_id, step_id=step.id,
                event_type=AuditEventType.POLICY_APPROVED,
                detail={"tool_name": plan_step.tool_name},
            )
        )

        # ── P3.0-4: Route through ToolGateway when orchestrator is available ──
        if self._execution_orchestrator is not None:
            result = await self._execute_via_orchestrator(
                task_id=task_id,
                step_id=step.id,
                plan_step=plan_step,
                policy_result=policy_result,
                context=context,
                ra=ra,
            )
        else:
            result = await self._execute_step_with_retry(
                task_id=task_id,
                step_id=step.id,
                tool_name=plan_step.tool_name,
                args=plan_step.args,
                capability_token=policy_result.token,
                context=context,
                ra=ra,
            )

        await _ws_broadcast(task_id, "step_completed" if result.success else "step_failed", {
            "step_id": step.id, "tool": plan_step.tool_name,
            "success": result.success,
        })

        return {
            "step": plan_step.step_id,
            "tool": plan_step.tool_name,
            "status": "completed" if result.success else "failed",
            "output": result.output,
            "artifacts": result.artifacts,
            "_raw_result": result,
        }, False

    async def _finalize_task(
        self,
        task_id: str,
        results: list[dict[str, Any]],
        failed: bool,
        cancelled: bool = False,
        *,
        ra,
        plan_duration: float = 0.0,
    ) -> None:
        t = await ra(TaskRepository.get_by_id, task_id, False)
        notify_user = t.user_id if t and t.user_id else "default"

        if cancelled:
            logger.info("Task %s: execution cancelled (%d/%d steps completed)", task_id,
                        sum(1 for r in results if r["status"] == "completed"), len(results))
            await ra(TaskRepository.update, task_id, TaskUpdate(status=TaskStatus.CANCELLED))
            await _ws_broadcast(task_id, "task_cancelled", {
                "steps_completed": sum(1 for r in results if r["status"] == "completed"),
            })
            await ra(
                AuditRepository.create, AuditEventCreate(
                    task_id=task_id,
                    event_type=AuditEventType.TASK_CANCELLED,
                    detail={"steps_completed": sum(1 for r in results if r["status"] == "completed")},
                )
            )
            await _notify(
                user_id=notify_user,
                ntype="task_cancelled",
                title="Task Cancelled",
                message=f"Task {task_id} has been cancelled.",
                data={"task_id": task_id},
            )
        elif failed:
            logger.info("Task %s: execution failed (%d/%d steps completed)", task_id,
                        sum(1 for r in results if r["status"] == "completed"), len(results))
            await ra(TaskRepository.update, task_id, TaskUpdate(status=TaskStatus.FAILED))
            await _ws_broadcast(task_id, "task_failed", {
                "steps_completed": sum(1 for r in results if r["status"] == "completed"),
            })
            await ra(
                AuditRepository.create, AuditEventCreate(
                    task_id=task_id,
                    event_type=AuditEventType.TASK_FAILED,
                    detail={"steps_completed": sum(1 for r in results if r["status"] == "completed")},
                )
            )
            await _notify(
                user_id=notify_user,
                ntype="task_failed",
                title="Task Failed",
                message=f"Task {task_id} has failed.",
                data={"task_id": task_id},
            )
        else:
            logger.info("Task %s: execution completed successfully (%d steps)", task_id, len(results))
            await ra(TaskRepository.update, task_id, TaskUpdate(status=TaskStatus.COMPLETED))
            await _ws_broadcast(task_id, "task_completed", {
                "steps_completed": len(results),
            })
            await ra(
                AuditRepository.create, AuditEventCreate(
                    task_id=task_id,
                    event_type=AuditEventType.TASK_COMPLETED,
                    detail={"steps_completed": len(results)},
                )
            )
            await _notify(
                user_id=notify_user,
                ntype="task_completed",
                title="Task Completed",
                message=f"Task {task_id} completed successfully.",
                data={"task_id": task_id},
            )

            # Record skill benchmark if skills were used
            if plan_duration > 0:
                try:
                    from packages.db.repositories.skill_repo import SkillRepository
                    runs = await ra(SkillRepository.get_runs_by_task, task_id)
                    if runs:
                        avg_without = await ra(
                            TaskRepository.get_avg_duration_without_skill,
                            "enterprise",
                        )
                        if avg_without:
                            for run in runs:
                                await ra(
                                    SkillRepository.update_run_benchmark,
                                    run.id,
                                    plan_duration,
                                    avg_without,
                                )
                except Exception as e:
                    logger.debug("Skill benchmark recording failed: %s", e)

    async def _execute_via_orchestrator(
        self,
        *,
        task_id: str,
        step_id: str,
        plan_step: Any,
        policy_result: Any,
        context: ExecutionContext,
        ra,
    ) -> Any:
        """Execute a step through ExecutionOrchestrator → ToolGateway.

        This is the P3.0 production path. Replaces the old tool_runner.run()
        direct call. The orchestrator handles grant/lease/effect/gateway
        internally.

        Retry policy: UNKNOWN_OUTCOME on non-idempotent effects → no retry
        (human reconciliation required). FAILED on idempotent → one retry.
        """
        from packages.db.models import ReceiptStatusDB

        # First attempt via orchestrator (no asyncio.run — pure async).
        step_result = await self._orchestrator_execute(
            task_id=task_id, step_id=step_id,
            plan_step=plan_step, policy_result=policy_result,
            context=context,
        )

        # Gateway failure → evaluate retry eligibility
        if not step_result.success:
            receipt = getattr(step_result, "receipt_status", None)
            effect_class = getattr(step_result, "effect_class", None)

            # UNKNOWN_OUTCOME on non-idempotent: NO auto-retry
            if receipt == ReceiptStatusDB.UNKNOWN and effect_class is not None:
                from packages.db.models import EffectClassDB
                if effect_class != EffectClassDB.READ_ONLY:
                    logger.error(
                        "Step %s (%s): UNKNOWN_OUTCOME on non-idempotent effect — "
                        "no auto-retry, requires human reconciliation",
                        step_id, plan_step.tool_name,
                    )
                    await ra(
                        AuditRepository.create, AuditEventCreate(
                            task_id=task_id, step_id=step_id,
                            event_type=AuditEventType.STEP_FAILED,
                            detail={
                                "tool_name": plan_step.tool_name,
                                "error": step_result.error,
                                "receipt_status": "UNKNOWN",
                                "retry_skipped": True,
                                "reason": "non-idempotent unknown outcome",
                            },
                        )
                    )
                    # Wrap as a ToolResult-compatible object for the caller
                    from packages.executor.tools.base import ToolResult
                    return ToolResult(
                        success=False,
                        error=f"UNKNOWN_OUTCOME: {step_result.error}",
                        artifacts=step_result.artifacts or [],
                    )

            # Deterministic FAILED or idempotent UNKNOWN: one retry via orchestrator
            logger.warning(
                "Step %s (%s) failed (receipt=%s), retrying once via orchestrator: %s",
                step_id, plan_step.tool_name,
                receipt, step_result.error,
            )
            await ra(
                AuditRepository.create, AuditEventCreate(
                    task_id=task_id, step_id=step_id,
                    event_type=AuditEventType.STEP_FAILED,
                    detail={"tool_name": plan_step.tool_name, "error": step_result.error, "retry": True},
                )
            )

            step_result = await self._orchestrator_execute(
                task_id=task_id, step_id=step_id,
                plan_step=plan_step, policy_result=policy_result,
                context=context,
            )

        # Convert StepExecutionResult to ToolResult-compatible for caller
        from packages.executor.tools.base import ToolResult
        return ToolResult(
            success=step_result.success,
            output=step_result.output or "",
            error=step_result.error,
            artifacts=step_result.artifacts or [],
        )

    async def _orchestrator_execute(
        self,
        *,
        task_id: str,
        step_id: str,
        plan_step: Any,
        policy_result: Any,
        context: ExecutionContext,
    ) -> Any:
        """Single attempt through execution_orchestrator.execute_step_async()."""
        step_result = await self._execution_orchestrator.execute_step_async(
            task_id=task_id,
            step_id=step_id,
            tool_name=plan_step.tool_name,
            args=plan_step.args,
            edition=context.edition,
            tenant_id=getattr(context, "tenant_id", "default"),
            workspace_root=context.workspace_root,
        )
        return step_result

    async def _execute_step_with_retry(
        self,
        task_id: str,
        step_id: str,
        tool_name: str,
        args: dict[str, Any],
        capability_token: str,
        context: ExecutionContext,
        *,
        ra,
    ) -> Any:
        """Execute a step with one retry on failure and timeout protection."""

        result = await self._run_with_timeout(
            task_id, step_id, tool_name, args, capability_token, context,
        )

        if not result.success:
            logger.warning(
                "Step %s (%s) failed, retrying once: %s",
                step_id, tool_name, result.error,
            )
            await ra(
                AuditRepository.create, AuditEventCreate(
                    task_id=task_id, step_id=step_id,
                    event_type=AuditEventType.STEP_FAILED,
                    detail={"tool_name": tool_name, "error": result.error, "retry": True},
                )
            )

            retry_step = await ra(
                TaskRepository.add_step, task_id, TaskStepCreate(
                    step_order=9000 + hash(step_id) % 1000,
                    tool_name=tool_name,
                    args=args,
                )
            )

            retry_policy = self.policy_engine.check(
                task_id=task_id,
                step_id=retry_step.id,
                tool_name=tool_name,
                args=args,
                edition=context.edition,
            )
            retry_token = retry_policy.token if retry_policy.allowed else capability_token

            result = await self._run_with_timeout(
                task_id, retry_step.id, tool_name, args, retry_token, context,
            )

            if result.success:
                logger.info("Step %s retry succeeded", step_id)
            else:
                logger.warning("Step %s retry also failed: %s", step_id, result.error)

        return result

    async def _run_with_timeout(
        self,
        task_id: str,
        step_id: str,
        tool_name: str,
        args: dict[str, Any],
        capability_token: str,
        context: ExecutionContext,
        db: Any = None,
    ) -> Any:
        """Execute a single tool run with timeout protection."""
        timeout = self._step_timeout or _get_step_timeout()
        try:
            return await asyncio.wait_for(
                self.tool_runner.run(
                    task_id=task_id,
                    step_id=step_id,
                    tool_name=tool_name,
                    args=args,
                    capability_token=capability_token,
                    context=context,
                    db=self._test_db,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            from packages.executor.tools.base import ToolResult
            logger.error(
                "Step %s (%s) timed out after %ds",
                step_id, tool_name, timeout,
            )
            return ToolResult(
                success=False,
                output="",
                error=f"Step timed out after {timeout}s",
                artifacts=[],
            )

    async def _try_replan(
        self,
        task_id: str,
        failed_step: Any,
        error: str | None,
        context: ExecutionContext,
        ra,
    ) -> Plan | None:
        """Attempt to re-plan from the failure point."""
        if self.planner is None:
            return None

        task = await ra(TaskRepository.get_by_id, task_id)
        if task is None:
            return None

        replan_prompt = (
            f"Original goal: {task.goal}\n"
            f"Step '{failed_step.tool_name}' failed with error: {error}\n"
            f"Please generate an alternative plan to accomplish the remaining goal. "
            f"Use different tools or approaches if possible."
        )

        try:
            logger.info("Attempting re-plan for task %s after step failure", task_id)
            recovery_plan = await self.planner.plan(
                goal=replan_prompt,
                edition=context.edition,
            )
            await ra(
                AuditRepository.create, AuditEventCreate(
                    task_id=task_id,
                    event_type=AuditEventType.PLAN_GENERATED,
                    detail={"steps_count": len(recovery_plan.steps), "is_recovery": True},
                )
            )
            return recovery_plan
        except Exception as exc:
            logger.warning("Re-planning failed for task %s: %s", task_id, exc)
            return None

    async def _execute_recovery_step(
        self,
        *,
        task_id: str,
        step: Any,
        plan_step: Any,
        policy_result: Any,
        context: ExecutionContext,
    ) -> Any:
        """Execute a recovery plan step via orchestrator when available."""
        if self._execution_orchestrator is not None:
            from packages.executor.tools.base import ToolResult
            step_result = await self._execution_orchestrator.execute_step_async(
                task_id=task_id,
                step_id=step.id,
                tool_name=plan_step.tool_name,
                args=plan_step.args,
                edition=context.edition,
                tenant_id=getattr(context, "tenant_id", "default"),
                workspace_root=context.workspace_root,
            )
            return ToolResult(
                success=step_result.success,
                output=step_result.output or "",
                error=step_result.error,
                artifacts=step_result.artifacts or [],
            )
        # Fallback to old path (dev/test only)
        return await self._run_with_timeout(
            task_id=task_id,
            step_id=step.id,
            tool_name=plan_step.tool_name,
            args=plan_step.args,
            capability_token=policy_result.token,
            context=context,
        )

    async def _execute_recovery(
        self,
        task_id: str,
        recovery_plan: Plan,
        context: ExecutionContext,
        ra,
    ) -> list[dict[str, Any]]:
        """Execute a recovery plan. Returns results list."""
        results = []

        for plan_step in recovery_plan.steps:
            step = await ra(
                TaskRepository.add_step, task_id, TaskStepCreate(
                    step_order=plan_step.step_id + 100,
                    tool_name=plan_step.tool_name,
                    args=plan_step.args,
                )
            )

            policy_result = self.policy_engine.check(
                task_id=task_id,
                step_id=step.id,
                tool_name=plan_step.tool_name,
                args=plan_step.args,
                edition=context.edition,
            )

            if not policy_result.allowed:
                await ra(
                    TaskRepository.update_step, step.id, TaskStepUpdate(
                        status=StepStatus.REJECTED,
                        error=policy_result.reason,
                    )
                )
                results.append({
                    "step": plan_step.step_id + 100,
                    "tool": plan_step.tool_name,
                    "status": "rejected",
                    "reason": policy_result.reason,
                })
                continue

            result = await self._execute_recovery_step(
                task_id=task_id,
                step=step,
                plan_step=plan_step,
                policy_result=policy_result,
                context=context,
            )

            results.append({
                "step": plan_step.step_id + 100,
                "tool": plan_step.tool_name,
                "status": "completed" if result.success else "failed",
                "output": result.output,
                "artifacts": result.artifacts,
                "is_recovery": True,
            })

        return results
