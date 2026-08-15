"""Integration tests for approvals, editions, and audit routes via TestClient."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api_server.dependencies import get_db
from apps.api_server.main import app
from packages.agent_core.schemas import ApprovalCreate, ApprovalResolve, AuditEventCreate
from packages.db.models import (
    ApprovalType,
    AuditEventType,
    Base,
    Edition,
)
from packages.db.repositories.approval_repo import ApprovalRepository
from packages.db.repositories.audit_repo import AuditRepository

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db_engine():
    """In-memory SQLite with StaticPool — single shared connection."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    s = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


@pytest.fixture
def client(db_engine, db):
    from tests.integration.conftest import make_auth_header

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    headers = make_auth_header(db)
    with TestClient(app) as c:
        c.headers.update(headers)
        yield c
    app.dependency_overrides.clear()


# ── Approvals integration ────────────────────────────────────────────────


@pytest.mark.integration
class TestApprovalsIntegration:
    def test_list_approvals_empty(self, client: TestClient):
        resp = client.get("/api/v1/approvals")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    def test_list_approvals_with_data(self, client: TestClient, db):
        ApprovalRepository.create(db, ApprovalCreate(
            approval_type=ApprovalType.HIGH_RISK_STEP,
            target_id="step-001",
            edition=Edition.ENTERPRISE,
            requested_by="tester",
        ))

        resp = client.get("/api/v1/approvals")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["status"] == "pending"

    def test_get_approval_found(self, client: TestClient, db):
        approval = ApprovalRepository.create(db, ApprovalCreate(
            approval_type=ApprovalType.SKILL,
            target_id="skill-001",
            edition=Edition.PERSONAL,
            requested_by="dev",
        ))

        resp = client.get(f"/api/v1/approvals/{approval.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == approval.id
        assert body["data"]["approval_type"] == "skill"

    def test_get_approval_not_found(self, client: TestClient):
        resp = client.get("/api/v1/approvals/nonexistent-id")
        assert resp.status_code == 404

    def test_resolve_approval_approve(self, client: TestClient, db):
        approval = ApprovalRepository.create(db, ApprovalCreate(
            approval_type=ApprovalType.HIGH_RISK_STEP,
            target_id="step-001",
            edition=Edition.ENTERPRISE,
        ))

        resp = client.post(
            f"/api/v1/approvals/{approval.id}/resolve",
            json={"approved": True, "approved_by": "admin", "reason": "ok"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "approved" in body["message"].lower()

    def test_resolve_approval_reject(self, client: TestClient, db):
        approval = ApprovalRepository.create(db, ApprovalCreate(
            approval_type=ApprovalType.HIGH_RISK_STEP,
            target_id="step-002",
            edition=Edition.ENTERPRISE,
        ))

        resp = client.post(
            f"/api/v1/approvals/{approval.id}/resolve",
            json={"approved": False, "approved_by": "admin", "reason": "risky"},
        )
        assert resp.status_code == 200
        assert "rejected" in resp.json()["message"].lower()

    def test_resolve_approval_already_resolved(self, client: TestClient, db):
        approval = ApprovalRepository.create(db, ApprovalCreate(
            approval_type=ApprovalType.SKILL,
            target_id="skill-002",
        ))
        # Resolve first time
        client.post(
            f"/api/v1/approvals/{approval.id}/resolve",
            json={"approved": True, "approved_by": "admin"},
        )
        # Try second time
        resp = client.post(
            f"/api/v1/approvals/{approval.id}/resolve",
            json={"approved": False, "approved_by": "admin"},
        )
        assert resp.status_code == 400

    def test_list_approvals_with_status_filter(self, client: TestClient, db):
        a1 = ApprovalRepository.create(db, ApprovalCreate(
            approval_type=ApprovalType.HIGH_RISK_STEP,
            target_id="step-010",
        ))
        ApprovalRepository.resolve(db, a1.id, ApprovalResolve(
            approved=True, approved_by="admin",
        ))
        ApprovalRepository.create(db, ApprovalCreate(
            approval_type=ApprovalType.HIGH_RISK_STEP,
            target_id="step-011",
        ))

        resp = client.get("/api/v1/approvals?status=pending")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["status"] == "pending"


# ── Editions integration ─────────────────────────────────────────────────


@pytest.mark.integration
class TestEditionsIntegration:
    def test_list_editions(self, client: TestClient):
        resp = client.get("/api/v1/editions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        # Should have enterprise and personal from configs/editions/
        edition_names = [e["edition"] for e in body["data"]]
        assert "enterprise" in edition_names
        assert "personal" in edition_names

    def test_get_enterprise_edition(self, client: TestClient):
        resp = client.get("/api/v1/editions/enterprise")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["edition"] == "enterprise"
        assert body["data"]["is_enterprise"] is True
        assert "tools" in body["data"]
        assert "policy" in body["data"]
        assert "memory" in body["data"]

    def test_get_personal_edition(self, client: TestClient):
        resp = client.get("/api/v1/editions/personal")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["edition"] == "personal"
        assert body["data"]["is_personal"] is True

    def test_get_edition_not_found(self, client: TestClient):
        resp = client.get("/api/v1/editions/nonexistent")
        assert resp.status_code == 404


# ── Audit integration ────────────────────────────────────────────────────


@pytest.mark.integration
class TestAuditIntegration:
    def test_list_audit_empty(self, client: TestClient):
        resp = client.get("/api/v1/audit")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    def test_list_audit_with_data(self, client: TestClient, db):
        AuditRepository.create(db, AuditEventCreate(
            task_id="t1",
            event_type=AuditEventType.TASK_CREATED,
            detail={"goal": "test"},
        ))

        resp = client.get("/api/v1/audit")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["event_type"] == "task_created"

    def test_filter_by_task_id(self, client: TestClient, db):
        AuditRepository.create(db, AuditEventCreate(
            task_id="t1", event_type=AuditEventType.TASK_CREATED,
        ))
        AuditRepository.create(db, AuditEventCreate(
            task_id="t2", event_type=AuditEventType.TASK_COMPLETED,
        ))

        resp = client.get("/api/v1/audit?task_id=t1")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["task_id"] == "t1"

    def test_filter_by_event_type(self, client: TestClient, db):
        AuditRepository.create(db, AuditEventCreate(
            task_id="t1", event_type=AuditEventType.TASK_CREATED,
        ))
        AuditRepository.create(db, AuditEventCreate(
            task_id="t2", event_type=AuditEventType.TASK_COMPLETED,
        ))

        resp = client.get("/api/v1/audit?event_type=task_completed")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["event_type"] == "task_completed"

    def test_filter_by_both_params(self, client: TestClient, db):
        AuditRepository.create(db, AuditEventCreate(
            task_id="t1", event_type=AuditEventType.TASK_CREATED,
        ))
        AuditRepository.create(db, AuditEventCreate(
            task_id="t1", event_type=AuditEventType.TASK_COMPLETED,
        ))

        resp = client.get("/api/v1/audit?task_id=t1&event_type=task_completed")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["event_type"] == "task_completed"
        assert body["data"][0]["task_id"] == "t1"

    def test_pagination_skip_limit(self, client: TestClient, db):
        for i in range(5):
            AuditRepository.create(db, AuditEventCreate(
                task_id=f"t{i}", event_type=AuditEventType.TASK_CREATED,
            ))

        resp = client.get("/api/v1/audit?skip=2&limit=2")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 2
