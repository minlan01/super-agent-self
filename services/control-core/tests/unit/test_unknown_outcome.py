"""P3.0-4 Gate: Verify UNKNOWN_OUTCOME handling for non-idempotent effects.

When a tool execution results in UNKNOWN_OUTCOME (timeout, crash, cancel),
and the effect is non-idempotent (side-effects may have occurred), the
executor must NOT automatically retry — human reconciliation is required.

This test verifies:
1. UNKNOWN_OUTCOME + non-idempotent → no retry
2. FAILED + idempotent → one retry allowed
3. ReceiptStatusDB.UNKNOWN is properly propagated through StepExecutionResult
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.db.models import EffectClassDB, ReceiptStatusDB


@pytest.mark.asyncio
async def test_unknown_outcome_non_idempotent_no_retry():
    """UNKNOWN_OUTCOME on NON_RETRYABLE effect must not trigger auto-retry."""
    from packages.executor.executor_service import ExecutorService

    # Track call count
    call_count = 0

    async def mock_execute_step_async(**kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.status = "failed"
        mock_result.error = "Tool timed out after 30s"
        mock_result.output = None
        mock_result.artifacts = []
        mock_result.receipt_status = ReceiptStatusDB.UNKNOWN
        mock_result.effect_class = EffectClassDB.NON_RETRYABLE
        return mock_result

    mock_orchestrator = MagicMock()
    mock_orchestrator.execute_step_async = mock_execute_step_async

    mock_tool_runner = MagicMock()
    mock_policy_engine = MagicMock()

    executor = ExecutorService(
        tool_runner=mock_tool_runner,
        policy_engine=mock_policy_engine,
        execution_orchestrator=mock_orchestrator,
    )

    plan_step = MagicMock(step_id=1, tool_name="write_file", args={})
    policy_result = MagicMock(token="tok")
    context = MagicMock(edition="enterprise", workspace_root="/tmp")

    async def mock_ra(func, *args, **kwargs):
        return MagicMock(id="step-1")

    result = await executor._execute_via_orchestrator(
        task_id="task-1",
        step_id="step-1",
        plan_step=plan_step,
        policy_result=policy_result,
        context=context,
        ra=mock_ra,
    )

    # Must NOT retry — only one call
    assert call_count == 1, (
        f"UNKNOWN_OUTCOME on non-idempotent must not retry, but got {call_count} calls"
    )
    assert result.success is False
    assert "UNKNOWN_OUTCOME" in result.error


@pytest.mark.asyncio
async def test_deterministic_failed_allows_one_retry():
    """Deterministic FAILED (not UNKNOWN) should allow one retry."""
    from packages.executor.executor_service import ExecutorService

    call_count = 0

    async def mock_execute_step_async(**kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.success = False
            mock_result.error = "File not found"
            mock_result.receipt_status = ReceiptStatusDB.FAILED
        else:
            mock_result.success = True
            mock_result.error = None
            mock_result.output = {"ok": True}
            mock_result.receipt_status = ReceiptStatusDB.SUCCEEDED
        mock_result.status = "completed" if mock_result.success else "failed"
        mock_result.output = mock_result.output if mock_result.success else None
        mock_result.artifacts = []
        mock_result.effect_class = EffectClassDB.READ_ONLY
        return mock_result

    mock_orchestrator = MagicMock()
    mock_orchestrator.execute_step_async = mock_execute_step_async

    executor = ExecutorService(
        tool_runner=MagicMock(),
        policy_engine=MagicMock(),
        execution_orchestrator=mock_orchestrator,
    )

    plan_step = MagicMock(step_id=1, tool_name="read_file", args={})
    policy_result = MagicMock(token="tok")
    context = MagicMock(edition="enterprise", workspace_root="/tmp")

    async def mock_ra(func, *args, **kwargs):
        return MagicMock(id="step-1")

    result = await executor._execute_via_orchestrator(
        task_id="task-1",
        step_id="step-1",
        plan_step=plan_step,
        policy_result=policy_result,
        context=context,
        ra=mock_ra,
    )

    # Should retry once
    assert call_count == 2, (
        f"Deterministic FAILED should allow one retry, expected 2 calls, got {call_count}"
    )
    assert result.success is True


@pytest.mark.asyncio
async def test_unknown_outcome_read_only_allows_retry():
    """UNKNOWN_OUTCOME on READ_ONLY effect is safe to retry (no side-effects)."""
    from packages.executor.executor_service import ExecutorService

    call_count = 0

    async def mock_execute_step_async(**kwargs):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        mock_result.success = call_count > 1  # Fail first, succeed on retry
        mock_result.error = "timeout" if call_count == 1 else None
        mock_result.status = "completed" if mock_result.success else "failed"
        mock_result.output = {"data": "ok"} if mock_result.success else None
        mock_result.artifacts = []
        mock_result.receipt_status = (
            ReceiptStatusDB.UNKNOWN if call_count == 1 else ReceiptStatusDB.SUCCEEDED
        )
        mock_result.effect_class = EffectClassDB.READ_ONLY
        return mock_result

    mock_orchestrator = MagicMock()
    mock_orchestrator.execute_step_async = mock_execute_step_async

    executor = ExecutorService(
        tool_runner=MagicMock(),
        policy_engine=MagicMock(),
        execution_orchestrator=mock_orchestrator,
    )

    plan_step = MagicMock(step_id=1, tool_name="search", args={})
    policy_result = MagicMock(token="tok")
    context = MagicMock(edition="enterprise", workspace_root="/tmp")

    async def mock_ra(func, *args, **kwargs):
        return MagicMock(id="step-1")

    result = await executor._execute_via_orchestrator(
        task_id="task-1",
        step_id="step-1",
        plan_step=plan_step,
        policy_result=policy_result,
        context=context,
        ra=mock_ra,
    )

    # READ_ONLY UNKNOWN should retry
    assert call_count == 2
    assert result.success is True


def test_step_execution_result_carries_receipt_status():
    """StepExecutionResult must propagate receipt_status from GatewayResult."""
    from packages.execution.orchestrator import StepExecutionResult

    # Simulate an UNKNOWN outcome result
    result = StepExecutionResult(
        step_id="step-1",
        tool_name="write_file",
        status="failed",
        error="Tool timed out",
        receipt_status=ReceiptStatusDB.UNKNOWN,
        effect_class=EffectClassDB.NON_RETRYABLE,
    )

    assert result.receipt_status == ReceiptStatusDB.UNKNOWN
    assert result.effect_class == EffectClassDB.NON_RETRYABLE
    assert result.success is False
