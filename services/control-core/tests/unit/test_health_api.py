"""Unit tests for health/metrics endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api_server.routes.health import get_metrics, readiness_check
from packages.db.models import Base, Memory, Task, TaskStatus

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


@pytest.fixture
def db_with_data(db):
    """Populate DB with tasks in various statuses and memories."""
    for status in [TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.COMPLETED]:
        db.add(Task(goal=f"{status.value} task", status=status, user_id="test-user"))
    db.flush()

    db.add(Memory(
        title="Active mem", summary="s", memory_type="execution_experience",
        is_active=True, user_id="test-user",
    ))
    db.add(Memory(
        title="Inactive mem", summary="s", memory_type="workflow_pattern",
        is_active=False, user_id="test-user",
    ))
    db.flush()
    return db


# ── readiness_check ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestReadinessCheck:
    def test_readiness_db_ok(self, db):
        """DB session available and queryable -> ready=True, status 200."""
        result = readiness_check(db=db)
        assert result.status_code == 200
        body = result.body.decode() if isinstance(result.body, bytes) else result.body
        import json
        data = json.loads(body)
        assert data["ready"] is True
        assert data["checks"]["db"] == "ok"

    def test_readiness_db_none(self):
        """db=None skips DB check -> still ready."""
        result = readiness_check(db=None)
        assert result.status_code == 200
        body = result.body.decode() if isinstance(result.body, bytes) else result.body
        import json
        data = json.loads(body)
        assert data["ready"] is True
        assert data["checks"]["db"] == "ok"

    def test_readiness_db_error(self):
        """DB throws an exception -> ready=False, status 503."""
        bad_db = MagicMock(spec=Session)
        bad_db.scalar.side_effect = RuntimeError("connection refused")
        result = readiness_check(db=bad_db)
        assert result.status_code == 503
        body = result.body.decode() if isinstance(result.body, bytes) else result.body
        import json
        data = json.loads(body)
        assert data["ready"] is False
        assert "error" in data["checks"]["db"]


# ── get_metrics ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGetMetrics:
    def test_metrics_returns_task_counts(self, db_with_data):
        result = get_metrics(db=db_with_data)
        assert "tasks" in result
        assert result["tasks"]["pending"] == 1
        assert result["tasks"]["failed"] == 1
        assert result["tasks"]["completed"] == 1

    def test_metrics_returns_memory_counts(self, db_with_data):
        result = get_metrics(db=db_with_data)
        assert "memories" in result
        assert result["memories"]["total"] == 2
        assert result["memories"]["active"] == 1

    def test_metrics_returns_uptime(self, db):
        result = get_metrics(db=db)
        assert "uptime_seconds" in result
        assert result["uptime_seconds"] >= 0

    def test_metrics_returns_version(self, db):
        result = get_metrics(db=db)
        assert result["version"] == "3.11.0"

    def test_metrics_zero_tasks(self, db):
        """Empty DB -> all task counts are zero, total_tasks=0."""
        result = get_metrics(db=db)
        assert result["total_tasks"] == 0
        for status_val in result["tasks"].values():
            assert status_val == 0

    def test_metrics_all_statuses_present(self, db):
        """Every TaskStatus enum value has a key in the tasks dict."""
        result = get_metrics(db=db)
        for status in TaskStatus:
            assert status.value in result["tasks"]
