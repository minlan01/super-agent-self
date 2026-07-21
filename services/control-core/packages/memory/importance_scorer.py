"""Importance Scorer — scores memory importance for retrieval ranking."""

from __future__ import annotations

import logging

from packages.db.models import MemoryType

logger = logging.getLogger(__name__)

# Base importance by memory type
_TYPE_WEIGHTS: dict[MemoryType, float] = {
    MemoryType.ERROR_SOLUTION: 0.9,
    MemoryType.WORKFLOW_PATTERN: 0.8,
    MemoryType.DOMAIN_KNOWLEDGE: 0.7,
    MemoryType.EXECUTION_EXPERIENCE: 0.6,
    MemoryType.USER_PREFERENCE: 0.75,
    MemoryType.PERSONAL_PROJECT: 0.7,
    MemoryType.FILE_KNOWLEDGE: 0.5,
    MemoryType.REMINDER: 0.6,
    MemoryType.DAILY_CONTEXT: 0.4,
}


class ImportanceScorer:
    """Scores and adjusts memory importance based on context."""

    def score(
        self,
        memory_type: MemoryType,
        base_importance: float = 0.5,
        success: bool = True,
        step_count: int = 0,
        is_unique: bool = True,
    ) -> float:
        """Calculate final importance score.

        Args:
            memory_type: Type of memory.
            base_importance: Initial importance from summarizer.
            success: Whether the source task succeeded.
            step_count: Number of steps in the source task.
            is_unique: Whether the content is unique (not a duplicate).

        Returns:
            Final importance score clamped to [0.0, 1.0].
        """
        type_weight = _TYPE_WEIGHTS.get(memory_type, 0.5)

        # Start with weighted average of base and type weight
        score = 0.4 * base_importance + 0.6 * type_weight

        # Boost for failures (important to remember what went wrong)
        if not success:
            score = min(1.0, score + 0.15)

        # Boost for complex tasks (more steps = more valuable experience)
        if step_count > 5:
            score = min(1.0, score + 0.1)
        elif step_count > 3:
            score = min(1.0, score + 0.05)

        # Penalize duplicates
        if not is_unique:
            score = max(0.0, score - 0.3)

        return round(max(0.0, min(1.0, score)), 2)

    def should_retrieve(
        self,
        importance_score: float,
        confidence_score: float,
        min_importance: float = 0.3,
        min_confidence: float = 0.5,
    ) -> bool:
        """Determine if a memory should be included in retrieval results."""
        return importance_score >= min_importance and confidence_score >= min_confidence
