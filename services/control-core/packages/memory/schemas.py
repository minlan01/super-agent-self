"""Memory schemas — service-layer schemas for memory operations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from packages.db.models import MemoryType


class MemoryWriteRequest(BaseModel):
    """Request to write a memory from task completion."""

    # None for non-task origins (preferences, reminders) — avoids FK
    # violations against tasks.source_task_id.
    task_id: str | None = None
    goal: str
    steps_summary: list[dict[str, Any]] = Field(default_factory=list)
    success: bool = True
    memory_type: MemoryType = MemoryType.EXECUTION_EXPERIENCE


class MemorySummary(BaseModel):
    """Result of memory summarization."""

    title: str = Field(..., min_length=1, max_length=500)
    summary: str = Field(..., min_length=1)
    importance_score: float = Field(0.5, ge=0.0, le=1.0)
    confidence_score: float = Field(0.5, ge=0.0, le=1.0)


class MemoryRetrievalResult(BaseModel):
    """Result of memory retrieval for planner injection."""

    memories: list[dict[str, Any]] = Field(default_factory=list)
    total_count: int = 0
    token_estimate: int = 0
    truncated: bool = False
