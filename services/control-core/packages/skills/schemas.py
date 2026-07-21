"""Skill schemas — service-layer schemas for skill operations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillDefinition(BaseModel):
    """Structured skill definition extracted from task steps."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    steps_template: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class SkillExtractionResult(BaseModel):
    """Result of skill extraction from a completed task."""

    extracted: bool
    skill: SkillDefinition | None = None
    reason: str = ""


class SkillReuseCheck(BaseModel):
    """Check if a skill can be reused for a given goal."""

    skill_id: str
    goal: str
    match_confidence: float = Field(0.0, ge=0.0, le=1.0)


class SkillDegradationCheck(BaseModel):
    """Result of skill degradation check."""

    skill_id: str
    should_degrade: bool
    reason: str = ""
    current_success_rate: float = 0.0
    consecutive_failures: int = 0
