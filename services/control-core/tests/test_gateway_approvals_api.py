"""Tests for Gateway Approval API routes (P3.2).

Uses dependency_overrides correctly to inject test DB and mock ActorScope.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from packages.approval.approval_service import ApprovalService
from packages.auth.actor_scope import ActorScope
from packages.db.models import Base
from packages.db.session import Base as AppBase


def _make_test_engine():
    """Create an in-memory engine with all tables (StaticPool for thread sharing)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    return engine


@pytest.fixture()
def app_and_db():
    """Yield (app, session_factory, scope_holder)."""
    engine = _make_test_engine()
    SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    alice = ActorScope(
        tenant_id="t1", principal_id="alice", workspace_id="w1",
        roles=["user"], permissions=[], auth_method="test",
        device_id="dev1", os_session_id="sess1",
    )
    bob = ActorScope(
        tenant_id="t1", principal_id="bob", workspace_id="w1",
        roles=["user"], permissions=[], auth_method="test",
        device_id="dev2", os_session_id="sess2",
    )
    scope_holder = {"current": alice, "alice": alice, "bob": bob}

    from apps.api_server.dependencies import get_db, get_current_actor_scope
    from apps.api_server.routes.gateway_approvals import router

    def _override_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    def _override_scope():
        return scope_holder["current"]

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_actor_scope] = _override_scope
    app.include_router(router, prefix="/api/v1/gateway-approvals")

    yield app, SessionFactory, scope_holder


def _seed_request(db, requester="alice", step="s1"):
    svc = ApprovalService(db)
    req = svc.create_request(
        tenant_id="t1", step_run_id=step, tool_name="file.delete",
        normalized_args_hash="a" * 64, risk_level="high",
        resource_scope={}, policy_digest="p" * 64,
        security_context_digest="sc" * 32,
        requester_principal_id=requester,
    )
    db.commit()
    return req.request_id


class TestGatewayApprovalsAPI:
    def test_list_pending_approvals(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        _seed_request(db)
        db.close()

        client = TestClient(app)
        resp = client.get("/api/v1/gateway-approvals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert data["items"][0]["tool_name"] == "file.delete"

    def test_cast_vote_approve(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        req_id = _seed_request(db, step="s2")
        db.close()

        holder["current"] = holder["bob"]
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/gateway-approvals/{req_id}/vote",
            json={"decision": "approve", "reason": "ok"},
        )
        assert resp.status_code == 200
        assert resp.json()["accepted"] is True

    def test_self_approve_rejected_403(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        req_id = _seed_request(db, step="s3")  # requester = alice
        db.close()

        holder["current"] = holder["alice"]  # alice votes on own request
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/gateway-approvals/{req_id}/vote",
            json={"decision": "approve"},
        )
        assert resp.status_code == 403
        assert "cannot" in resp.json()["detail"].lower()

    def test_resolve_after_quorum(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        req_id = _seed_request(db, step="s4")
        db.close()

        holder["current"] = holder["bob"]
        client = TestClient(app)
        vote_resp = client.post(
            f"/api/v1/gateway-approvals/{req_id}/vote",
            json={"decision": "approve"},
        )
        assert vote_resp.status_code == 200

        resolve_resp = client.post(
            f"/api/v1/gateway-approvals/{req_id}/resolve",
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["status"] == "approved"

    def test_get_nonexistent_returns_404(self, app_and_db):
        app, sf, holder = app_and_db
        client = TestClient(app)
        resp = client.get("/api/v1/gateway-approvals/nonexistent-id")
        assert resp.status_code == 404
