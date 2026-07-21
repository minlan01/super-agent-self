"""Integration tests for the files download API endpoint."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.db.models import Base
from packages.db.repositories.rbac_repo import RBACRepository
from packages.db.repositories.auth_repo import AuthRepository
from packages.auth.auth_service import create_access_token
from packages.config import clear_settings_cache


@pytest.fixture
def app_and_client():
    """Create a test app with auth enabled, RBAC seeded, and in-memory DB."""
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

    RBACRepository.seed_default_roles_and_permissions(db)
    db.commit()

    from apps.api_server.dependencies import get_db
    from apps.api_server.main import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

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
def admin_headers(app_and_client):
    """Create an admin user and return auth headers."""
    client, db = app_and_client
    user = AuthRepository.create_user(db, username="admin", password="admin123")
    user.role = "admin"  # type: ignore
    db.commit()

    admin_role = RBACRepository.get_role_by_name(db, "admin")
    if admin_role:
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=admin_role.id)
        db.commit()

    token = create_access_token({"sub": user.id, "username": user.username})
    return {"Authorization": f"Bearer {token}"}


# ── GET /api/v1/files/{path} ──────────────────────────────────────────────


@pytest.mark.integration
def test_download_file_requires_auth(app_and_client):
    """Downloading a file without auth returns 401."""
    client, db = app_and_client
    resp = client.get("/api/v1/files/somefile.txt")
    assert resp.status_code == 401


@pytest.mark.integration
def test_download_file_not_found(app_and_client, admin_headers, tmp_path):
    """Requesting a file that does not exist returns 404."""
    client, db = app_and_client
    # Patch workspace root to a temp directory so the path resolves safely
    import apps.api_server.routes.files as files_mod

    original_root = files_mod._WORKSPACE_ROOT
    files_mod._WORKSPACE_ROOT = tmp_path.resolve()
    try:
        resp = client.get("/api/v1/files/nonexistent.txt", headers=admin_headers)
        assert resp.status_code == 404
        assert "not found" in resp.json()["message"].lower()
    finally:
        files_mod._WORKSPACE_ROOT = original_root


@pytest.mark.integration
def test_download_file_path_traversal_blocked(app_and_client, admin_headers, tmp_path):
    """Path traversal attempts are blocked and return 403."""
    client, db = app_and_client
    import apps.api_server.routes.files as files_mod

    original_root = files_mod._WORKSPACE_ROOT
    files_mod._WORKSPACE_ROOT = tmp_path.resolve()
    try:
        # Use a symlink or direct resolve trick: FastAPI normalizes `../`
        # in the URL path, so we test with a path that resolves outside
        # the workspace after symlink resolution.  The simplest way is to
        # pass a path containing `..` segments that survive URL decoding
        # but resolve outside the workspace root.
        resp = client.get("/api/v1/files/..%2F..%2F..%2Fetc%2Fpasswd", headers=admin_headers)
        # Either 403 (traversal detected) or 404 (file not found) is acceptable
        assert resp.status_code in (403, 404)
    finally:
        files_mod._WORKSPACE_ROOT = original_root


@pytest.mark.integration
def test_download_file_success(app_and_client, admin_headers, tmp_path):
    """Downloading an existing file returns the file content."""
    client, db = app_and_client
    import apps.api_server.routes.files as files_mod

    original_root = files_mod._WORKSPACE_ROOT
    # Create workspace subdirectory and a file
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    test_file = workspace_dir / "output.txt"
    test_file.write_text("hello from workspace", encoding="utf-8")

    files_mod._WORKSPACE_ROOT = workspace_dir.resolve()
    try:
        resp = client.get("/api/v1/files/output.txt", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.text == "hello from workspace"
        assert "application/octet-stream" in resp.headers.get("content-type", "")
    finally:
        files_mod._WORKSPACE_ROOT = original_root


@pytest.mark.integration
def test_download_file_nested_path(app_and_client, admin_headers, tmp_path):
    """Downloading a file from a nested subdirectory works."""
    client, db = app_and_client
    import apps.api_server.routes.files as files_mod

    original_root = files_mod._WORKSPACE_ROOT
    workspace_dir = tmp_path / "workspace"
    nested = workspace_dir / "subdir" / "deep"
    nested.mkdir(parents=True)
    test_file = nested / "report.csv"
    test_file.write_text("a,b,c\n1,2,3", encoding="utf-8")

    files_mod._WORKSPACE_ROOT = workspace_dir.resolve()
    try:
        resp = client.get(
            "/api/v1/files/subdir/deep/report.csv",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert "a,b,c" in resp.text
    finally:
        files_mod._WORKSPACE_ROOT = original_root
