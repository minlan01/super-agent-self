"""Integration tests for analytics API endpoints.

Covers the 5 new analytics endpoints:
- GET /api/v1/analytics/execution/realtime
- GET /api/v1/analytics/costs/summary
- GET /api/v1/analytics/costs/trend
- GET /api/v1/analytics/skills/benchmark
- GET /api/v1/analytics/anomalies
"""

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.db.models import (
    Base,
    LLMCostRecord,
    Skill,
    SkillRun,
    SkillStatus,
    Task,
    TaskStatus,
)
from packages.db.repositories.auth_repo import AuthRepository
from packages.db.repositories.rbac_repo import RBACRepository
from packages.auth.auth_service import create_access_token
from packages.config import clear_settings_cache


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def app_and_client():
    """Create a test app with RBAC enabled and REQUIRE_AUTH=true."""
    _prev_require_auth = os.environ.get("REQUIRE_AUTH")
    os.environ["REQUIRE_AUTH"] = "1"
    clear_settings_cache()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)

    # Seed RBAC
    RBACRepository.seed_default_roles_and_permissions(db)
    db.commit()

    from packages.db.session import get_db
    from apps.api_server.main import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass  # Don't close the shared session

    app.dependency_overrides[get_db] = _override_get_db

    client = TestClient(app)
    yield client, db

    app.dependency_overrides.clear()
    db.close()
    if _prev_require_auth is not None:
        os.environ["REQUIRE_AUTH"] = _prev_require_auth
    else:
        os.environ.pop("REQUIRE_AUTH", None)


@pytest.fixture
def admin_token(app_and_client):
    """Create an admin user and return a valid JWT token."""
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="admin", password="admin123")
    user.role = "admin"  # type: ignore
    db.commit()

    admin_role = RBACRepository.get_role_by_name(db, "admin")
    if admin_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=admin_role.id)
        db.commit()

    return create_access_token({"sub": user.id, "username": user.username})


@pytest.fixture
def auth_headers(admin_token):
    """Return authorization headers dict for admin user."""
    return {"Authorization": f"Bearer {admin_token}"}


# ── TestAnalyticsAuth ────────────────────────────────────────────────────


class TestAnalyticsAuth:
    """Unauthenticated requests return 401/403 for all new analytics endpoints."""

    @pytest.mark.parametrize("path", [
        "/api/v1/analytics/execution/realtime",
        "/api/v1/analytics/costs/summary",
        "/api/v1/analytics/costs/trend",
        "/api/v1/analytics/skills/benchmark",
        "/api/v1/analytics/anomalies",
    ])
    def test_unauthenticated_returns_401_or_403(self, app_and_client, path):
        client, _ = app_and_client
        resp = client.get(path)
        assert resp.status_code in (401, 403)


# ── TestRealtimeMetrics ──────────────────────────────────────────────────


