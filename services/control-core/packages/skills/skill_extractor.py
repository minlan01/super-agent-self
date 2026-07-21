"""Skill Extractor — extracts reusable skill templates from completed tasks."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from packages.skills.schemas import SkillDefinition, SkillExtractionResult

logger = logging.getLogger(__name__)


class SkillExtractor:
    """Extracts skill templates from successfully completed task steps."""

    def extract(
        self,
        goal: str,
        steps: list[dict[str, Any]],
        success: bool,
        min_steps: int = 2,
    ) -> SkillExtractionResult:
        """Try to extract a skill from completed task steps.

        A skill is extracted when:
        - Task was successful
        - At least min_steps steps were executed
        - Steps form a coherent workflow

        Args:
            goal: The task goal.
            steps: List of step dicts with tool_name, args, status.
            success: Whether the task succeeded.
            min_steps: Minimum steps required for a skill.

        Returns:
            SkillExtractionResult with extracted flag and skill definition.
        """
        if not success:
            return SkillExtractionResult(
                extracted=False,
                reason="Cannot extract skill from failed task",
            )

        completed_steps = [s for s in steps if s.get("status") in ("completed", "approved")]
        if len(completed_steps) < min_steps:
            return SkillExtractionResult(
                extracted=False,
                reason=f"Need at least {min_steps} completed steps, got {len(completed_steps)}",
            )

        # Generate name from goal
        name = self._generate_name(goal)

        # Build step template
        steps_template = []
        for i, step in enumerate(completed_steps):
            steps_template.append({
                "step_id": i + 1,
                "tool_name": step.get("tool_name", ""),
                "args_template": self._generalize_args(step.get("args", {})),
            })

        # Extract tags from tool names
        tags = list({s.get("tool_name", "").split(".")[0] for s in completed_steps})

        skill = SkillDefinition(
            name=name,
            description=f"Auto-extracted skill from task: {goal[:200]}",
            steps_template=steps_template,
            tags=tags,
        )

        logger.info("Extracted skill '%s' with %d steps", name, len(steps_template))
        return SkillExtractionResult(extracted=True, skill=skill)

    @staticmethod
    def _generate_name(goal: str) -> str:
        """Generate a skill name from the task goal."""
        # Take first meaningful words
        words = goal.lower().replace(".", " ").replace(",", " ").split()
        stop = {"the", "a", "an", "and", "or", "to", "from", "for", "with", "in", "on", "of"}
        meaningful = [w for w in words if w not in stop and len(w) > 2][:5]
        name = "_".join(meaningful)
        if not name:
            name = f"skill_{hashlib.sha256(goal.encode()).hexdigest()[:8]}"
        return name[:200]

    @staticmethod
    def _generalize_args(args: dict[str, Any]) -> dict[str, Any]:
        """Generalize specific args into a template.

        Replaces specific values with placeholder descriptions.
        """
        template = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                template[key] = "{{url}}"
            elif isinstance(value, str) and len(value) > 50:
                template[key] = f"{{{{{key}}}}}"
            else:
                template[key] = value
        return template
