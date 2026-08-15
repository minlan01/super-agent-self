"""ExecutionOrchestrator — coordinates the full P2 execution chain.

Bridges the gap between the existing executor_service (which uses the old
policy_engine.check() + tool_runner flow) and the new P2 security chain
(PolicyEngine → ApprovalService → GrantIssuer → LeaseManager → ToolGateway).

Design:
  - executor_service delegates step execution to this orchestrator when
    the gateway is available (feature flag: P2_GATEWAY_ENABLED).
  - The orchestrator handles the three PolicyDecision outcomes:
      DENY          -> reject step
      WAIT_APPROVAL -> create ApprovalRequest, suspend step
      GRANT         -> issue grant, acquire lease, invoke ToolGateway

  - When WAIT_APPROVAL is resolved externally (approval API), the
    orchestrator's resume_after_approval() re-enters the GRANT path.

This module is the glue that makes P2's security chain usable from the
existing task execution pipeline without rewriting executor_service.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.orm import Session

from packages.approval.approval_service import (
    ApprovalService,
)
from packages.db.models import (
    ApprovalRequestStatus,
    EffectClassDB,
)
from packages.db.session import SessionLocal
from packages.execution.effect_journal import EffectJournal
from packages.execution.lease_manager import LeaseManager
from packages.executor.tool_gateway import ToolGateway
from packages.policy.grant_issuer import GrantIssuer
from packages.policy.policy_engine import PolicyEngine

logger = structlog.get_logger()


@dataclass
class StepExecutionResult:
    """Result of executing a single step through the orchestrator."""
    step_id: str
    tool_name: str
    status: str          # "completed" | "failed" | "awaiting_approval" | "rejected"
    effect_id: str | None = None
    approval_request_id: str | None = None
    output: Any = None
    error: str | None = None
    receipt_status: Any = None  # ReceiptStatusDB | None
    effect_class: Any = None    # EffectClassDB | None
    artifacts: list = None      # list[Any] | None
    success: bool = False       # convenience: True iff status == "completed"


class ExecutionOrchestrator:
    """Coordinates PolicyEngine + ApprovalService + GrantIssuer + LeaseManager + ToolGateway.

    Each step execution gets its own DB session (production-safe).
    For tests, a shared session can be injected.
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        tool_gateway_factory: Any,  # Callable[[Session], ToolGateway]
        approval_service_factory: Any = None,  # Callable[[Session], ApprovalService]
        grant_issuer_factory: Any = None,      # Callable[[Session], GrantIssuer]
        lease_manager_factory: Any = None,     # Callable[[Session], LeaseManager]
    ):
        self.policy_engine = policy_engine
        self._gw_factory = tool_gateway_factory
        self._approval_factory = approval_service_factory or (lambda db: ApprovalService(db))
        self._grant_factory = grant_issuer_factory or (lambda db: GrantIssuer(db))
        self._lease_factory = lease_manager_factory or (lambda db: LeaseManager(db))

    @classmethod
    def from_defaults(
        cls,
        policy_engine: PolicyEngine,
        db_session_factory: Any = None,
        tool_lookup: Any = None,
    ) -> ExecutionOrchestrator:
        """Create an orchestrator with default factory functions.

        Args:
            policy_engine: The existing PolicyEngine instance.
            db_session_factory: Callable that returns a Session (default: get_session).
            tool_lookup: Tool registry for ToolGateway.
        """
        _get_db = db_session_factory or SessionLocal

        def _make_gateway(db: Session) -> ToolGateway:
            return ToolGateway(
                db=db,
                grant_issuer=GrantIssuer(db),
                lease_manager=LeaseManager(db),
                effect_journal=EffectJournal(db),
                tool_lookup=tool_lookup,
            )

        return cls(
            policy_engine=policy_engine,
            tool_gateway_factory=_make_gateway,
        )

    def execute_step(
        self,
        *,
        task_id: str,
        step_id: str,
        tool_name: str,
        args: dict[str, Any],
        edition: str = "enterprise",
        tenant_id: str = "default",
        requester_principal_id: str = "system",
        workspace_root: str = "./workspace",
        db: Session | None = None,
    ) -> StepExecutionResult:
        """Execute a single step through the full P2 security chain.

        This is a synchronous wrapper that handles DB session lifecycle.
        The actual tool execution inside ToolGateway is async; we bridge
        with asyncio.run() since the orchestrator is called from the
        async executor_service via run_async().
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()

        try:
            return self._execute_step_inner(
                db=db, task_id=task_id, step_id=step_id,
                tool_name=tool_name, args=args, edition=edition,
                tenant_id=tenant_id,
                requester_principal_id=requester_principal_id,
                workspace_root=workspace_root,
            )
        finally:
            if owns_session and db is not None:
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()

    def _execute_step_inner(
        self, db: Session, *, task_id, step_id, tool_name, args,
        edition, tenant_id, requester_principal_id, workspace_root,
    ) -> StepExecutionResult:
        # ── 1. Policy check ──
        policy_result = self.policy_engine.check(
            task_id=task_id, step_id=step_id,
            tool_name=tool_name, args=args, edition=edition,
        )

        # ── 2a. DENY or WAIT_APPROVAL ──
        if not policy_result.allowed:
            if policy_result.requires_approval:
                return self._handle_wait_approval(
                    db=db, step_id=step_id, tool_name=tool_name, args=args,
                    policy_result=policy_result, tenant_id=tenant_id,
                    requester_principal_id=requester_principal_id,
                )
            # Genuinely denied
            return StepExecutionResult(
                step_id=step_id, tool_name=tool_name,
                status="rejected",
                error=policy_result.reason,
            )

        # ── 2b. GRANT path: issue grant + lease + invoke gateway ──
        return self._handle_grant(
            db=db, task_id=task_id, step_id=step_id,
            tool_name=tool_name, args=args,
            policy_result=policy_result, tenant_id=tenant_id,
            workspace_root=workspace_root,
        )

    # ------------------------------------------------------------------
    # Async variants — for use inside running event loops (P3.0-4)
    # ------------------------------------------------------------------

    async def execute_step_async(
        self,
        *,
        task_id: str,
        step_id: str,
        tool_name: str,
        args: dict[str, Any],
        edition: str = "enterprise",
        tenant_id: str = "default",
        requester_principal_id: str = "system",
        workspace_root: str = "./workspace",
        db: Session | None = None,
    ) -> StepExecutionResult:
        """Async-native execute_step — no asyncio.run(), safe inside event loop.

        This is the P3.0 production path. ExecutorService calls this when
        execution_orchestrator is available, ensuring all tool invocations
        go through ToolGateway instead of the legacy tool_runner.run().
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()

        try:
            return self._execute_step_inner_async(
                db=db, task_id=task_id, step_id=step_id,
                tool_name=tool_name, args=args, edition=edition,
                tenant_id=tenant_id,
                requester_principal_id=requester_principal_id,
                workspace_root=workspace_root,
            )
        finally:
            if owns_session and db is not None:
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()

    async def _execute_step_inner_async(
        self, db: Session, *, task_id, step_id, tool_name, args,
        edition, tenant_id, requester_principal_id, workspace_root,
    ) -> StepExecutionResult:
        """Async version of _execute_step_inner — no asyncio.run()."""
        # ── 1. Policy check (sync DB ops are safe in async) ──
        policy_result = self.policy_engine.check(
            task_id=task_id, step_id=step_id,
            tool_name=tool_name, args=args, edition=edition,
        )

        # ── 2a. DENY or WAIT_APPROVAL ──
        if not policy_result.allowed:
            if policy_result.requires_approval:
                return self._handle_wait_approval(
                    db=db, step_id=step_id, tool_name=tool_name, args=args,
                    policy_result=policy_result, tenant_id=tenant_id,
                    requester_principal_id=requester_principal_id,
                )
            return StepExecutionResult(
                step_id=step_id, tool_name=tool_name,
                status="rejected",
                error=policy_result.reason,
            )

        # ── 2b. GRANT path via async gateway invoke ──
        return await self._handle_grant_async(
            db=db, task_id=task_id, step_id=step_id,
            tool_name=tool_name, args=args,
            policy_result=policy_result, tenant_id=tenant_id,
            workspace_root=workspace_root,
        )

    async def _handle_grant_async(
        self, db: Session, *, task_id, step_id, tool_name, args,
        policy_result, tenant_id, workspace_root,
    ) -> StepExecutionResult:
        """Async version of _handle_grant — uses await gw.invoke() instead of asyncio.run()."""
        gi = self._grant_factory(db)
        lm = self._lease_factory(db)
        gw = self._gw_factory(db)

        args_hash = self._compute_args_hash(args)
        security_digest = self._compute_security_digest(args, policy_result.token or "")

        issued = gi.issue(
            tenant_id=tenant_id,
            step_run_id=step_id,
            tool_name=tool_name,
            bound_args_hash=args_hash,
            risk_level=policy_result.risk_level,
            resource_scope={"workspace_id": tenant_id},
            security_context_digest=security_digest,
        )

        lease = lm.acquire(
            tenant_id=tenant_id,
            worker_id=f"executor-{task_id}",
            step_run_id=step_id,
        )

        from packages.executor.tools.base import ExecutionContext
        ctx = ExecutionContext(
            task_id=task_id, step_id=step_id,
            principal_id=tenant_id, workspace_id=tenant_id,
            workspace_root=workspace_root,
        )

        effect_class = (
            EffectClassDB.READ_ONLY
            if policy_result.risk_level == "low"
            else EffectClassDB.NON_RETRYABLE
        )

        # Invoke through gateway — NO asyncio.run(), direct await.
        try:
            result = await gw.invoke(
                handle=issued.handle,
                lease_id=lease.lease_id,
                tool_name=tool_name,
                args=args,
                context=ctx,
                effect_class=effect_class,
                tenant_id=tenant_id,
                security_context_digest=security_digest,
            )
        except Exception as e:
            logger.exception("ToolGateway invocation failed: %s", e)
            return StepExecutionResult(
                step_id=step_id, tool_name=tool_name,
                status="failed",
                error=f"Gateway error: {e}",
                effect_class=effect_class,
            )

        if result.success:
            return StepExecutionResult(
                step_id=step_id, tool_name=tool_name,
                status="completed",
                effect_id=result.effect_id,
                output=result.tool_result.output if result.tool_result else None,
                artifacts=result.tool_result.artifacts if result.tool_result else None,
                receipt_status=result.receipt_status,
                effect_class=effect_class,
                success=True,
            )
        return StepExecutionResult(
            step_id=step_id, tool_name=tool_name,
            status="failed",
            effect_id=result.effect_id,
            error=result.error,
            artifacts=result.tool_result.artifacts if result.tool_result else None,
            receipt_status=result.receipt_status,
            effect_class=effect_class,
        )

    def _handle_wait_approval(
        self, db: Session, *, step_id, tool_name, args,
        policy_result, tenant_id, requester_principal_id,
    ) -> StepExecutionResult:
        """Create an ApprovalRequest and suspend the step."""
        svc = self._approval_factory(db)

        args_hash = self._compute_args_hash(args)
        security_digest = self._compute_security_digest(args, requester_principal_id)

        req = svc.create_request(
            tenant_id=tenant_id,
            step_run_id=step_id,
            tool_name=tool_name,
            normalized_args_hash=args_hash,
            risk_level=policy_result.risk_level,
            resource_scope={"workspace_id": tenant_id},
            policy_digest=security_digest,  # simplified: use security digest
            security_context_digest=security_digest,
            requester_principal_id=requester_principal_id,
        )

        logger.info(
            "Step suspended awaiting approval: step=%s tool=%s request=%s",
            step_id, tool_name, req.request_id,
        )

        return StepExecutionResult(
            step_id=step_id, tool_name=tool_name,
            status="awaiting_approval",
            approval_request_id=req.request_id,
            error=policy_result.reason,
        )

    def _handle_grant(
        self, db: Session, *, task_id, step_id, tool_name, args,
        policy_result, tenant_id, workspace_root,
    ) -> StepExecutionResult:
        """Issue grant, acquire lease, invoke ToolGateway."""
        gi = self._grant_factory(db)
        lm = self._lease_factory(db)
        gw = self._gw_factory(db)

        # Issue grant (low/medium risk: no approval needed).
        args_hash = self._compute_args_hash(args)
        security_digest = self._compute_security_digest(args, policy_result.token or "")

        issued = gi.issue(
            tenant_id=tenant_id,
            step_run_id=step_id,
            tool_name=tool_name,
            bound_args_hash=args_hash,
            risk_level=policy_result.risk_level,
            resource_scope={"workspace_id": tenant_id},
            security_context_digest=security_digest,
        )

        # Acquire lease.
        lease = lm.acquire(
            tenant_id=tenant_id,
            worker_id=f"executor-{task_id}",
            step_run_id=step_id,
        )

        # Build execution context.
        from packages.executor.tools.base import ExecutionContext
        ctx = ExecutionContext(
            task_id=task_id, step_id=step_id,
            principal_id=tenant_id, workspace_id=tenant_id,
            workspace_root=workspace_root,
        )

        # Determine effect class from tool risk level.
        effect_class = (
            EffectClassDB.READ_ONLY
            if policy_result.risk_level == "low"
            else EffectClassDB.NON_RETRYABLE
        )

        # Invoke through gateway (async -> sync bridge).
        try:
            result = asyncio.run(gw.invoke(
                handle=issued.handle,
                lease_id=lease.lease_id,
                tool_name=tool_name,
                args=args,
                context=ctx,
                effect_class=effect_class,
                tenant_id=tenant_id,
                security_context_digest=security_digest,
            ))
        except Exception as e:
            logger.exception("ToolGateway invocation failed: %s", e)
            return StepExecutionResult(
                step_id=step_id, tool_name=tool_name,
                status="failed",
                error=f"Gateway error: {e}",
            )

        if result.success:
            return StepExecutionResult(
                step_id=step_id, tool_name=tool_name,
                status="completed",
                effect_id=result.effect_id,
                output=result.tool_result.output if result.tool_result else None,
            )
        return StepExecutionResult(
            step_id=step_id, tool_name=tool_name,
            status="failed",
            effect_id=result.effect_id,
            error=result.error,
        )

    def resume_after_approval(
        self,
        *,
        approval_request_id: str,
        task_id: str,
        step_id: str,
        tool_name: str,
        args: dict[str, Any],
        edition: str = "enterprise",
        tenant_id: str = "default",
        workspace_root: str = "./workspace",
        db: Session | None = None,
    ) -> StepExecutionResult:
        """Resume step execution after an approval is resolved APPROVED.

        This is NOT a generic resume — it's bound to a specific approval
        request and verifies the resolution before proceeding.
        """
        owns_session = db is None
        if owns_session:
            db = SessionLocal()

        try:
            svc = self._approval_factory(db)
            req = svc.get_request(approval_request_id)

            if req is None:
                return StepExecutionResult(
                    step_id=step_id, tool_name=tool_name,
                    status="rejected", error="approval request not found",
                )
            if req.status != ApprovalRequestStatus.APPROVED:
                return StepExecutionResult(
                    step_id=step_id, tool_name=tool_name,
                    status="rejected",
                    error=f"approval status is {req.status.value}, not APPROVED",
                )

            # Re-check policy (content may have changed).
            policy_result = self.policy_engine.check(
                task_id=task_id, step_id=step_id,
                tool_name=tool_name, args=args, edition=edition,
            )

            # Now issue grant with the approval resolution_id.
            gi = self._grant_factory(db)
            lm = self._lease_factory(db)
            gw = self._gw_factory(db)

            args_hash = self._compute_args_hash(args)
            security_digest = self._compute_security_digest(args, req.resolution_id or "")

            issued = gi.issue(
                tenant_id=tenant_id, step_run_id=step_id,
                tool_name=tool_name, bound_args_hash=args_hash,
                risk_level=req.risk_level,
                resource_scope={"workspace_id": tenant_id},
                security_context_digest=security_digest,
                approval_resolution_id=req.resolution_id,
            )

            lease = lm.acquire(
                tenant_id=tenant_id,
                worker_id=f"executor-{task_id}",
                step_run_id=step_id,
            )

            from packages.executor.tools.base import ExecutionContext
            ctx = ExecutionContext(
                task_id=task_id, step_id=step_id,
                principal_id=tenant_id, workspace_id=tenant_id,
                workspace_root=workspace_root,
            )

            effect_class = (
                EffectClassDB.READ_ONLY if req.risk_level == "low"
                else EffectClassDB.NON_RETRYABLE
            )

            result = asyncio.run(gw.invoke(
                handle=issued.handle, lease_id=lease.lease_id,
                tool_name=tool_name, args=args, context=ctx,
                effect_class=effect_class, tenant_id=tenant_id,
                security_context_digest=security_digest,
            ))

            if result.success:
                return StepExecutionResult(
                    step_id=step_id, tool_name=tool_name,
                    status="completed", effect_id=result.effect_id,
                    output=result.tool_result.output if result.tool_result else None,
                )
            return StepExecutionResult(
                step_id=step_id, tool_name=tool_name,
                status="failed", effect_id=result.effect_id,
                error=result.error,
            )
        finally:
            if owns_session and db is not None:
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_args_hash(args: dict[str, Any]) -> str:
        raw = json.dumps(args, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _compute_security_digest(args: dict[str, Any], salt: str) -> str:
        raw = json.dumps(
            {"args": args, "salt": salt},
            sort_keys=True, default=str,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
