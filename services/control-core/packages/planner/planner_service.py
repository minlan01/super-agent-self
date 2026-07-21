"""Planner service — orchestrates LLM planning with validation and retry."""

from __future__ import annotations

import json
from typing import Any

import structlog

from packages.llm_gateway.base import LLMMessage
from packages.llm_gateway.provider_router import ProviderRouter
from packages.planner.plan_validator import Plan, PlanValidator
from packages.planner.prompt_templates import build_planning_prompt

logger = structlog.get_logger()

# Rough estimate: 1 token ≈ 4 chars for mixed CJK/English
CHARS_PER_TOKEN = 4
# Context length used for compression trigger (tokens)
DEFAULT_CONTEXT_LENGTH = 8192
_MAX_RETRY_MESSAGES = 6


class PlannerService:
    """Generates, validates, and retries plans via the LLM gateway."""

    def __init__(
        self,
        provider_router: ProviderRouter,
        tool_registry: Any,
        max_retries: int = 2,
        context_compressor: Any | None = None,
    ):
        self.provider_router = provider_router
        self.tool_registry = tool_registry
        self.validator = PlanValidator(tool_registry)
        self.max_retries = max_retries
        self.context_compressor = context_compressor

    async def plan(
        self,
        goal: str,
        edition: str = "enterprise",
        memories: list[dict[str, Any]] | None = None,
        skills: list[dict[str, Any]] | None = None,
    ) -> Plan:
        """Generate and validate a plan for the given goal.

        Retries up to max_retries times if parsing or validation fails,
        sending the error message back to the LLM for correction.

        Args:
            goal: The task goal description.
            edition: "enterprise" or "personal".
            memories: Optional past experiences to inject into the prompt.
            skills: Optional approved skills to inject into the prompt.

        Returns:
            A validated Plan object.

        Raises:
            RuntimeError: If all retry attempts fail.
        """
        tools_summary = self.tool_registry.get_tools_summary(edition=edition)
        messages = list(build_planning_prompt(goal, tools_summary, edition, memories, skills))

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                messages = await self._maybe_compress(messages)

                response = await self.provider_router.generate_json(messages)
                plan_dict = self._parse_json(response.content)
                plan = self.validator.validate(plan_dict)
                logger.info(
                    "Plan generated: %d steps for goal: %s",
                    len(plan.steps),
                    goal[:50],
                )
                return plan
            except Exception as e:
                last_error = e
                logger.warning(
                    "Plan attempt %d failed: %s", attempt + 1, str(e)
                )
                messages.append(
                    LLMMessage(role="assistant", content="{}")
                )
                messages.append(
                    LLMMessage(
                        role="user",
                        content=f"The previous plan was invalid: {str(e)}. Please fix and return valid JSON.",
                    )
                )
                if len(messages) > _MAX_RETRY_MESSAGES:
                    messages = messages[-_MAX_RETRY_MESSAGES:]

        raise RuntimeError(
            f"Failed to generate valid plan after {self.max_retries + 1} attempts: {last_error}"
        )

    async def _maybe_compress(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        """Trigger context compression if message list exceeds threshold."""
        if self.context_compressor is None:
            return messages

        total_chars = sum(len(m.content) for m in messages)
        token_estimate = total_chars // CHARS_PER_TOKEN

        if self.context_compressor.should_compress(token_estimate, DEFAULT_CONTEXT_LENGTH):
            logger.info(
                "Context compression triggered: ~%d tokens estimated, compressing",
                token_estimate,
            )
            return await self.context_compressor.compress(messages, DEFAULT_CONTEXT_LENGTH)
        return messages

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        """Extract JSON from LLM response content.

        Handles markdown code fences that some providers wrap around JSON.
        """
        content = content.strip()
        # Remove markdown code blocks if present
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            content = "\n".join(lines)
        return json.loads(content)
