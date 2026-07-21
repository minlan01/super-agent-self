"""Strawberry GraphQL type definitions."""

from datetime import datetime

import strawberry


@strawberry.type
class TaskType:
    id: strawberry.ID
    goal: str
    status: str
    edition: str
    risk_level: str | None
    result: str | None
    error: str | None
    created_at: datetime | None
    updated_at: datetime | None


@strawberry.type
class TaskStepType:
    id: strawberry.ID
    task_id: str
    step_id: str
    tool_name: str
    status: str
    risk_level: str | None
    result: str | None


@strawberry.type
class MemoryType:
    id: strawberry.ID
    title: str
    memory_type: str
    summary: str | None
    importance_score: float | None
    confidence_score: float | None
    enabled: bool
    created_at: datetime | None


@strawberry.type
class SkillType:
    id: strawberry.ID
    name: str
    version: int
    status: str
    success_rate: float | None
    created_at: datetime | None


@strawberry.type
class AuditEventType:
    id: strawberry.ID
    task_id: str | None
    event_type: str
    actor: str | None
    detail: str | None
    created_at: datetime | None


@strawberry.type
class DashboardStats:
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    total_skills: int
    total_memories: int
    success_rate: float


@strawberry.type
class TaskWithSteps:
    task: TaskType
    steps: list["TaskStepType"]
