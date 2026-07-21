"""Sub-Agent Runner — runs child agents with isolated context and limited depth."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

MAX_DEPTH = 2
MAX_CONCURRENT = 3
BLOCKED_TOOLS = {"delegate.task", "memory.write"}


class SubAgentRunner:
    """Run sub-agents with isolated context, limited recursion depth."""

    def __init__(
        self,
        planner: Any,
        executor: Any,
        max_depth: int = MAX_DEPTH,
        max_concurrent: int = MAX_CONCURRENT,
    ):
        self.planner = planner
        self.executor = executor
        self.max_depth = max_depth
        self.max_concurrent = max_concurrent
        self._active_count = 0
        self._count_lock = asyncio.Lock()

    async def run(self, goal: str, parent_context: Any, depth: int = 0) -> dict[str, Any]:
        """Create an isolated agent instance and run a subtask.

        Args:
            goal: The subtask goal.
            parent_context: The parent's ExecutionContext.
            depth: Current recursion depth.

        Returns:
            dict with success, output, and metadata.
        """
        if depth >= self.max_depth:
            return {
                "success": False,
                "error": f"Maximum sub-agent depth ({self.max_depth}) reached",
                "depth": depth,
            }

        async with self._count_lock:
            if self._active_count >= self.max_concurrent:
                return {
                    "success": False,
                    "error": f"Maximum concurrent sub-agents ({self.max_concurrent}) reached",
                    "depth": depth,
                }
            self._active_count += 1
        sub_id = str(uuid.uuid4())[:8]

        try:
            logger.info("Sub-agent [%s] started (depth=%d): %s", sub_id, depth, goal[:50])

            # Generate plan for subtask
            plan = await self.planner.plan(goal=goal, edition=parent_context.edition)

            # Create isolated context
            from packages.executor.tools.base import ExecutionContext
            sub_context = ExecutionContext(
                task_id=f"sub-{sub_id}",
                step_id=f"sub-{sub_id}-0",
                edition=parent_context.edition,
                workspace_root=parent_context.workspace_root,
                screenshots_dir=parent_context.screenshots_dir,
                outputs_dir=parent_context.outputs_dir,
            )

            # Execute plan steps through the tool registry
            results = []
            from packages.policy.unified_registry import tool_registry

            for plan_step in plan.steps:
                if plan_step.tool_name in BLOCKED_TOOLS:
                    results.append({
                        "step": plan_step.step_id,
                        "tool": plan_step.tool_name,
                        "status": "blocked",
                        "reason": "Tool not allowed in sub-agent",
                    })
                    continue

                try:
                    tool_instance = tool_registry.get_tool_instance(plan_step.tool_name)
                    if tool_instance is None:
                        results.append({
                            "step": plan_step.step_id,
                            "tool": plan_step.tool_name,
                            "status": "not_found",
                            "error": f"Tool '{plan_step.tool_name}' not registered",
                        })
                        continue

                    step_result = await tool_instance.execute(plan_step.args, sub_context)
                    results.append({
                        "step": plan_step.step_id,
                        "tool": plan_step.tool_name,
                        "status": "success" if step_result.success else "failed",
                        "output": step_result.output if step_result.success else None,
                        "error": step_result.error if not step_result.success else None,
                    })
                except Exception as e:
                    results.append({
                        "step": plan_step.step_id,
                        "tool": plan_step.tool_name,
                        "status": "error",
                        "error": str(e),
                    })

            success = all(r.get("status") in ("success", "delegated") for r in results)

            logger.info("Sub-agent [%s] completed: %s", sub_id, "ok" if success else "blocked")
            return {
                "success": success,
                "sub_agent_id": sub_id,
                "depth": depth,
                "goal": goal,
                "results": results,
            }
        except Exception as exc:
            logger.exception("Sub-agent [%s] failed: %s", sub_id, exc)
            return {
                "success": False,
                "error": str(exc),
                "sub_agent_id": sub_id,
                "depth": depth,
            }
        finally:
            async with self._count_lock:
                self._active_count -= 1

    async def run_parallel(self, goals: list[str], parent_context: Any, depth: int = 0) -> list[dict[str, Any]]:
        """Run multiple sub-agents in parallel (up to max_concurrent)."""
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _limited_run(goal: str) -> dict[str, Any]:
            async with semaphore:
                return await self.run(goal, parent_context, depth)

        tasks = [_limited_run(g) for g in goals]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Convert unexpected exceptions (from return_exceptions=True) into error dicts
        processed: list[dict[str, Any]] = []
        for r in results:
            if isinstance(r, Exception):
                processed.append({"success": False, "error": f"Unexpected error: {r}"})
            else:
                processed.append(r)
        return processed
