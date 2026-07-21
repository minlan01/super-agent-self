"""Memory Summarizer — creates memory summaries from task results."""

from __future__ import annotations

import logging
from typing import Any

from packages.memory.schemas import MemorySummary, MemoryWriteRequest

logger = logging.getLogger(__name__)


class MemorySummarizer:
    """Creates concise memory summaries from task execution results."""

    def __init__(self, provider_router: Any | None = None):
        self.provider_router = provider_router

    async def summarize(self, request: MemoryWriteRequest) -> MemorySummary:
        """Generate a memory summary from task results.

        Uses LLM if provider_router is available and configured,
        otherwise falls back to rule-based summarization.
        """
        if self.provider_router is not None:
            try:
                return await self._llm_summarize(request)
            except Exception as e:
                logger.warning("LLM summarization failed, falling back to rule-based: %s", e)

        return self._rule_based_summarize(request)

    async def _llm_summarize(self, request: MemoryWriteRequest) -> MemorySummary:
        """Use LLM to generate a summary."""
        from packages.llm_gateway.base import LLMMessage

        steps_text = "\n".join(
            f"  Step {s.get('step_id', '?')}: {s.get('tool_name', '?')} → {s.get('status', '?')}"
            for s in request.steps_summary
        )

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a memory summarizer. Given a completed task, "
                    "produce a concise memory summary as JSON with keys: "
                    "title (max 200 chars), summary (max 500 chars), "
                    "importance_score (0.0-1.0), confidence_score (0.0-1.0)."
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"Task goal: {request.goal}\n"
                    f"Success: {request.success}\n"
                    f"Steps:\n{steps_text}"
                ),
            ),
        ]

        import json
        response = await self.provider_router.generate_json(messages)
        data = json.loads(response.content)
        return MemorySummary(
            title=data.get("title", request.goal[:200]),
            summary=data.get("summary", request.goal[:500]),
            importance_score=data.get("importance_score", 0.5),
            confidence_score=data.get("confidence_score", 0.5),
        )

    def _rule_based_summarize(self, request: MemoryWriteRequest) -> MemorySummary:
        """Rule-based fallback summarization."""

        # Build title from goal
        title = request.goal[:200] if len(request.goal) > 200 else request.goal

        # Build summary from steps
        tool_names = [s.get("tool_name", "?") for s in request.steps_summary]
        tools_str = " → ".join(tool_names) if tool_names else "no steps"

        success_str = "succeeded" if request.success else "failed"
        summary = (
            f"Task {success_str}: {request.goal[:200]}. "
            f"Tools used: {tools_str}. "
            f"Steps: {len(request.steps_summary)}."
        )
        if len(summary) > 500:
            summary = summary[:497] + "..."

        # Score based on success and complexity
        importance = 0.7 if request.success else 0.8  # failures are important to remember
        confidence = 0.9 if request.success else 0.7

        return MemorySummary(
            title=title,
            summary=summary,
            importance_score=importance,
            confidence_score=confidence,
        )
