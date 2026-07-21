"""Tool Runner — executes a single tool with policy + token verification."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from packages.agent_core.schemas import AuditEventCreate, TaskStepUpdate
from packages.db.models import AuditEventType, StepStatus
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.task_repo import TaskRepository
from packages.db.session import run_async
from packages.executor.tools.base import ExecutionContext, ToolBase, ToolResult
from packages.policy.capability_token import TokenIssuer

if TYPE_CHECKING:
    from packages.policy.unified_registry import UnifiedToolRegistry

logger = logging.getLogger(__name__)

_SENSITIVE_ARG_KEYS = frozenset({
    "password", "secret", "token", "api_key", "apikey",
    "access_token", "refresh_token", "private_key",
    "credential", "auth", "authorization",
})


def _sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    sanitized = {}
    for k, v in args.items():
        if k.lower() in _SENSITIVE_ARG_KEYS:
            sanitized[k] = "***REDACTED***"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_args(v)
        else:
            sanitized[k] = v
    return sanitized


class ToolRunner:
    def __init__(self, token_issuer: TokenIssuer, registry: UnifiedToolRegistry | None = None):
        self.token_issuer = token_issuer
        self._registry = registry
        # Legacy dict for backward compat when no registry is provided
        self._tools: dict[str, ToolBase] = {}

    def register(self, tool: ToolBase) -> None:
        """Legacy: register a tool instance directly. Prefer UnifiedToolRegistry."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> ToolBase | None:
        if self._registry is not None:
            return self._registry.get_tool_instance(name)
        return self._tools.get(name)

    async def _db_update_step(self, step_id: str, update: TaskStepUpdate, db: Any = None) -> None:
        """Update a step — uses shared session if provided (tests), else independent session."""
        if db is not None:
            await asyncio.to_thread(TaskRepository.update_step, db, step_id, update)
        else:
            await run_async(TaskRepository.update_step, step_id, update)

    async def _db_create_audit(self, event: AuditEventCreate, db: Any = None) -> None:
        """Create an audit event — uses shared session if provided (tests), else independent session."""
        if db is not None:
            await asyncio.to_thread(AuditRepository.create, db, event)
        else:
            await run_async(AuditRepository.create, event)

    async def run(
        self,
        task_id: str,
        step_id: str,
        tool_name: str,
        args: dict[str, Any],
        capability_token: str,
        context: ExecutionContext,
        db: Any = None,
    ) -> ToolResult:
        """Execute a tool after verifying the capability token.

        When *db* is None (production default), each DB operation uses an
        independent session via ``run_async`` — thread-safe for concurrent use.
        When *db* is provided (test backward-compat), the shared session is used.
        """

        # Verify capability token
        valid, reason = self.token_issuer.verify(
            capability_token, task_id, step_id, tool_name, args
        )
        if not valid:
            logger.warning("Token verification failed for %s: %s", tool_name, reason)
            await self._db_update_step(step_id, TaskStepUpdate(
                status=StepStatus.FAILED, error=f"Token verification failed: {reason}"
            ), db)
            await self._db_create_audit(AuditEventCreate(
                task_id=task_id, step_id=step_id,
                event_type=AuditEventType.STEP_FAILED,
                detail={"tool_name": tool_name, "error": reason},
            ), db)
            return ToolResult(success=False, error=f"Token verification failed: {reason}")

        # Get tool
        tool = self.get_tool(tool_name)
        if tool is None:
            error = f"Tool '{tool_name}' not found in runner"
            await self._db_update_step(step_id, TaskStepUpdate(
                status=StepStatus.FAILED, error=error
            ), db)
            return ToolResult(success=False, error=error)

        # Update step to executing
        await self._db_update_step(step_id, TaskStepUpdate(status=StepStatus.EXECUTING), db)
        await self._db_create_audit(AuditEventCreate(
            task_id=task_id, step_id=step_id,
            event_type=AuditEventType.STEP_EXECUTING,
            detail={"tool_name": tool_name, "args": _sanitize_args(args)},
        ), db)

        # Execute
        try:
            result = await asyncio.wait_for(
                tool.execute(args, context),
                timeout=context.tool_timeout,
            )
            if result.success:
                await self._db_update_step(step_id, TaskStepUpdate(
                    status=StepStatus.COMPLETED,
                    result=str(result.output) if result.output else None,
                ), db)
                await self._db_create_audit(AuditEventCreate(
                    task_id=task_id, step_id=step_id,
                    event_type=AuditEventType.STEP_COMPLETED,
                    detail={"tool_name": tool_name, "artifacts": result.artifacts},
                ), db)
            else:
                await self._db_update_step(step_id, TaskStepUpdate(
                    status=StepStatus.FAILED, error=result.error
                ), db)
                await self._db_create_audit(AuditEventCreate(
                    task_id=task_id, step_id=step_id,
                    event_type=AuditEventType.STEP_FAILED,
                    detail={"tool_name": tool_name, "error": result.error},
                ), db)
            return result
        except asyncio.TimeoutError:
            error = f"Tool '{tool_name}' timed out after {context.tool_timeout}s"
            logger.warning(error)
            await self._db_update_step(step_id, TaskStepUpdate(
                status=StepStatus.FAILED, error=error
            ), db)
            await self._db_create_audit(AuditEventCreate(
                task_id=task_id, step_id=step_id,
                event_type=AuditEventType.STEP_FAILED,
                detail={"tool_name": tool_name, "error": error, "timeout": True},
            ), db)
            return ToolResult(success=False, error=error)
        except asyncio.CancelledError:
            error = f"Tool '{tool_name}' execution cancelled"
            logger.warning(error)
            await self._db_update_step(step_id, TaskStepUpdate(
                status=StepStatus.FAILED, error=error
            ), db)
            await self._db_create_audit(AuditEventCreate(
                task_id=task_id, step_id=step_id,
                event_type=AuditEventType.STEP_FAILED,
                detail={"tool_name": tool_name, "error": error, "cancelled": True},
            ), db)
            raise
        except Exception as e:
            logger.exception("Tool execution error: %s - %s", tool_name, e)
            await self._db_update_step(step_id, TaskStepUpdate(
                status=StepStatus.FAILED, error=str(e)
            ), db)
            await self._db_create_audit(AuditEventCreate(
                task_id=task_id, step_id=step_id,
                event_type=AuditEventType.STEP_FAILED,
                detail={"tool_name": tool_name, "error": str(e)},
            ), db)
            return ToolResult(success=False, error=str(e))
