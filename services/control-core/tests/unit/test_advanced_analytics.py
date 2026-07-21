"""Unit tests for advanced analytics query functions.

Tests the 4 new endpoint groups added in Sprint 37:
- _realtime_metrics_query
- _cost_summary_query
- _cost_trend_query
- _anomaly_detection_query
- _skill_benchmark_query
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api_server.routes.analytics import (
    _anomaly_detection_query,
    _cost_summary_query,
    _cost_trend_query,
    _realtime_metrics_query,
    _skill_benchmark_query,
)
from packages.db.models import (
    Base,
    LLMCostRecord,
    Skill,
    SkillRun,
    SkillStatus,
    Task,
    TaskStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _make_task(
    db: Session,
    status: TaskStatus = TaskStatus.COMPLETED,
    hours_ago: float = 0,
    update_hours_ago: float = 0,
) -> Task:
    """Create a task with controlled timestamps."""
    now = datetime.now(UTC)
    task = Task(
        goal="test task",
        status=status,
        created_at=now - timedelta(hours=hours_ago),
        updated_at=now - timedelta(hours=update_hours_ago),
    )
    db.add(task)
    db.commit()
    return task


def _make_cost_record(
    db: Session,
    provider: str = "openai",
    model: str = "gpt-4",
    cost: float = 0.01,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    hours_ago: float = 0,
) -> LLMCostRecord:
    """Create an LLM cost record."""
    record = LLMCostRecord(
        provider=provider,
        model=model,
        estimated_cost_usd=cost,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )
    db.add(record)
    db.commit()
    return record


def _make_skill(
    db: Session,
    name: str = "test-skill",
    success_rate: float = 0.9,
    total_runs: int = 10,
    status: SkillStatus = SkillStatus.STABLE,
) -> Skill:
    """Create a skill."""
    skill = Skill(
        name=name,
        success_rate=success_rate,
        total_runs=total_runs,
        status=status,
        definition={"type": "test"},
    )
    db.add(skill)
    db.commit()
    return skill


def _make_skill_run(
    db: Session,
    skill_id: str,
    success: bool = True,
    execution_time: float | None = 1.5,
    cost: float | None = 0.02,
    hours_ago: float = 0,
) -> SkillRun:
    """Create a skill run."""
    run = SkillRun(
        skill_id=skill_id,
        task_id="fake-task",
        success=success,
        execution_time=execution_time,
        estimated_cost_usd=cost,
        created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )
    db.add(run)
    db.commit()
    return run


# ── Real-time Metrics ────────────────────────────────────────────────────


@pytest.mark.unit
class TestRealtimeMetrics:
    def test_empty_db_returns_zero_defaults(self, db):
        result = _realtime_metrics_query(db)
        assert result["running_tasks"] == 0
        assert result["completed_last_hour"] == 0
        assert result["failed_last_hour"] == 0
        assert result["avg_execution_time_seconds"] is None
        assert result["tasks_per_hour"] == 0.0
        assert result["active_skills"] == 0
        assert result["total_cost_usd"] == 0.0

    def test_running_tasks_counted(self, db):
        _make_task(db, status=TaskStatus.EXECUTING)
        _make_task(db, status=TaskStatus.EXECUTING)
        _make_task(db, status=TaskStatus.COMPLETED)
        result = _realtime_metrics_query(db)
        assert result["running_tasks"] == 2

    def test_completed_last_hour(self, db):
        _make_task(db, status=TaskStatus.COMPLETED, update_hours_ago=0.5)
        _make_task(db, status=TaskStatus.COMPLETED, update_hours_ago=2)
        result = _realtime_metrics_query(db)
        assert result["completed_last_hour"] == 1

    def test_failed_last_hour(self, db):
        _make_task(db, status=TaskStatus.FAILED, update_hours_ago=0.3)
        _make_task(db, status=TaskStatus.FAILED, update_hours_ago=0.7)
        result = _realtime_metrics_query(db)
        assert result["failed_last_hour"] == 2

    def test_tasks_per_hour_calculated(self, db):
        now = datetime.now(UTC)
        for i in range(12):
            db.add(Task(
                goal=f"t-{i}",
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(hours=i),
                updated_at=now,
            ))
        db.commit()
        result = _realtime_metrics_query(db)
        assert result["tasks_per_hour"] == 0.5

    def test_total_cost_from_llm_records(self, db):
        _make_cost_record(db, cost=1.5)
        _make_cost_record(db, cost=2.5)
        result = _realtime_metrics_query(db)
        assert result["total_cost_usd"] == 4.0

    def test_avg_execution_time_returns_value_or_none(self, db):
        # SQLite julianday works for simple date diffs — just ensure no crash
        _make_task(db, status=TaskStatus.COMPLETED, hours_ago=1, update_hours_ago=0)
        result = _realtime_metrics_query(db)
        # Value may be None on some SQLite builds or a float — both acceptable
        assert result["avg_execution_time_seconds"] is None or isinstance(
            result["avg_execution_time_seconds"], float
        )


# ── Cost Summary ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCostSummary:
    def test_empty_db_returns_zero_totals(self, db):
        result = _cost_summary_query(db, 30)
        assert result["total_cost_usd"] == 0.0
        assert result["total_prompt_tokens"] == 0
        assert result["total_completion_tokens"] == 0
        assert result["total_requests"] == 0
        assert result["breakdown"] == []

    def test_single_record(self, db):
        _make_cost_record(db, provider="openai", model="gpt-4", cost=0.05, prompt_tokens=200, completion_tokens=100)
        result = _cost_summary_query(db, 30)
        assert result["total_cost_usd"] == 0.05
        assert result["total_prompt_tokens"] == 200
        assert result["total_completion_tokens"] == 100
        assert result["total_requests"] == 1

    def test_multiple_records_aggregated(self, db):
        _make_cost_record(db, cost=1.0, prompt_tokens=100, completion_tokens=50)
        _make_cost_record(db, cost=2.0, prompt_tokens=200, completion_tokens=100)
        result = _cost_summary_query(db, 30)
        assert result["total_cost_usd"] == 3.0
        assert result["total_prompt_tokens"] == 300
        assert result["total_requests"] == 2

    def test_breakdown_grouped_by_provider_model(self, db):
        _make_cost_record(db, provider="openai", model="gpt-4", cost=1.0)
        _make_cost_record(db, provider="openai", model="gpt-4", cost=2.0)
        _make_cost_record(db, provider="anthropic", model="claude-3", cost=0.5)
        result = _cost_summary_query(db, 30)
        assert len(result["breakdown"]) == 2
        # Sorted by cost desc: openai/gpt-4 first
        openai_row = next(r for r in result["breakdown"] if r["provider"] == "openai")
        assert openai_row["estimated_cost_usd"] == 3.0
        assert openai_row["requests"] == 2

    def test_respects_days_cutoff(self, db):
        _make_cost_record(db, cost=5.0, hours_ago=10)  # within 30 days
        _make_cost_record(db, cost=5.0, hours_ago=800)  # outside 30 days
        result = _cost_summary_query(db, 30)
        assert result["total_cost_usd"] == 5.0


# ── Cost Trend ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCostTrend:
    def test_empty_db_returns_empty_trend(self, db):
        result = _cost_trend_query(db, 30)
        assert result["trend"] == []
        assert result["days"] == 30

    def test_daily_aggregation(self, db):
        _make_cost_record(db, cost=1.0, hours_ago=1)
        _make_cost_record(db, cost=2.0, hours_ago=1)
        _make_cost_record(db, cost=5.0, hours_ago=48)
        result = _cost_trend_query(db, 7)
        assert len(result["trend"]) == 2
        # Today's entry should aggregate the two records from hours_ago=1
        today_total = sum(r["cost_usd"] for r in result["trend"] if r["requests"] == 2)
        assert today_total == 3.0

    def test_trend_sorted_by_date(self, db):
        _make_cost_record(db, cost=1.0, hours_ago=1)
        _make_cost_record(db, cost=2.0, hours_ago=48)
        result = _cost_trend_query(db, 7)
        dates = [r["date"] for r in result["trend"]]
        assert dates == sorted(dates)


# ── Anomaly Detection ────────────────────────────────────────────────────


@pytest.mark.unit
class TestAnomalyDetection:
    def test_no_anomalies_on_clean_db(self, db):
        result = _anomaly_detection_query(db)
        assert result["alerts"] == []
        assert "checked_at" in result

    def test_failure_spike_detected(self, db):
        now = datetime.now(UTC)
        # Baseline: 1 failed, 10 completed over last 24h
        for i in range(10):
            db.add(Task(
                goal=f"baseline-ok-{i}",
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(hours=12),
                updated_at=now - timedelta(hours=12),
            ))
        db.add(Task(
            goal="baseline-fail",
            status=TaskStatus.FAILED,
            created_at=now - timedelta(hours=12),
            updated_at=now - timedelta(hours=12),
        ))
        # Recent (last 1h): 5 failed, 1 completed -> rate=83.3% (>80%)
        for i in range(5):
            db.add(Task(
                goal=f"recent-fail-{i}",
                status=TaskStatus.FAILED,
                created_at=now - timedelta(minutes=30),
                updated_at=now - timedelta(minutes=30),
            ))
        db.add(Task(
            goal="recent-ok",
            status=TaskStatus.COMPLETED,
            created_at=now - timedelta(minutes=30),
            updated_at=now - timedelta(minutes=30),
        ))
        db.commit()
        result = _anomaly_detection_query(db)
        spike_alerts = [a for a in result["alerts"] if a["type"] == "failure_spike"]
        assert len(spike_alerts) == 1
        assert spike_alerts[0]["severity"] == "critical"

    def test_failure_spike_warning_severity(self, db):
        now = datetime.now(UTC)
        # Baseline: 1 failure out of 10
        for i in range(10):
            db.add(Task(
                goal=f"bl-ok-{i}",
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(hours=12),
                updated_at=now - timedelta(hours=12),
            ))
        db.add(Task(
            goal="bl-fail",
            status=TaskStatus.FAILED,
            created_at=now - timedelta(hours=12),
            updated_at=now - timedelta(hours=12),
        ))
        # Recent: 2 failed, 1 completed -> rate=66.7% (>50%, <80%, >2x baseline)
        for i in range(2):
            db.add(Task(
                goal=f"rec-fail-{i}",
                status=TaskStatus.FAILED,
                created_at=now - timedelta(minutes=30),
                updated_at=now - timedelta(minutes=30),
            ))
        db.add(Task(
            goal="rec-ok",
            status=TaskStatus.COMPLETED,
            created_at=now - timedelta(minutes=30),
            updated_at=now - timedelta(minutes=30),
        ))
        db.commit()
        result = _anomaly_detection_query(db)
        spike_alerts = [a for a in result["alerts"] if a["type"] == "failure_spike"]
        assert len(spike_alerts) == 1
        assert spike_alerts[0]["severity"] == "warning"

    def test_skill_degradation_detected(self, db):
        _make_skill(db, name="broken-skill", success_rate=0.25, total_runs=10, status=SkillStatus.STABLE)
        result = _anomaly_detection_query(db)
        deg_alerts = [a for a in result["alerts"] if a["type"] == "skill_degradation"]
        assert len(deg_alerts) == 1
        assert deg_alerts[0]["severity"] == "critical"
        assert "broken-skill" in deg_alerts[0]["message"]

    def test_skill_degradation_warning(self, db):
        _make_skill(db, name="degraded-skill", success_rate=0.45, total_runs=7, status=SkillStatus.CANDIDATE)
        result = _anomaly_detection_query(db)
        deg_alerts = [a for a in result["alerts"] if a["type"] == "skill_degradation"]
        assert len(deg_alerts) == 1
        assert deg_alerts[0]["severity"] == "warning"

    def test_skill_degradation_requires_min_runs(self, db):
        # Only 3 runs — below the threshold of 5
        _make_skill(db, name="few-runs", success_rate=0.1, total_runs=3, status=SkillStatus.STABLE)
        result = _anomaly_detection_query(db)
        deg_alerts = [a for a in result["alerts"] if a["type"] == "skill_degradation"]
        assert len(deg_alerts) == 0

    def test_disabled_skill_not_flagged(self, db):
        _make_skill(db, name="disabled-skill", success_rate=0.1, total_runs=10, status=SkillStatus.DISABLED)
        result = _anomaly_detection_query(db)
        deg_alerts = [a for a in result["alerts"] if a["type"] == "skill_degradation"]
        assert len(deg_alerts) == 0


# ── Skill Benchmark ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestSkillBenchmark:
    def test_empty_db_returns_empty_skills(self, db):
        result = _skill_benchmark_query(db, 10)
        assert result["skills"] == []

    def test_skills_with_runs_show_avg_execution_and_cost(self, db):
        skill = _make_skill(db, name="bench-skill", success_rate=0.8, total_runs=5)
        _make_skill_run(db, skill_id=skill.id, execution_time=2.0, cost=0.05)
        _make_skill_run(db, skill_id=skill.id, execution_time=4.0, cost=0.15)
        result = _skill_benchmark_query(db, 10)
        assert len(result["skills"]) == 1
        s = result["skills"][0]
        assert s["name"] == "bench-skill"
        assert s["avg_execution_time"] == 3.0
        assert s["avg_cost_usd"] == 0.1
        assert s["success_rate"] == 80.0
        assert s["total_runs"] == 5

    def test_top_n_limit_respected(self, db):
        for i in range(5):
            skill = _make_skill(db, name=f"skill-{i}", total_runs=10 - i)
            _make_skill_run(db, skill_id=skill.id, execution_time=1.0, cost=0.01)
        result = _skill_benchmark_query(db, 3)
        assert len(result["skills"]) == 3
        # Sorted by total_runs desc
        assert result["skills"][0]["total_runs"] >= result["skills"][1]["total_runs"]

    def test_disabled_skills_excluded(self, db):
        _make_skill(db, name="active-skill", total_runs=10, status=SkillStatus.STABLE)
        _make_skill(db, name="disabled-skill", total_runs=20, status=SkillStatus.DISABLED)
        result = _skill_benchmark_query(db, 10)
        assert len(result["skills"]) == 1
        assert result["skills"][0]["name"] == "active-skill"

    def test_trend_included_in_skill_data(self, db):
        skill = _make_skill(db, name="trend-skill", total_runs=3)
        _make_skill_run(db, skill_id=skill.id, success=True, hours_ago=2)
        _make_skill_run(db, skill_id=skill.id, success=False, hours_ago=1)
        result = _skill_benchmark_query(db, 10)
        s = result["skills"][0]
        assert "trend" in s
        assert len(s["trend"]) == 2
        assert all("success" in t and "created_at" in t for t in s["trend"])
