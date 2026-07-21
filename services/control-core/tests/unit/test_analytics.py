"""Unit tests for analytics endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api_server.routes.analytics import (
    _memories_growth_query,
    _overview_query,
    _recent_activity_query,
    _skills_performance_query,
    _task_status_distribution_query,
    _task_trend_query,
)
from packages.db.models import (
    AuditEvent,
    AuditEventType,
    Base,
    Memory,
    MemoryType,
    Skill,
    SkillStatus,
    Task,
    TaskStatus,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


@pytest.fixture
def db_with_tasks(db):
    """Populate DB with tasks at various times."""
    now = datetime.now(UTC)
    for i in range(5):
        db.add(Task(
            goal=f"task-{i}",
            status=TaskStatus.COMPLETED,
            user_id="u1",
            created_at=now - timedelta(days=i),
        ))
    for i in range(3):
        db.add(Task(
            goal=f"failed-{i}",
            status=TaskStatus.FAILED,
            user_id="u1",
            created_at=now - timedelta(days=i),
        ))
    db.add(Task(goal="pending-0", status=TaskStatus.PENDING, user_id="u1"))
    db.flush()
    return db


@pytest.fixture
def db_with_skills(db):
    """Populate DB with skills at varying success rates."""
    skills_data = [
        ("skill-a", 0.95, 100, SkillStatus.STABLE),
        ("skill-b", 0.80, 50, SkillStatus.STABLE),
        ("skill-c", 0.60, 30, SkillStatus.CANDIDATE),
        ("skill-d", 0.30, 10, SkillStatus.DISABLED),
    ]
    for name, rate, runs, status in skills_data:
        db.add(Skill(
            name=name,
            success_rate=rate,
            total_runs=runs,
            status=status,
            definition={"type": "test"},
        ))
    db.flush()
    return db


@pytest.fixture
def db_with_memories(db):
    """Populate DB with memories across multiple days."""
    now = datetime.now(UTC)
    for i in range(6):
        db.add(Memory(
            title=f"mem-{i}",
            summary="s",
            memory_type=MemoryType.EXECUTION_EXPERIENCE,
            is_active=True,
            user_id="u1",
            created_at=now - timedelta(days=i),
        ))
    db.flush()
    return db


@pytest.fixture
def db_with_audit(db):
    """Populate DB with audit events."""
    now = datetime.now(UTC)
    event_types = [
        AuditEventType.TASK_CREATED,
        AuditEventType.TASK_COMPLETED,
        AuditEventType.STEP_EXECUTING,
        AuditEventType.MEMORY_WRITTEN,
        AuditEventType.SKILL_EXTRACTED,
    ]
    for i, et in enumerate(event_types):
        db.add(AuditEvent(
            event_type=et,
            actor="system",
            task_id=None,
            detail={"index": i},
            created_at=now - timedelta(hours=i),
        ))
    db.flush()
    return db


@pytest.fixture
def db_full(db_with_tasks, db_with_skills, db_with_memories, db_with_audit):
    """DB populated with tasks, skills, memories, and audit events."""
    return db_with_tasks


# ── Overview ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestOverview:
    def test_overview_returns_all_keys(self, db_full):
        result = _overview_query(db_full)
        expected_keys = {"total_tasks", "success_rate", "active_skills", "total_memories", "recent_activity_24h"}
        assert set(result.keys()) == expected_keys

    def test_overview_total_tasks(self, db_full):
        result = _overview_query(db_full)
        # 5 completed + 3 failed + 1 pending = 9
        assert result["total_tasks"] == 9

    def test_overview_success_rate(self, db_full):
        result = _overview_query(db_full)
        # 5 completed / (5 completed + 3 failed) = 62.5%
        assert result["success_rate"] == 62.5

    def test_overview_active_skills(self, db_full):
        result = _overview_query(db_full)
        # 3 skills not disabled (a, b, c)
        assert result["active_skills"] == 3

    def test_overview_empty_db(self, db):
        result = _overview_query(db)
        assert result["total_tasks"] == 0
        assert result["success_rate"] == 0.0
        assert result["active_skills"] == 0
        assert result["total_memories"] == 0
        assert result["recent_activity_24h"] == 0


# ── Task Trend ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTaskTrend:
    def test_trend_returns_days_and_trend(self, db_with_tasks):
        result = _task_trend_query(db_with_tasks, 30)
        assert "days" in result
        assert "trend" in result
        assert result["days"] == 30

    def test_trend_has_date_and_count(self, db_with_tasks):
        result = _task_trend_query(db_with_tasks, 30)
        for item in result["trend"]:
            assert "date" in item
            assert "count" in item
            assert isinstance(item["count"], int)

    def test_trend_respects_days_param(self, db_with_tasks):
        result = _task_trend_query(db_with_tasks, 1)
        # Only tasks from the last 1 day
        for item in result["trend"]:
            assert item["count"] > 0

    def test_trend_empty_db(self, db):
        result = _task_trend_query(db, 30)
        assert result["trend"] == []


# ── Task Status Distribution ─────────────────────────────────────────────


@pytest.mark.unit
class TestTaskStatusDistribution:
    def test_distribution_has_all_statuses(self, db_with_tasks):
        result = _task_status_distribution_query(db_with_tasks)
        for status in TaskStatus:
            assert status.value in result["distribution"]

    def test_distribution_counts_correct(self, db_with_tasks):
        result = _task_status_distribution_query(db_with_tasks)
        assert result["distribution"]["completed"] == 5
        assert result["distribution"]["failed"] == 3
        assert result["distribution"]["pending"] == 1

    def test_distribution_empty_db(self, db):
        result = _task_status_distribution_query(db)
        assert all(v == 0 for v in result["distribution"].values())


# ── Skills Performance ──────────────────────────────────────────────────


@pytest.mark.unit
class TestSkillsPerformance:
    def test_performance_returns_skills_list(self, db_with_skills):
        result = _skills_performance_query(db_with_skills)
        assert "skills" in result
        assert len(result["skills"]) == 4

    def test_performance_sorted_by_success_rate(self, db_with_skills):
        result = _skills_performance_query(db_with_skills)
        rates = [s["success_rate"] for s in result["skills"]]
        assert rates == sorted(rates, reverse=True)

    def test_performance_percentage_format(self, db_with_skills):
        result = _skills_performance_query(db_with_skills)
        for skill in result["skills"]:
            assert 0 <= skill["success_rate"] <= 100
            assert isinstance(skill["success_rate"], float)

    def test_performance_has_expected_keys(self, db_with_skills):
        result = _skills_performance_query(db_with_skills)
        for skill in result["skills"]:
            assert "name" in skill
            assert "success_rate" in skill
            assert "total_runs" in skill
            assert "status" in skill

    def test_performance_empty_db(self, db):
        result = _skills_performance_query(db)
        assert result["skills"] == []


# ── Memory Growth ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestMemoryGrowth:
    def test_growth_returns_days_and_growth(self, db_with_memories):
        result = _memories_growth_query(db_with_memories, 30)
        assert "days" in result
        assert "growth" in result
        assert result["days"] == 30

    def test_growth_has_expected_keys(self, db_with_memories):
        result = _memories_growth_query(db_with_memories, 30)
        for item in result["growth"]:
            assert "date" in item
            assert "count" in item
            assert "cumulative" in item

    def test_growth_cumulative_is_increasing(self, db_with_memories):
        result = _memories_growth_query(db_with_memories, 30)
        if len(result["growth"]) > 1:
            for i in range(1, len(result["growth"])):
                assert result["growth"][i]["cumulative"] >= result["growth"][i - 1]["cumulative"]

    def test_growth_empty_db(self, db):
        result = _memories_growth_query(db, 30)
        assert result["growth"] == []


# ── Recent Activity ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestRecentActivity:
    def test_activity_returns_events(self, db_with_audit):
        result = _recent_activity_query(db_with_audit, 50)
        assert "events" in result
        assert "total" in result
        assert result["total"] == 5

    def test_activity_events_have_expected_keys(self, db_with_audit):
        result = _recent_activity_query(db_with_audit, 50)
        for event in result["events"]:
            assert "id" in event
            assert "event_type" in event
            assert "actor" in event
            assert "created_at" in event

    def test_activity_respects_limit(self, db_with_audit):
        result = _recent_activity_query(db_with_audit, 2)
        assert result["total"] == 2

    def test_activity_ordered_by_created_at_desc(self, db_with_audit):
        result = _recent_activity_query(db_with_audit, 50)
        dates = [e["created_at"] for e in result["events"] if e["created_at"]]
        assert dates == sorted(dates, reverse=True)

    def test_activity_empty_db(self, db):
        result = _recent_activity_query(db, 50)
        assert result["events"] == []
        assert result["total"] == 0
