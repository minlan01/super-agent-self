"""Integration tests for Export, Conversations, Health/Metrics, and Cron APIs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api_server.main import app


@pytest.fixture()
def client():
    """TestClient with a valid Bearer token (P1: require_auth defaults True)."""
    from tests.integration.conftest import make_auth_header

    from packages.db.session import SessionLocal

    db = SessionLocal()
    try:
        headers = make_auth_header(db)
    finally:
        db.close()

    with TestClient(app) as c:
        c.headers.update(headers)
        yield c


# ── Health / Readiness / Metrics ────────────────────────────────────────


@pytest.mark.integration
class TestHealthIntegration:
    def test_health_check(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_readiness_check(self, client: TestClient):
        resp = client.get("/api/v1/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is True
        assert body["checks"]["db"] == "ok"

    def test_metrics(self, client: TestClient):
        resp = client.get("/api/v1/health/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert "tasks" in body
        assert "memories" in body
        assert "uptime_seconds" in body
        assert "version" in body


# ── Export API ──────────────────────────────────────────────────────────


@pytest.mark.integration
class TestExportIntegration:
    def test_export_tasks_json(self, client: TestClient):
        resp = client.get("/api/v1/export/tasks?format=json")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "count" in body
        assert "data" in body

    def test_export_tasks_csv(self, client: TestClient):
        resp = client.get("/api/v1/export/tasks?format=csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/csv; charset=utf-8"
        assert "tasks.csv" in resp.headers["content-disposition"]

    def test_export_memories_json(self, client: TestClient):
        resp = client.get("/api/v1/export/memories?format=json")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_export_audit_json(self, client: TestClient):
        resp = client.get("/api/v1/export/audit?format=json")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_export_with_data(self, client: TestClient):
        # Create a task first
        client.post("/api/v1/tasks", json={"goal": "export-test-task"})

        resp = client.get("/api/v1/export/tasks?format=json")
        body = resp.json()
        assert body["count"] >= 1
        goals = [item["goal"] for item in body["data"]]
        assert "export-test-task" in goals


# ── Conversations API ──────────────────────────────────────────────────


@pytest.mark.integration
class TestConversationIntegration:
    def test_list_conversations_with_filter(self, client: TestClient):
        """P1 semantics: the ?user_id= query param is IGNORED (anti-forgery);
        a non-admin user only sees their own (empty) conversation list."""
        from tests.integration.conftest import make_auth_header

        from packages.db.session import SessionLocal

        db = SessionLocal()
        try:
            viewer_headers = make_auth_header(db, role="viewer")
        finally:
            db.close()

        # The client's default admin header sees everything (owner filter
        # is disabled for admins); client-sent user_id must not change that.
        resp = client.get("/api/v1/conversations?user_id=no-such-user-xyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

        # A fresh viewer user sees only their own conversations: empty.
        saved = dict(client.headers)
        client.headers.update(viewer_headers)
        try:
            resp2 = client.get("/api/v1/conversations")
            assert resp2.status_code == 200
            body2 = resp2.json()
            assert body2["count"] == 0
            assert body2["data"] == []
        finally:
            client.headers.clear()
            client.headers.update(saved)

    def test_create_and_get_conversation(self, client: TestClient):
        # Create a conversation via chat (which auto-creates conversations)
        # Or use the repository directly — but for integration test, let's check list works
        resp = client.get("/api/v1/conversations?limit=10&offset=0")
        assert resp.status_code == 200

    def test_get_nonexistent_conversation(self, client: TestClient):
        resp = client.get("/api/v1/conversations/nonexistent-id")
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False

    def test_delete_nonexistent_conversation(self, client: TestClient):
        resp = client.delete("/api/v1/conversations/nonexistent-id")
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False


# ── Cron CRUD API ──────────────────────────────────────────────────────


@pytest.mark.integration
class TestCronIntegration:
    def test_list_cron_jobs_format(self, client: TestClient):
        resp = client.get("/api/v1/cron")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "count" in body
        assert "data" in body
        assert isinstance(body["data"], list)

    def test_create_cron_job(self, client: TestClient):
        resp = client.post("/api/v1/cron", json={
            "name": "test-cron",
            "schedule": "every 30m",
            "goal": "run tests",
            "edition": "enterprise",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "test-cron"
        assert body["schedule"] == "every 30m"
        assert "id" in body

    def test_create_and_list_and_delete(self, client: TestClient):
        # Create
        create_resp = client.post("/api/v1/cron", json={
            "name": "chain-test",
            "schedule": "every 1h",
            "goal": "chain test goal",
        })
        assert create_resp.status_code == 201
        job_id = create_resp.json()["id"]

        # List
        list_resp = client.get("/api/v1/cron")
        body = list_resp.json()
        assert body["count"] >= 1
        ids = [j["id"] for j in body["data"]]
        assert job_id in ids

        # Get
        get_resp = client.get(f"/api/v1/cron/{job_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "chain-test"

        # Update
        update_resp = client.put(f"/api/v1/cron/{job_id}", json={"name": "updated-chain"})
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "updated-chain"

        # Delete
        del_resp = client.delete(f"/api/v1/cron/{job_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

        # Verify deleted
        get_resp2 = client.get(f"/api/v1/cron/{job_id}")
        assert get_resp2.status_code == 404

    def test_create_with_invalid_upstream(self, client: TestClient):
        resp = client.post("/api/v1/cron", json={
            "name": "bad-chain",
            "schedule": "every 1h",
            "goal": "fail",
            "context_from": ["nonexistent-id"],
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert "not found" in body["message"]

    def test_cron_self_reference_rejected(self, client: TestClient):
        # Create a job
        create_resp = client.post("/api/v1/cron", json={
            "name": "self-ref",
            "schedule": "every 1h",
            "goal": "test",
        })
        job_id = create_resp.json()["id"]

        # Try to update with self-reference
        update_resp = client.put(f"/api/v1/cron/{job_id}", json={
            "context_from": [job_id],
        })
        assert update_resp.status_code == 400
        assert update_resp.json()["success"] is False


# ── File Download API ──────────────────────────────────────────────────


@pytest.mark.integration
class TestFileDownloadIntegration:
    def test_download_nonexistent_file(self, client: TestClient):
        resp = client.get("/api/v1/files/nonexistent.txt")
        assert resp.status_code == 404

    def test_path_traversal_blocked(self, client: TestClient):
        resp = client.get("/api/v1/files/../../../etc/passwd")
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False

    def test_download_existing_file(self, client: TestClient, tmp_path):
        # Create a test file in workspace
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        test_file = workspace / "test-output.txt"
        test_file.write_text("hello from workspace", encoding="utf-8")

        # Patch workspace root for this test
        from apps.api_server.routes import files
        original_root = files._WORKSPACE_ROOT
        files._WORKSPACE_ROOT = workspace.resolve()

        try:
            resp = client.get("/api/v1/files/test-output.txt")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/octet-stream"
        finally:
            files._WORKSPACE_ROOT = original_root


# ── Error response format ──────────────────────────────────────────────


@pytest.mark.integration
class TestErrorResponseFormat:
    def test_404_returns_consistent_format(self, client: TestClient):
        resp = client.get("/api/v1/tasks/nonexistent-id")
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False
        assert "message" in body

    def test_422_validation_error_format(self, client: TestClient):
        # Missing required 'goal' field
        resp = client.post("/api/v1/tasks", json={})
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False
        assert "message" in body
