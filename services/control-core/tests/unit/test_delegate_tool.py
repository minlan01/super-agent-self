"""Tests for sub-agent delegation — DelegateTask tool and SubAgentRunner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.agent_core.sub_agent import DelegateTask
from packages.executor.tools.base import ExecutionContext


def _make_context():
    return ExecutionContext(
        task_id="parent-1",
        step_id="step-0",
        edition="enterprise",
    )


@pytest.mark.unit
class TestDelegateTask:
    @pytest.mark.asyncio
    async def test_delegate_success(self):
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value={
            "success": True,
            "sub_agent_id": "abc123",
            "depth": 0,
            "goal": "search for X",
            "results": [{"step": 1, "status": "delegated"}],
        })

        tool = DelegateTask(sub_agent_runner=mock_runner)
        ctx = _make_context()
        result = await tool.execute({"goal": "search for X"}, ctx)

        assert result.success
        assert result.output["sub_agent_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_delegate_no_goal(self):
        tool = DelegateTask()
        ctx = _make_context()
        result = await tool.execute({"goal": ""}, ctx)

        assert not result.success
        assert "goal" in result.error

    @pytest.mark.asyncio
    async def test_delegate_no_runner(self):
        tool = DelegateTask(sub_agent_runner=None)
        ctx = _make_context()
        result = await tool.execute({"goal": "do something"}, ctx)

        assert not result.success
        assert "not configured" in result.error

    @pytest.mark.asyncio
    async def test_delegate_sub_agent_failure(self):
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value={
            "success": False,
            "error": "Sub-agent failed",
            "depth": 0,
        })

        tool = DelegateTask(sub_agent_runner=mock_runner)
        ctx = _make_context()
        result = await tool.execute({"goal": "fail task"}, ctx)

        assert not result.success
        assert "Sub-agent failed" in result.error

    @pytest.mark.asyncio
    async def test_delegate_with_custom_depth(self):
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value={
            "success": True,
            "depth": 1,
            "results": [],
        })

        tool = DelegateTask(sub_agent_runner=mock_runner)
        ctx = _make_context()
        result = await tool.execute({"goal": "sub task", "depth": 1}, ctx)

        assert result.success
        mock_runner.run.assert_called_once_with("sub task", ctx, depth=2)
