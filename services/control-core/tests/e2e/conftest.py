"""Shared E2E fixtures — starts FastAPI backend and seeds a test user."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Generator

import pytest
import uvicorn

# Must set TESTING before importing the app so rate-limiting is disabled
os.environ["TESTING"] = "1"
# NOTE: SECRET_KEY, REQUIRE_AUTH and DATABASE_URL are NOT set at module level
# to avoid polluting other test modules.  They are set inside the e2e_server
# fixture so they only affect E2E sessions.


def _find_free_port() -> int:
    """Find and return a random available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def e2e_server() -> Generator[str, None, None]:
    """Start the FastAPI app with uvicorn in a background thread.

    Uses an in-memory SQLite database so tests are fully isolated.
    Yields the base_url (e.g. ``http://127.0.0.1:PORT``).
    """
    # Save old values so we can restore them in teardown and avoid polluting
    # other test modules (unit/integration) that expect REQUIRE_AUTH=false.
    _saved = {
        "REQUIRE_AUTH": os.environ.get("REQUIRE_AUTH"),
        "DATABASE_URL": os.environ.get("DATABASE_URL"),
        "SECRET_KEY": os.environ.get("SECRET_KEY"),
    }

    # Set E2E-specific env vars only within this fixture scope.
    os.environ["REQUIRE_AUTH"] = "1"
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["SECRET_KEY"] = "test-secret-key-for-e2e"

    # Import here so env vars are already set
    from packages.db.session import Base

    # Create all tables in the in-memory DB (already configured via DATABASE_URL)
    Base.metadata.create_all(bind=_get_engine())

    # Seed a test user
    _seed_test_user()

    port = _find_free_port()

    # We need a fresh app instance that picks up the in-memory DB.
    # The app module-level imports have already run, but since we set
    # DATABASE_URL=sqlite:// before importing, the engine should use in-memory.
    from apps.api_server.main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to become ready (up to 10 seconds)
    base_url = f"http://127.0.0.1:{port}"
    _wait_for_server(base_url, timeout=10)

    yield base_url

    # Shutdown
    server.should_exit = True
    thread.join(timeout=5)

    # Restore env vars to prevent polluting other test modules
    for key, old_val in _saved.items():
        if old_val is not None:
            os.environ[key] = old_val
        else:
            os.environ.pop(key, None)


@pytest.fixture(scope="session")
def frontend_url() -> str | None:
    """Return the frontend dev server URL if it is reachable, else None.

    Tests that need the frontend should skip if this returns None.
    """
    import httpx

    url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
    try:
        resp = httpx.get(url, timeout=3, follow_redirects=True)
        if resp.status_code < 500:
            return url
    except (httpx.ConnectError, httpx.TimeoutException):
        pass
    return None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_engine():
    """Return the engine used by the app (respects DATABASE_URL)."""
    from packages.db.session import engine as _engine

    return _engine


def _seed_test_user():
    """Create an admin user in the test database."""
    from packages.db.repositories.auth_repo import AuthRepository
    from packages.db.session import SessionLocal

    db = SessionLocal()
    try:
        existing = AuthRepository.get_by_username(db, "admin")
        if existing is None:
            AuthRepository.create_user(
                db,
                username="admin",
                password="admin123",
                email="admin@test.com",
                role="admin",
            )
    finally:
        db.close()


def _wait_for_server(base_url: str, timeout: float = 10) -> None:
    """Poll the health endpoint until the server responds or timeout."""
    import httpx

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                return
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Server at {base_url} did not start within {timeout}s")
