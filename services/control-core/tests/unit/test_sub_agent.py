"""Tests for Sub-Agent runner and DelegateTask tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.agent_core.sub_agent import DelegateTask
from packages.executor.tools.base import ExecutionContext
from packages.executor.tools.delegate_tool import SubAgentRunner


@pytest.fixture
def context(tmp_path):
    return ExecutionContext(
        task_id="t1",
        step_id="s1",
        edition="enterprise",
        workspace_root=str(tmp_path),
    )


def _make_mock_tool_result(success=True, output=None, error=None):
    """Create a mock ToolResult."""
    result = MagicMock()
    result.success = success
    result.output = output
    result.error = error
    return result


def _make_mock_tool_cls(tool_result=None):
    """Create a mock tool class that returns the given result on execute."""
    if tool_result is None:
        tool_result = _make_mock_tool_result(success=True, output={"data": "ok"})
    instance = MagicMock()
    instance.execute = AsyncMock(return_value=tool_result)
    return instance


def _make_mock_planner(steps=None):
    """Create a mock planner that returns a plan with given steps."""
    planner = MagicMock()

    # Default steps if none provided
    if steps is None:
        steps = [{"step_id": 1, "tool_name": "file.read", "args": {"path": "test.txt"}}]

    mock_plan = MagicMock()
    mock_plan.steps = []
    for s in steps:
        step = MagicMock()
        step.step_id = s["step_id"]
        step.tool_name = s["tool_name"]
        step.args = s.get("args", {})
        mock_plan.steps.append(step)

    planner.plan = AsyncMock(return_value=mock_plan)
    return planner


def _make_mock_executor():
    executor = MagicMock()
    return executor


# ── SubAgentRunner ──────────────────────────────────────────────────────────


class TestSubAgentRunner:
    @pytest.mark.asyncio
    async def test_run_simple(self, context):
        planner = _make_mock_planner()
        executor = _make_mock_executor()
        runner = SubAgentRunner(planner, executor)

        mock_tool_instance = _make_mock_tool_cls()
        with patch("packages.policy.unified_registry.tool_registry") as mock_registry:
            mock_registry.get_tool_instance.return_value = mock_tool_instance
            result = await runner.run("Read a file", context)
        assert result["success"]
        assert "sub_agent_id" in result

    @pytest.mark.asyncio
    async def test_run_depth_limit(self, context):
        planner = _make_mock_planner()
        executor = _make_mock_executor()
        runner = SubAgentRunner(planner, executor, max_depth=2)

        result = await runner.run("Read a file", context, depth=2)
        assert not result["success"]
        assert "depth" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_run_blocks_dangerous_tools(self, context):
        planner = _make_mock_planner(steps=[
            {"step_id": 1, "tool_name": "delegate.task", "args": {"goal": "nested"}},
        ])
        executor = _make_mock_executor()
        runner = SubAgentRunner(planner, executor)

        result = await runner.run("Delegate nested task", context)
        assert not result["success"]

    @pytest.mark.asyncio
    async def test_run_handles_planner_error(self, context):
        planner = MagicMock()
        planner.plan = AsyncMock(side_effect=RuntimeError("LLM error"))
        executor = _make_mock_executor()
        runner = SubAgentRunner(planner, executor)

        result = await runner.run("Broken task", context)
        assert not result["success"]
        assert "LLM error" in result["error"]

    @pytest.mark.asyncio
    async def test_run_parallel(self, context):
        planner = _make_mock_planner()
        executor = _make_mock_executor()
        runner = SubAgentRunner(planner, executor, max_concurrent=3)

        mock_tool_instance = _make_mock_tool_cls()
        with patch("packages.policy.unified_registry.tool_registry") as mock_registry:
            mock_registry.get_tool_instance.return_value = mock_tool_instance
            goals = ["Task 1", "Task 2", "Task 3"]
            results = await runner.run_parallel(goals, context)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_concurrent_limit(self, context):
        planner = _make_mock_planner()
        executor = _make_mock_executor()
        runner = SubAgentRunner(planner, executor, max_concurrent=1)
        runner._active_count = 1  # Simulate one active

        result = await runner.run("Should be rejected", context)
        assert not result["success"]
        assert "concurrent" in result["error"].lower()


# ── DelegateTask tool ──────────────────────────────────────────────────────


class TestDelegateTask:
    @pytest.mark.asyncio
    async def test_no_goal(self, context):
        tool = DelegateTask()
        result = await tool.execute({}, context)
        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_runner(self, context):
        tool = DelegateTask()
        result = await tool.execute({"goal": "test"}, context)
        assert not result.success
        assert "not configured" in result.error.lower()

    @pytest.mark.asyncio
    async def test_successful_delegation(self, context):
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value={
            "success": True,
            "sub_agent_id": "abc",
            "results": [],
        })
        tool = DelegateTask(sub_agent_runner=mock_runner)
        result = await tool.execute({"goal": "read files"}, context)
        assert result.success
        assert result.output["sub_agent_id"] == "abc"

    @pytest.mark.asyncio
    async def test_failed_delegation(self, context):
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value={
            "success": False,
            "error": "Sub-agent failed: LLM error",
        })
        tool = DelegateTask(sub_agent_runner=mock_runner)
        result = await tool.execute({"goal": "read files"}, context)
        assert not result.success
        assert "Sub-agent failed" in result.error
