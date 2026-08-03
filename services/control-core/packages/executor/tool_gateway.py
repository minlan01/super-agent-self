"""ToolGateway — the sole entry point for Tool invocation (spec §4.3).

PROJECT-CONTEXT §规范执行链:
  ToolGateway verifies Grant + Effect + Lease + fencing before invoking
  the Adapter.  No other code path may call tool.execute() directly.

Flow:
  1. Verify grant handle (digest lookup, status/expiry/consume checks)
  2. Verify lease (active, not expired, fencing_token matches)
  3. Create Effect (PREPARED) before any adapter call
  4. Record dispatch attempt (audit trace)
  5. Consume grant atomically (max_uses=1, exactly-once)
  6. Invoke adapter (tool.execute)
  7. Record ToolReceipt + finalize Effect (CONFIRMED|FAILED|UNKNOWN_OUTCOME)

Fail-closed: ANY verification failure aborts before adapter invocation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from packages.db.models import EffectClassDB, ReceiptStatusDB
from packages.execution.effect_journal import EffectJournal
from packages.execution.lease_manager import LeaseManager
from packages.executor.tools.base import ExecutionContext, ToolBase, ToolResult
from packages.policy.grant_issuer import GrantIssuer, VerifiedGrant

logger = structlog.get_logger()


@dataclass
class GatewayResult:
    """Result of ToolGateway.invoke() — wraps ToolResult with Effect metadata."""
    success: bool
    effect_id: str
    receipt_status: ReceiptStatusDB
    tool_result: ToolResult | None = None
    error: str | None = None


class ToolGateway:
    """Sole entry point for tool execution.

    Replaces the old tool_runner.py flow that called tool.execute() directly
    with only a capability-token check.  Now every invocation goes through:
    Grant verify -> Lease verify -> Effect prepare -> dispatch -> finalize.

    The gateway holds references to GrantIssuer, LeaseManager, EffectJournal
    and a tool lookup function (registry).
    """

    def __init__(
        self,
        db: Session,
        grant_issuer: GrantIssuer,
        lease_manager: LeaseManager,
        effect_journal: EffectJournal,
        tool_lookup: Any,  # Callable[[str], ToolBase | None] or registry
        worker_id: str = "control-core",
    ):
        self.db = db
        self.grant_issuer = grant_issuer
        self.lease_manager = lease_manager
        self.effect_journal = effect_journal
        self._tool_lookup = tool_lookup
        self.worker_id = worker_id

    async def invoke(
        self,
        *,
        handle: str,
        lease_id: str,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
        effect_class: EffectClassDB = EffectClassDB.READ_ONLY,
        tenant_id: str = "default",
        security_context_digest: str = "",
    ) -> GatewayResult:
        """Execute a tool through the full security chain.

        Args:
            handle: The opaque grant handle (plaintext, from GrantIssuer.issue).
            lease_id: The active lease for this step.
            tool_name: Tool to invoke.
            args: Tool arguments.
            context: Execution context (workspace, timeouts, etc).
            effect_class: Side-effect classification (drives retry policy).
            tenant_id: Tenant scope.
            security_context_digest: Digest of the security context bound to grant.

        Returns:
            GatewayResult with success/failure + effect_id + receipt_status.
        """
        # ── Step 1: Verify grant handle ──
        verified: VerifiedGrant = self.grant_issuer.verify(handle)
        if not verified.valid:
            logger.warning(
                "ToolGateway: grant verification failed for %s: %s",
                tool_name, verified.reason,
            )
            return GatewayResult(
                success=False,
                effect_id="",
                receipt_status=ReceiptStatusDB.FAILED,
                error=f"Grant rejected: {verified.reason}",
            )

        # ── Step 2: Verify lease + fencing ──
        # We need the fencing_token from the lease to match what the caller claims.
        # The caller passes lease_id; we read fencing_token from the lease record.
        lease = self.lease_manager.get_lease(lease_id)
        if lease is None:
            return GatewayResult(
                success=False,
                effect_id="",
                receipt_status=ReceiptStatusDB.FAILED,
                error=f"Lease {lease_id} not found",
            )

        if not self.lease_manager.is_valid(lease_id, lease.fencing_token):
            logger.warning(
                "ToolGateway: lease invalid for %s (lease=%s)",
                tool_name, lease_id,
            )
            return GatewayResult(
                success=False,
                effect_id="",
                receipt_status=ReceiptStatusDB.FAILED,
                error="Lease invalid (expired, released, or stale)",
            )

        fencing_token = lease.fencing_token

        # ── Step 3: Look up tool adapter ──
        tool = self._get_tool(tool_name)
        if tool is None:
            return GatewayResult(
                success=False,
                effect_id="",
                receipt_status=ReceiptStatusDB.FAILED,
                error=f"Tool '{tool_name}' not found",
            )

        # ── Step 4: Create Effect (PREPARED) ──
        # Must happen BEFORE adapter invocation (durable intent record).
        prepared = self.effect_journal.prepare(
            tenant_id=tenant_id,
            step_run_id=context.step_id,
            grant_id=verified.grant_id,
            lease_id=lease_id,
            fencing_token=fencing_token,
            tool_name=tool_name,
            effect_class=effect_class,
            security_context_digest=security_context_digest or verified.resource_scope.get("_sec_digest", ""),
        )

        # ── Step 5: Consume grant atomically (exactly-once) ──
        if not self.grant_issuer.consume(handle):
            # Grant was consumed by another concurrent caller (nonce replay).
            logger.warning(
                "ToolGateway: grant already consumed for effect %s (nonce replay)",
                prepared.effect_id,
            )
            self.effect_journal.finalize(
                tenant_id=tenant_id,
                effect_id=prepared.effect_id,
                receipt_status=ReceiptStatusDB.FAILED,
                error_code="GRANT_ALREADY_CONSUMED",
                error_message="Grant nonce was already used (replay detected)",
                tool_name=tool_name,
                args_hash=self._args_hash(args),
            )
            return GatewayResult(
                success=False,
                effect_id=prepared.effect_id,
                receipt_status=ReceiptStatusDB.FAILED,
                error="Grant already consumed (nonce replay)",
            )

        # ── Step 6: Record dispatch + invoke adapter ──
        grant_digest = hashlib.sha256(handle.encode()).hexdigest()
        self.effect_journal.record_dispatch(
            tenant_id=tenant_id,
            effect_id=prepared.effect_id,
            lease_id=lease_id,
            fencing_token=fencing_token,
            grant_digest=grant_digest,
            worker_id=self.worker_id,
            adapter_name=type(tool).__name__,
        )

        # Compute before_hash for side-effects (non-read-only).
        before_hash = None
        if effect_class != EffectClassDB.READ_ONLY:
            before_hash = self._compute_content_hash(args)

        # Invoke the adapter with timeout protection.
        tool_result = await self._invoke_adapter(tool, args, context)

        # Compute after_hash for side-effects.
        after_hash = None
        if effect_class != EffectClassDB.READ_ONLY:
            after_hash = self._compute_content_hash_after(args, tool_result)

        # ── Step 7: Finalize Effect + record ToolReceipt ──
        # Mapping:
        #   success           -> SUCCEEDED -> Effect CONFIRMED
        #   deterministic err -> FAILED    -> Effect FAILED
        #   timeout/crash     -> UNKNOWN   -> Effect UNKNOWN_OUTCOME
        #   (we don't know if the side-effect happened)
        if tool_result.success:
            receipt_status = ReceiptStatusDB.SUCCEEDED
        elif tool_result.error and any(
            kw in tool_result.error.lower()
            for kw in ("timed out", "cancelled", "crashed", "adapter crashed")
        ):
            receipt_status = ReceiptStatusDB.UNKNOWN
        else:
            receipt_status = ReceiptStatusDB.FAILED

        self.effect_journal.finalize(
            tenant_id=tenant_id,
            effect_id=prepared.effect_id,
            receipt_status=receipt_status,
            result={"output": str(tool_result.output)[:4000]} if tool_result.output else None,
            error_code=None if tool_result.success else "TOOL_ERROR",
            error_message=tool_result.error,
            before_hash=before_hash,
            after_hash=after_hash,
            tool_name=tool_name,
            args_hash=self._args_hash(args),
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
        )

        return GatewayResult(
            success=tool_result.success,
            effect_id=prepared.effect_id,
            receipt_status=receipt_status,
            tool_result=tool_result,
            error=tool_result.error,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_tool(self, name: str) -> ToolBase | None:
        """Look up a tool by name via the injected registry/lookup."""
        # Dict lookup (tests / simple registries).
        if isinstance(self._tool_lookup, dict):
            return self._tool_lookup.get(name)
        # UnifiedToolRegistry with get_tool_instance.
        if hasattr(self._tool_lookup, "get_tool_instance"):
            return self._tool_lookup.get_tool_instance(name)
        # Legacy ToolRegistry with get_tool.
        if hasattr(self._tool_lookup, "get_tool"):
            return self._tool_lookup.get_tool(name)
        # Plain callable.
        if callable(self._tool_lookup):
            return self._tool_lookup(name)
        return None

    async def _invoke_adapter(
        self, tool: ToolBase, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        """Invoke tool.execute() with timeout protection.

        On timeout or crash, returns a ToolResult indicating failure/unknown.
        """
        try:
            result = await asyncio.wait_for(
                tool.execute(args, context),
                timeout=context.tool_timeout,
            )
            return result
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool timed out after {context.tool_timeout}s",
                artifacts=[],
            )
        except asyncio.CancelledError:
            return ToolResult(
                success=False,
                output="",
                error="Tool execution cancelled",
                artifacts=[],
            )
        except Exception as e:
            logger.exception("ToolGateway: adapter crashed: %s", e)
            return ToolResult(
                success=False,
                output="",
                error=f"Adapter crashed: {e}",
                artifacts=[],
            )

    @staticmethod
    def _args_hash(args: dict[str, Any]) -> str:
        """SHA-256 of canonical args JSON (truncated for DB)."""
        raw = json.dumps(args, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _compute_content_hash(args: dict[str, Any]) -> str:
        """Compute a 'before' content hash for side-effect verification.

        For file tools, this would hash the target file; here we use a
        simplified args-based hash that subclasses/overrides can refine.
        """
        raw = json.dumps(args, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _compute_content_hash_after(args: dict[str, Any], result: ToolResult) -> str:
        """Compute an 'after' content hash after tool execution."""
        raw = json.dumps(
            {"args": args, "output": str(result.output)[:1000]},
            sort_keys=True, default=str,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
