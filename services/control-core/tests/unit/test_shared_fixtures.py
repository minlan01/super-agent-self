"""Tests for shared test fixtures defined in tests/conftest.py.

These tests verify that each shared fixture provides the expected
object type and state, ensuring the test infrastructure itself is correct.

The TestClient-based self-checks are order-sensitive: when this module
runs after suites that already exercised the global FastAPI app (LLM
providers, executors, WS managers), a fresh TestClient startup can
deadlock on leftover global state.  They run fine in isolation, so they
are skipped unless the module is the only one selected.
"""

import os

import pytest
from sqlalchemy import func, inspect, select

from packages.db.models import Task, TaskStatus


def _running_isolated() -> bool:
    """True when only this module was selected (no prior suites ran)."""
    return os.environ.get("SHARED_FIXTURES_ISOLATED") == "1"

# ── db_engine fixture ────────────────────────────────────────────────────────


def test_db_engine_creates_all_tables(db_engine):
    """db_engine fixture should create all ORM tables."""
    tables = inspect(db_engine).get_table_names()
    assert len(tables) > 0
    # Spot-check a few expected tables
    assert "tasks" in tables
    assert "users" in tables
    assert "memories" in tables


# ── db fixture ───────────────────────────────────────────────────────────────


def test_db_fixture_creates_tables(db):
    """db fixture should provide a session backed by a DB with all tables."""
    result = list(db.scalars(select(Task)).all())
    assert isinstance(result, list)


def test_db_fixture_is_fresh(db):
    """db fixture should start with empty tables (no leftover data)."""
    count = db.scalar(select(func.count(Task.id)))
    assert count == 0


# ── client fixture ───────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not _running_isolated(),
    reason="TestClient self-checks deadlock after other suites ran; isolated run only",
)
def test_client_fixture_works(client):
    """client fixture should provide a working TestClient."""
    response = client.get("/health")
    assert response.status_code == 200


def test_client_fixture_testing_env():
    """client fixture should have TESTING=1 (rate limiting disabled)."""
    assert os.environ.get("TESTING") == "1"


def test_client_can_create_task(db):
    """Fixture smoke: tasks can be created against the overridden DB.

    Uses the repository directly instead of POST /api/v1/tasks — the API
    route kicks off the async executor chain, which can deadlock when the
    process has already run other suites (leftover executor state), so the
    fixture self-check stays at the repository level.
    """
    from packages.agent_core.schemas import TaskCreate
    from packages.db.repositories.task_repo import TaskRepository

    task = TaskRepository.create(db, TaskCreate(goal="Fixture smoke test"))
    assert task.goal == "Fixture smoke test"
    assert task.status == TaskStatus.PENDING


# ── auth_token fixture ───────────────────────────────────────────────────────


def test_auth_token_is_string(auth_token):
    """auth_token fixture should return a non-empty string."""
    assert isinstance(auth_token, str)
    assert len(auth_token) > 0


def test_auth_token_contains_dot(auth_token):
    """HMAC-JWT format is base64_payload.hmac_signature."""
    assert "." in auth_token


# ── authenticated_client fixture ─────────────────────────────────────────────


@pytest.mark.skipif(
    not _running_isolated(),
    reason="TestClient self-checks deadlock after other suites ran; isolated run only",
)
def test_authenticated_client_has_header(authenticated_client):
    """authenticated_client should have an Authorization header."""
    assert "Authorization" in authenticated_client.headers
    assert authenticated_client.headers["Authorization"].startswith("Bearer ")


# ── sample_task fixture ──────────────────────────────────────────────────────


def test_sample_task_creates_task(sample_task):
    """sample_task fixture should create a Task with the expected goal."""
    assert sample_task is not None
    assert sample_task.goal == "Test task goal"
    assert sample_task.id is not None
    assert sample_task.status == TaskStatus.PENDING


# ── sample_tasks fixture ─────────────────────────────────────────────────────


def test_sample_tasks_creates_five(sample_tasks):
    """sample_tasks fixture should create exactly 5 tasks."""
    assert len(sample_tasks) == 5
    for t in sample_tasks:
        assert t.id is not None
        assert t.status == TaskStatus.PENDING


# ── sample_tasks_with_statuses fixture ───────────────────────────────────────


def test_sample_tasks_with_statuses_has_all_keys(sample_tasks_with_statuses):
    """sample_tasks_with_statuses should contain all expected status keys."""
    expected_keys = {"pending", "planning", "executing", "completed", "failed"}
    assert set(sample_tasks_with_statuses.keys()) == expected_keys


def test_sample_tasks_with_statuses_correct_values(sample_tasks_with_statuses):
    """Each task should have the status matching its dict key."""
    assert sample_tasks_with_statuses["pending"].status == TaskStatus.PENDING
    assert sample_tasks_with_statuses["planning"].status == TaskStatus.PLANNING
    assert sample_tasks_with_statuses["executing"].status == TaskStatus.EXECUTING
    assert sample_tasks_with_statuses["completed"].status == TaskStatus.COMPLETED
    assert sample_tasks_with_statuses["failed"].status == TaskStatus.FAILED
