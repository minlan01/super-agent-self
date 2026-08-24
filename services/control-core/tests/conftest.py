"""Shared test configuration and fixtures.

Environment:
  TESTING=1     — disables rate limiting middleware
  LLM_PROVIDER=mock — prevents real LLM API calls

Fixtures:
  db_engine   — fresh in-memory SQLite engine with all tables created
  db          — transactional DB session (function-scoped, auto-cleanup)
  client      — TestClient with DB dependency overridden to use test DB
  auth_token  — creates a test user and returns a valid HMAC-JWT token
  authenticated_client — client with Authorization header pre-set
  sample_task — single PENDING task
  sample_tasks — 5 PENDING tasks
  sample_tasks_with_statuses — dict of tasks in each TaskStatus state

Note: Test files that define their own fixtures with the same name (e.g. ``db``,
``client``) will shadow these shared fixtures — pytest resolves from the
innermost scope outward.
"""

import os
import pathlib

# TESTING=1 and LLM_PROVIDER=mock must be set at module level (before any
# app module is imported) because apps.api_server.main reads TESTING at
# import time to decide whether to add rate-limiting middleware.
os.environ["TESTING"] = "1"
os.environ["LLM_PROVIDER"] = "mock"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ── Global test env cleanup ─────────────────────────────────────────────────
# The module-level env sets above are necessary for correct import-time
# behaviour, but they should be restored after the session so they don't
# leak into the parent process (e.g. when running via an IDE).

_BASE_ENV_KEYS = ("TESTING", "LLM_PROVIDER")


@pytest.fixture(scope="session", autouse=True)
def _restore_base_env():
    """Restore TESTING / LLM_PROVIDER after the test session."""
    saved = {k: os.environ.get(k) for k in _BASE_ENV_KEYS}
    yield
    for k, orig in saved.items():
        if orig is not None:
            os.environ[k] = orig
        else:
            os.environ.pop(k, None)


def pytest_configure(config):
    """Base-temp handling now lives in the repo-root conftest
    (services/control-core/conftest.py) so ``pytest packages/...`` runs get
    it too. Kept as a no-op here for discoverability."""
    return


# ── E2E env-var isolation ───────────────────────────────────────────────────
# The session-scoped e2e_server fixture (tests/e2e/conftest.py) sets
# REQUIRE_AUTH=1, DATABASE_URL=sqlite:// and SECRET_KEY for the entire
# pytest session.  Without isolation, those env vars leak into
# unit/integration tests, causing unexpected 401 errors in
# notification/backup routes, wrong DB connections, and auth failures.
# This autouse fixture resets the polluted vars for every non-e2e test
# and restores them afterward so subsequent e2e tests still work.

_E2E_ENV_KEYS = ("REQUIRE_AUTH", "DATABASE_URL", "SECRET_KEY")


@pytest.fixture(autouse=True)
def _isolate_e2e_env_vars(request):
    """Reset REQUIRE_AUTH / DATABASE_URL / SECRET_KEY before each non-e2e test."""
    test_path = str(request.fspath)
    if "tests/e2e" in test_path or "tests\\e2e" in test_path:
        # E2E tests manage env vars via the e2e_server fixture — don't touch.
        yield
        return

    saved = {}
    for key in _E2E_ENV_KEYS:
        saved[key] = os.environ.get(key)
        os.environ.pop(key, None)

    yield

    for key, val in saved.items():
        if val is not None:
            os.environ[key] = val
        else:
            os.environ.pop(key, None)


# Import get_db from the same module that route files use so that
# dependency_overrides patches the exact object FastAPI resolves.
from apps.api_server.dependencies import get_db
from packages.agent_core.schemas import TaskCreate, TaskUpdate
from packages.auth.auth_service import create_access_token
from packages.db.models import Base, TaskStatus
from packages.db.repositories.auth_repo import AuthRepository
from packages.db.repositories.task_repo import TaskRepository

# ── Database fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_engine():
    """Create a fresh in-memory SQLite engine with all tables.

    Uses StaticPool so the single connection is shared across threads,
    which is required for FastAPI/Starlette async handling.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db(db_engine):
    """Provide a transactional DB session that rolls back after each test."""
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    yield session
    session.close()


# ── HTTP client fixtures ─────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def client(db_engine, db):
    """Provide a TestClient with DB dependency overridden to use test DB."""
    from apps.api_server.main import app

    def _override_get_db():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Auth fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def auth_token(db):
    """Create a test user and return a valid HMAC-SHA256 auth token."""
    user = AuthRepository.create_user(db, username="testuser", password="testpass123")
    token = create_access_token({"sub": user.id, "username": user.username})
    return token


@pytest.fixture(scope="function")
def authenticated_client(client, auth_token):
    """Provide a TestClient with Authorization header pre-set."""
    client.headers["Authorization"] = f"Bearer {auth_token}"
    return client


# ── Sample data fixtures ─────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def sample_task(db):
    """Create a single sample task in PENDING status."""
    return TaskRepository.create(db, TaskCreate(goal="Test task goal"))


@pytest.fixture(scope="function")
def sample_tasks(db):
    """Create 5 sample tasks, all in PENDING status."""
    tasks = []
    for i in range(5):
        t = TaskRepository.create(db, TaskCreate(goal=f"Sample task {i + 1}"))
        tasks.append(t)
    return tasks


@pytest.fixture(scope="function")
def sample_tasks_with_statuses(db):
    """Create tasks in various statuses for testing.

    Returns a dict mapping status name (str) to the Task ORM object:
      pending, planning, executing, completed, failed
    """
    pending = TaskRepository.create(db, TaskCreate(goal="Pending task"))

    planning = TaskRepository.create(db, TaskCreate(goal="Planning task"))
    TaskRepository.update(db, planning.id, TaskUpdate(status=TaskStatus.PLANNING))

    executing = TaskRepository.create(db, TaskCreate(goal="Executing task"))
    TaskRepository.update(db, executing.id, TaskUpdate(status=TaskStatus.EXECUTING))

    completed = TaskRepository.create(db, TaskCreate(goal="Completed task"))
    TaskRepository.update(db, completed.id, TaskUpdate(status=TaskStatus.COMPLETED))

    failed = TaskRepository.create(db, TaskCreate(goal="Failed task"))
    TaskRepository.update(db, failed.id, TaskUpdate(status=TaskStatus.FAILED))

    return {
        "pending": pending,
        "planning": planning,
        "executing": executing,
        "completed": completed,
        "failed": failed,
    }
