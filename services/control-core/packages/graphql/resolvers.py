"""Data fetchers for GraphQL resolvers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import strawberry
from sqlalchemy import func, select

from packages.db.models import (
    AuditEvent,
    Memory,
    Skill,
    Task,
    TaskStatus,
    TaskStep,
)
from packages.db.session import SessionLocal
from packages.graphql.types import (
    AuditEventType,
    DashboardStats,
    MemoryType,
    SkillType,
    TaskStepType,
    TaskType,
    TaskWithSteps,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# ── Converters ──────────────────────────────────────────────────────────────


def _to_task_type(t: Task) -> TaskType:
    return TaskType(
        id=strawberry.ID(str(t.id)),
        goal=t.goal,
        status=t.status.value if hasattr(t.status, "value") else str(t.status),
        edition=t.edition.value if hasattr(t.edition, "value") else str(t.edition),
        risk_level=t.risk_level.value if hasattr(t.risk_level, "value") else t.risk_level,
        result=t.result,
        error=t.error,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _to_step_type(s: TaskStep) -> TaskStepType:
    return TaskStepType(
        id=strawberry.ID(str(s.id)),
        task_id=s.task_id,
        step_id=str(s.step_order),
        tool_name=s.tool_name,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        risk_level=s.risk_level.value if hasattr(s.risk_level, "value") else s.risk_level,
        result=s.result,
    )


def _to_memory_type(m: Memory) -> MemoryType:
    return MemoryType(
        id=strawberry.ID(str(m.id)),
        title=m.title,
        memory_type=m.memory_type.value if hasattr(m.memory_type, "value") else str(m.memory_type),
        summary=m.summary,
        importance_score=m.importance_score,
        confidence_score=m.confidence_score,
        enabled=m.is_active,
        created_at=m.created_at,
    )


def _to_skill_type(s: Skill) -> SkillType:
    return SkillType(
        id=strawberry.ID(str(s.id)),
        name=s.name,
        version=s.version,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        success_rate=s.success_rate,
        created_at=s.created_at,
    )


def _to_audit_event_type(a: AuditEvent) -> AuditEventType:
    detail_str: str | None = None
    if a.detail is not None:
        if isinstance(a.detail, dict):
            detail_str = json.dumps(a.detail)
        else:
            detail_str = str(a.detail)
    return AuditEventType(
        id=strawberry.ID(str(a.id)),
        task_id=a.task_id,
        event_type=a.event_type.value if hasattr(a.event_type, "value") else str(a.event_type),
        actor=a.actor,
        detail=detail_str,
        created_at=a.created_at,
    )


# ── Resolver functions ──────────────────────────────────────────────────────


def get_tasks(
    limit: int = 20, offset: int = 0, status: str | None = None, *, db: Session | None = None,
) -> list[TaskType]:
    limit = min(limit, 200)
    offset = max(0, min(offset, 10000))
    _db = db or SessionLocal()
    try:
        query = select(Task).order_by(Task.created_at.desc()).offset(offset).limit(limit)
        if status:
            try:
                status_enum = TaskStatus(status)
            except ValueError:
                raise ValueError(f"Invalid task status filter: '{status}'. Valid values: {[s.value for s in TaskStatus]}")
            query = query.where(Task.status == status_enum)
        tasks = list(_db.scalars(query).all())
        return [_to_task_type(t) for t in tasks]
    finally:
        if db is None:
            _db.close()


def get_task(task_id: str, *, db: Session | None = None) -> TaskType | None:
    _db = db or SessionLocal()
    try:
        t = _db.get(Task, task_id)
        return _to_task_type(t) if t else None
    finally:
        if db is None:
            _db.close()


def get_task_with_steps(task_id: str, *, db: Session | None = None) -> TaskWithSteps | None:
    _db = db or SessionLocal()
    try:
        t = _db.get(Task, task_id)
        if not t:
            return None
        steps = list(_db.scalars(
            select(TaskStep).where(TaskStep.task_id == task_id).order_by(TaskStep.step_order)
        ).all())
        return TaskWithSteps(task=_to_task_type(t), steps=[_to_step_type(s) for s in steps])
    finally:
        if db is None:
            _db.close()


def get_memories(
    limit: int = 20, offset: int = 0, memory_type: str | None = None, *, db: Session | None = None,
) -> list[MemoryType]:
    limit = min(limit, 200)
    offset = max(0, min(offset, 10000))
    _db = db or SessionLocal()
    try:
        query = select(Memory).order_by(Memory.created_at.desc()).offset(offset).limit(limit)
        if memory_type:
            from packages.db.models import MemoryType as MemoryTypeEnum
            try:
                mt_enum = MemoryTypeEnum(memory_type)
            except ValueError:
                raise ValueError(f"Invalid memory_type filter: '{memory_type}'")
            query = query.where(Memory.memory_type == mt_enum)
        memories = list(_db.scalars(query).all())
        return [_to_memory_type(m) for m in memories]
    finally:
        if db is None:
            _db.close()


def get_skills(
    limit: int = 20, offset: int = 0, status: str | None = None, *, db: Session | None = None,
) -> list[SkillType]:
    limit = min(limit, 200)
    offset = max(0, min(offset, 10000))
    _db = db or SessionLocal()
    try:
        query = select(Skill).order_by(Skill.created_at.desc()).offset(offset).limit(limit)
        if status:
            from packages.db.models import SkillStatus
            try:
                status_enum = SkillStatus(status)
            except ValueError:
                raise ValueError(f"Invalid skill status filter: '{status}'")
            query = query.where(Skill.status == status_enum)
        skills = list(_db.scalars(query).all())
        return [_to_skill_type(s) for s in skills]
    finally:
        if db is None:
            _db.close()


def get_audit_events(
    limit: int = 20, offset: int = 0, task_id: str | None = None, *, db: Session | None = None,
) -> list[AuditEventType]:
    limit = min(limit, 200)
    offset = max(0, min(offset, 10000))
    _db = db or SessionLocal()
    try:
        query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)
        if task_id:
            query = query.where(AuditEvent.task_id == task_id)
        events = list(_db.scalars(query).all())
        return [_to_audit_event_type(a) for a in events]
    finally:
        if db is None:
            _db.close()


def get_dashboard_stats(*, db: Session | None = None) -> DashboardStats:
    _db = db or SessionLocal()
    try:
        task_stats = _db.execute(
            select(
                func.count(Task.id).label("total"),
                func.count(Task.id).filter(Task.status == TaskStatus.COMPLETED).label("completed"),
                func.count(Task.id).filter(Task.status == TaskStatus.FAILED).label("failed"),
            )
        ).one()
        total_skills = _db.scalar(select(func.count(Skill.id))) or 0
        total_memories = _db.scalar(select(func.count(Memory.id))) or 0
        total = task_stats.total or 0
        success_rate = (task_stats.completed / total * 100) if total > 0 else 0.0
        return DashboardStats(
            total_tasks=total,
            completed_tasks=task_stats.completed or 0,
            failed_tasks=task_stats.failed or 0,
            total_skills=total_skills,
            total_memories=total_memories,
            success_rate=round(success_rate, 1),
        )
    finally:
        if db is None:
            _db.close()
