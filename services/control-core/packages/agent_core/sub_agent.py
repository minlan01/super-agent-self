"""Sub-Agent tool — delegates a subtask to a child agent."""

from __future__ import annotations

import logging
from typing import Any

from packages.executor.tools.base import ExecutionContext, ToolBase, ToolResult
from packages.policy.unified_registry import tool_registry

logger = logging.getLogger(__name__)

_runner_instance: Any = None


def set_sub_agent_runner(runner: Any) -> None:
    global _runner_instance
    _runner_instance = runner


_MAX_SUB_AGENT_DEPTH = 3


@tool_registry.register(
    category="agent",
    risk_level="medium",
    emoji="🤖",
    params_schema={
        "type": "object",
        "required": ["goal"],
        "properties": {
            "goal": {"type": "string", "description": "Goal for the sub-agent"},
            "edition": {"type": "string", "description": "Edition context", "default": "enterprise"},
        },
        "additionalProperties": False,
    },
)
class DelegateTask(ToolBase):
    """Delegate a subtask to a child agent."""

    name = "delegate.task"
    description = "Delegate a subtask to a child agent with isolated context"

    def __init__(self, sub_agent_runner: Any = None):
        self._runner = sub_agent_runner

    def _resolve_runner(self) -> Any:
        if self._runner is not None:
            return self._runner
        return _runner_instance

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        goal: str = args.get("goal", "").strip()
        if not goal:
            return ToolResult(success=False, error="goal is required")

        runner = self._resolve_runner()
        if runner is None:
            return ToolResult(success=False, error="Sub-agent runner not configured")

        depth = int(args.get("depth", 0))
        if depth >= _MAX_SUB_AGENT_DEPTH:
            return ToolResult(success=False, error=f"Maximum sub-agent depth ({_MAX_SUB_AGENT_DEPTH}) exceeded")
        result = await runner.run(goal, context, depth=depth + 1)

        if result.get("success"):
            return ToolResult(
                success=True,
                output=result,
            )
        else:
            return ToolResult(
                success=False,
                error=result.get("error", "Sub-agent failed"),
                output=result,
            )