class TestRealtimeMetrics:
    """Tests for GET /api/v1/analytics/execution/realtime."""

    def test_returns_200_with_correct_structure(self, app_and_client, auth_headers):
        client, _ = app_and_client
        resp = client.get("/api/v1/analytics/execution/realtime", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "running_tasks" in data
        assert "completed_last_hour" in data
        assert "failed_last_hour" in data
        assert "avg_execution_time_seconds" in data
        assert "tasks_per_hour" in data
        assert "active_skills" in data
        assert "total_cost_usd" in data

    def test_empty_db_returns_zeros(self, app_and_client, auth_headers):
        client, _ = app_and_client
        resp = client.get("/api/v1/analytics/execution/realtime", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["running_tasks"] == 0
        assert data["completed_last_hour"] == 0
        assert data["failed_last_hour"] == 0
        assert data["tasks_per_hour"] == 0.0

    def test_counts_running_tasks(self, app_and_client, auth_headers):
        client, db = app_and_client
        now = datetime.now(UTC)

        # Create 2 executing tasks and 1 completed task
        db.add(Task(goal="running-1", status=TaskStatus.EXECUTING, created_at=now, updated_at=now))
        db.add(Task(goal="running-2", status=TaskStatus.EXECUTING, created_at=now, updated_at=now))
        db.add(Task(goal="done-1", status=TaskStatus.COMPLETED, created_at=now, updated_at=now))
        db.commit()

        resp = client.get("/api/v1/analytics/execution/realtime", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["running_tasks"] == 2  # EXECUTING tasks counted as running

    def test_counts_completed_last_hour(self, app_and_client, auth_headers):
        client, db = app_and_client
        now = datetime.now(UTC)
        recent = now - timedelta(minutes=30)
        old = now - timedelta(hours=2)

        db.add(Task(goal="recent-done", status=TaskStatus.COMPLETED, created_at=recent, updated_at=recent))
        db.add(Task(goal="old-done", status=TaskStatus.COMPLETED, created_at=old, updated_at=old))
        db.commit()

        resp = client.get("/api/v1/analytics/execution/realtime", headers=auth_headers)
        data = resp.json()
        assert data["completed_last_hour"] == 1


# ── TestCostAnalytics ────────────────────────────────────────────────────


class TestCostAnalytics:
    """Tests for GET /api/v1/analytics/costs/summary and /costs/trend."""

    def test_cost_summary_returns_200(self, app_and_client, auth_headers):
        client, _ = app_and_client
        resp = client.get("/api/v1/analytics/costs/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_cost_usd" in data
        assert "total_prompt_tokens" in data
        assert "total_completion_tokens" in data
        assert "total_requests" in data
        assert "breakdown" in data

    def test_cost_summary_empty_db(self, app_and_client, auth_headers):
        client, _ = app_and_client
        resp = client.get("/api/v1/analytics/costs/summary", headers=auth_headers)
        data = resp.json()
        assert data["total_cost_usd"] == 0.0
        assert data["total_requests"] == 0
        assert data["breakdown"] == []

    def test_cost_summary_with_records(self, app_and_client, auth_headers):
        client, db = app_and_client
        now = datetime.now(UTC)

        db.add(LLMCostRecord(
            provider="openai", model="gpt-4",
            prompt_tokens=1000, completion_tokens=500,
            estimated_cost_usd=0.05, created_at=now,
        ))
        db.add(LLMCostRecord(
            provider="deepseek", model="deepseek-v3",
            prompt_tokens=2000, completion_tokens=1000,
            estimated_cost_usd=0.02, created_at=now,
        ))
        db.commit()

        resp = client.get("/api/v1/analytics/costs/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost_usd"] == pytest.approx(0.07, abs=0.001)
        assert data["total_prompt_tokens"] == 3000
        assert data["total_completion_tokens"] == 1500
        assert data["total_requests"] == 2
        assert len(data["breakdown"]) == 2

    def test_cost_summary_days_param(self, app_and_client, auth_headers):
        client, db = app_and_client
        now = datetime.now(UTC)
        old = now - timedelta(days=60)

        # Recent record
        db.add(LLMCostRecord(
            provider="openai", model="gpt-4",
            prompt_tokens=500, completion_tokens=200,
            estimated_cost_usd=0.03, created_at=now,
        ))
        # Old record (outside 30-day window)
        db.add(LLMCostRecord(
            provider="openai", model="gpt-4",
            prompt_tokens=500, completion_tokens=200,
            estimated_cost_usd=0.10, created_at=old,
        ))
        db.commit()

        resp = client.get("/api/v1/analytics/costs/summary?days=30", headers=auth_headers)
        data = resp.json()
        assert data["total_cost_usd"] == pytest.approx(0.03, abs=0.001)
        assert data["total_requests"] == 1

    def test_cost_trend_returns_200(self, app_and_client, auth_headers):
        client, _ = app_and_client
        resp = client.get("/api/v1/analytics/costs/trend", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "days" in data
        assert "trend" in data
        assert isinstance(data["trend"], list)

    def test_cost_trend_with_records(self, app_and_client, auth_headers):
        client, db = app_and_client
        now = datetime.now(UTC)

        db.add(LLMCostRecord(
            provider="openai", model="gpt-4",
            prompt_tokens=1000, completion_tokens=500,
            estimated_cost_usd=0.05, created_at=now,
        ))
        db.commit()

        resp = client.get("/api/v1/analytics/costs/trend?days=30", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["trend"]) >= 1
        entry = data["trend"][0]
        assert "date" in entry
        assert "cost_usd" in entry
        assert "prompt_tokens" in entry
        assert "completion_tokens" in entry
        assert "requests" in entry


# ── TestSkillBenchmark ───────────────────────────────────────────────────


class TestSkillBenchmark:
    """Tests for GET /api/v1/analytics/skills/benchmark."""

    def test_returns_200_with_skills_array(self, app_and_client, auth_headers):
        client, _ = app_and_client
        resp = client.get("/api/v1/analytics/skills/benchmark", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_empty_db_returns_empty_skills(self, app_and_client, auth_headers):
        client, _ = app_and_client
        resp = client.get("/api/v1/analytics/skills/benchmark", headers=auth_headers)
        data = resp.json()
        assert data["skills"] == []

    def test_each_skill_has_required_fields(self, app_and_client, auth_headers):
        client, db = app_and_client
        now = datetime.now(UTC)

        skill = Skill(
            name="test-skill",
            status=SkillStatus.STABLE,
            definition={"type": "test"},
            success_rate=0.85,
            total_runs=10,
        )
        db.add(skill)
        db.flush()

        db.add(SkillRun(
            skill_id=skill.id, task_id="t1",
            success=True, execution_time=2.5,
            estimated_cost_usd=0.01,
        ))
        db.commit()

        resp = client.get("/api/v1/analytics/skills/benchmark", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["skills"]) == 1

        s = data["skills"][0]
        assert s["name"] == "test-skill"
        assert s["success_rate"] == 85.0
        assert s["total_runs"] == 10
        assert "avg_execution_time" in s

    def test_top_n_param_limits_results(self, app_and_client, auth_headers):
        client, db = app_and_client
        now = datetime.now(UTC)

        for i in range(5):
            db.add(Skill(
                name=f"skill-{i}",
                status=SkillStatus.STABLE,
                definition={"type": "test"},
                success_rate=0.5,
                total_runs=i,
            ))
        db.commit()

        resp = client.get("/api/v1/analytics/skills/benchmark?top_n=3", headers=auth_headers)
        data = resp.json()
        assert len(data["skills"]) <= 3


# ── TestAnomalies ────────────────────────────────────────────────────────


class TestAnomalies:
    """Tests for GET /api/v1/analytics/anomalies."""

    def test_returns_200_with_alerts_array(self, app_and_client, auth_headers):
        client, _ = app_and_client
        resp = client.get("/api/v1/analytics/anomalies", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "checked_at" in data
        assert isinstance(data["alerts"], list)

    def test_empty_db_returns_empty_alerts(self, app_and_client, auth_headers):
        client, _ = app_and_client
        resp = client.get("/api/v1/analytics/anomalies", headers=auth_headers)
        data = resp.json()
        assert data["alerts"] == []

    def test_degraded_skill_triggers_alert(self, app_and_client, auth_headers):
        client, db = app_and_client

        # Skill with low success_rate (<0.5) and enough runs (>=5) triggers skill_degradation
        db.add(Skill(
            name="degraded-skill",
            status=SkillStatus.STABLE,
            definition={"type": "test"},
            success_rate=0.2,
            total_runs=10,
        ))
        db.commit()

        resp = client.get("/api/v1/analytics/anomalies", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        degradation_alerts = [a for a in data["alerts"] if a["type"] == "skill_degradation"]
        assert len(degradation_alerts) == 1
        alert = degradation_alerts[0]
        assert alert["resource"] == "skill:degraded-skill"
        assert alert["severity"] == "critical"  # rate < 0.3

    def test_moderately_degraded_skill_is_warning(self, app_and_client, auth_headers):
        client, db = app_and_client

        # success_rate between 0.3 and 0.5 → warning severity
        db.add(Skill(
            name="warning-skill",
            status=SkillStatus.STABLE,
            definition={"type": "test"},
            success_rate=0.4,
            total_runs=8,
        ))
        db.commit()

        resp = client.get("/api/v1/analytics/anomalies", headers=auth_headers)
        data = resp.json()
        degradation_alerts = [a for a in data["alerts"] if a["type"] == "skill_degradation"]
        assert len(degradation_alerts) == 1
        assert degradation_alerts[0]["severity"] == "warning"

    def test_disabled_skills_not_checked(self, app_and_client, auth_headers):
        client, db = app_and_client

        # Disabled skill should not trigger anomaly even with low rate
        db.add(Skill(
            name="disabled-skill",
            status=SkillStatus.DISABLED,
            definition={"type": "test"},
            success_rate=0.1,
            total_runs=20,
        ))
        db.commit()

        resp = client.get("/api/v1/analytics/anomalies", headers=auth_headers)
        data = resp.json()
        degradation_alerts = [a for a in data["alerts"] if a["type"] == "skill_degradation"]
        assert len(degradation_alerts) == 0

    def test_low_run_count_skill_not_flagged(self, app_and_client, auth_headers):
        client, db = app_and_client

        # Skill with < 5 total_runs should not be flagged even with low rate
        db.add(Skill(
            name="new-skill",
            status=SkillStatus.CANDIDATE,
            definition={"type": "test"},
            success_rate=0.1,
            total_runs=3,
        ))
        db.commit()

        resp = client.get("/api/v1/analytics/anomalies", headers=auth_headers)
        data = resp.json()
        degradation_alerts = [a for a in data["alerts"] if a["type"] == "skill_degradation"]
        assert len(degradation_alerts) == 0
