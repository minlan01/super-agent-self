"""Task Evaluator — post-task assessment, regression detection, and LLM outcome verification."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.db.models import Task, TaskStatus

logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """你是一个任务评估代理。判断以下任务是否真正达成了目标。

## 任务目标
{goal}

## 执行结果
{results_summary}

## 判断标准
- 目标是否完全达成？
- 输出是否与目标一致？
- 是否有明显遗漏？

只返回 JSON:
{{"achieved": true/false, "score": 0.0-1.0, "reason": "简短说明"}}
"""


class TaskEvaluator:
    """Evaluates completed tasks and tracks quality metrics."""

    def __init__(self, provider_router: Any | None = None):
        self.provider_router = provider_router

    def evaluate_task(self, task: Task, steps: list[Any]) -> dict[str, Any]:
        """Evaluate a completed task and return quality metrics."""
        total_steps = len(steps)
        completed_steps = sum(1 for s in steps if s.status.value in ("completed", "approved"))
        failed_steps = sum(1 for s in steps if s.status.value == "failed")

        success_rate = completed_steps / total_steps if total_steps > 0 else 0.0

        # Calculate execution efficiency (planned vs actual steps)
        efficiency = 1.0  # Perfect if all planned steps executed
        skipped = sum(1 for s in steps if s.status.value == "skipped")
        if skipped > 0 and total_steps > 0:
            efficiency = 1.0 - (skipped / total_steps)

        # Risk assessment
        high_risk_steps = sum(1 for s in steps if s.risk_level.value in ("high", "critical"))

        return {
            "task_id": task.id,
            "success": task.status == TaskStatus.COMPLETED,
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "step_success_rate": round(success_rate, 2),
            "efficiency": round(efficiency, 2),
            "high_risk_steps": high_risk_steps,
            "quality_score": round((success_rate * 0.6 + efficiency * 0.4), 2),
        }

    async def evaluate_with_verification(
        self,
        task: Task,
        steps: list[Any],
        db: Session | None = None,
    ) -> dict[str, Any]:
        """Evaluate task with LLM-based outcome verification.

        Falls back to basic evaluation if LLM is unavailable.
        """
        # Start with basic metrics
        metrics = self.evaluate_task(task, steps)

        # Add LLM verification if available
        if self.provider_router is not None and task.status == TaskStatus.COMPLETED:
            try:
                verification = await self._verify_outcome(task, steps)
                metrics["outcome_verification"] = verification
                # Adjust quality score based on LLM verification
                if verification.get("achieved") is False:
                    metrics["quality_score"] = round(
                        metrics["quality_score"] * verification.get("score", 0.5), 2
                    )
            except Exception as exc:
                logger.warning("Outcome verification failed: %s", exc)
                metrics["outcome_verification"] = {
                    "achieved": None, "score": None, "reason": f"Verification failed: {exc}",
                }

        return metrics

    async def _verify_outcome(self, task: Task, steps: list[Any]) -> dict[str, Any]:
        """Use LLM to verify whether the task goal was actually achieved."""
        import json

        from packages.llm_gateway.base import LLMMessage

        # Build results summary from completed steps
        completed_steps = [s for s in steps if s.status.value == "completed"]
        results_summary = "\n".join(
            f"- Step {s.step_order}: {s.tool_name} → {s.result or 'no output'}"
            for s in completed_steps
        ) or "No steps completed."

        prompt = VERIFICATION_PROMPT.format(
            goal=task.goal,
            results_summary=results_summary,
        )

        messages = [
            LLMMessage(role="system", content="你是一个任务评估代理，只返回 JSON。"),
            LLMMessage(role="user", content=prompt),
        ]

        response = await self.provider_router.generate_json(messages)
        content = response.content.strip()

        # Parse JSON
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                result = json.loads(content[start:end + 1])
            else:
                return {"achieved": None, "score": None, "reason": "Could not parse verification"}

        return {
            "achieved": result.get("achieved"),
            "score": result.get("score"),
            "reason": result.get("reason", ""),
        }

    def get_system_metrics(self, db: Session) -> dict[str, Any]:
        """Get overall system quality metrics."""
        total = db.scalar(select(func.count()).select_from(Task))
        completed = db.scalar(
            select(func.count()).select_from(Task).where(Task.status == TaskStatus.COMPLETED)
        )
        failed = db.scalar(
            select(func.count()).select_from(Task).where(Task.status == TaskStatus.FAILED)
        )

        total_count = total or 0
        completed_count = completed or 0
        failed_count = failed or 0

        return {
            "total_tasks": total_count,
            "completed_tasks": completed_count,
            "failed_tasks": failed_count,
            "success_rate": round(completed_count / total_count, 2) if total_count > 0 else 0.0,
        }
