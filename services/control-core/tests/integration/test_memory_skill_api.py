"""Integration tests for Memory and Skill API routes."""

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


# ── Memory API ────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestMemoryAPI:
    def test_list_memories(self, client: TestClient):
        resp = client.get("/api/v1/memory")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_search_memories(self, client: TestClient):
        resp = client.get("/api/v1/memory/search", params={"keyword": "test"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_get_memory_not_found(self, client: TestClient):
        resp = client.get("/api/v1/memory/nonexistent-id")
        assert resp.status_code == 404

    def test_disable_memory_not_found(self, client: TestClient):
        resp = client.post("/api/v1/memory/nonexistent-id/disable")
        assert resp.status_code == 404

    def test_delete_memory_not_found(self, client: TestClient):
        resp = client.delete("/api/v1/memory/nonexistent-id")
        assert resp.status_code == 404


# ── Skill API ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestSkillAPI:
    def test_list_skills(self, client: TestClient):
        resp = client.get("/api/v1/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_get_skill_not_found(self, client: TestClient):
        resp = client.get("/api/v1/skills/nonexistent-id")
        assert resp.status_code == 404

    def test_approve_skill_not_found(self, client: TestClient):
        resp = client.post("/api/v1/skills/nonexistent-id/approve")
        assert resp.status_code == 404

    def test_disable_skill_not_found(self, client: TestClient):
        resp = client.post("/api/v1/skills/nonexistent-id/disable")
        assert resp.status_code == 404

    def test_rollback_skill_not_found(self, client: TestClient):
        resp = client.post("/api/v1/skills/nonexistent-id/rollback")
        assert resp.status_code == 404


# ── Audit API ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestAuditAPI:
    def test_list_audit_events(self, client: TestClient):
        resp = client.get("/api/v1/audit")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_list_audit_with_task_filter(self, client: TestClient):
        resp = client.get("/api/v1/audit", params={"task_id": "nonexistent"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)


# ── Approval API ──────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestApprovalAPI:
    def test_list_approvals(self, client: TestClient):
        resp = client.get("/api/v1/approvals")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_get_approval_not_found(self, client: TestClient):
        resp = client.get("/api/v1/approvals/nonexistent-id")
        assert resp.status_code == 404

    def test_resolve_approval_not_found(self, client: TestClient):
        resp = client.post(
            "/api/v1/approvals/nonexistent-id/resolve",
            json={"approved": True, "approved_by": "admin"},
        )
        assert resp.status_code == 404
