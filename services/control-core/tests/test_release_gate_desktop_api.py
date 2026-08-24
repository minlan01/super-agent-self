"""Release-gate tests for desktop acceptance capabilities (GA-1.2).

Covers the manual's mandatory acceptance surface:
  - 参数脱敏: task detail + approval snapshot redact credential material
  - 租户隔离: cross-tenant task/approval/effect access returns 404
  - 自批准 403: requester cannot vote on own request (HTTP level)
  - 重复投票 409: second vote by the same principal is rejected (HTTP level)
  - Effect 终态不可逆: re-reconcile returns 409; detail exposes
    before_hash/after_hash + dispatch history for the desktop view.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from packages.approval.approval_service import ApprovalService
from packages.auth.actor_scope import ActorScope
from packages.db.models import (
    Base,
    CapabilityGrantModel,
    Edition,
    EffectClassDB,
    EffectStatusDB,
    LeaseModel,
    RiskLevel,
    StepStatus,
    Task,
    TaskStatus,
    TaskStep,
)
from packages.db.session import Base as AppBase

from packages.security.args_sanitizer import sanitize_args

SECRET_ARGS = {
    "path": "C:/data/report.txt",
    "password": "hunter2-secret",
    "api_key": "ak-plaintext-123",
    "nested": {"db_password": "nested-secret", "keep": "visible"},
    "items": [{"access_token": "tok-1"}, {"name": "file.txt"}],
    "secret_ref": {"key_id": "k1", "label": "cred"},
    "author": "alice",
}


@pytest.fixture()
def app_and_db():
    """Bare app with tasks + gateway-approvals + effects routers wired."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    alice = ActorScope(
        tenant_id="t1", principal_id="alice", workspace_id="w1",
        roles=["user"], permissions=[], auth_method="test",
        device_id="d1", os_session_id="s1",
    )
    bob = ActorScope(
        tenant_id="t1", principal_id="bob", workspace_id="w1",
        roles=["user"], permissions=[], auth_method="test",
        device_id="d2", os_session_id="s2",
    )
    mallory = ActorScope(
        tenant_id="t2", principal_id="mallory", workspace_id="w2",
        roles=["user"], permissions=[], auth_method="test",
        device_id="d3", os_session_id="s3",
    )
    holder = {"current": alice, "alice": alice, "bob": bob, "mallory": mallory}

    from apps.api_server.dependencies import get_current_actor_scope, get_db
    from apps.api_server.routes import effects as effects_route
    from apps.api_server.routes import gateway_approvals as approvals_route
    from apps.api_server.routes import tasks as tasks_route

    def _override_db():
        db = SessionFactory()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_actor_scope] = lambda: holder["current"]
    # The tasks router carries a router-level require_permission dependency
    # created at import time — neutralize the exact instance for unit tests.
    for dep in tasks_route.router.dependencies:
        app.dependency_overrides[dep.dependency] = lambda: None
    app.include_router(tasks_route.router, prefix="/api/v1/tasks")
    app.include_router(approvals_route.router, prefix="/api/v1/gateway-approvals")
    app.include_router(effects_route.router, prefix="/api/v1/effects")

    yield app, SessionFactory, holder


def _seed_task_with_secret_step(db, tenant_id="t1"):
    task = Task(
        tenant_id=tenant_id, user_id="alice", edition=Edition.ENTERPRISE,
        goal="file.read acceptance", status=TaskStatus.PENDING,
        risk_level=RiskLevel.HIGH,
    )
    db.add(task)
    db.flush()
    step = TaskStep(
        tenant_id=tenant_id, task_id=task.id, step_order=0,
        tool_name="file.read", args=SECRET_ARGS,
        risk_level=RiskLevel.HIGH, requires_approval=False,
        status=StepStatus.PENDING,
    )
    db.add(step)
    db.commit()
    return task.id, step.id


def _seed_approval(db, step_id, requester="alice"):
    svc = ApprovalService(db)
    req = svc.create_request(
        tenant_id="t1", step_run_id=step_id, tool_name="file.delete",
        normalized_args_hash="a" * 64, risk_level="high",
        resource_scope={}, policy_digest="p" * 64,
        security_context_digest="sc" * 32,
        requester_principal_id=requester,
    )
    db.commit()
    return req.request_id


def _make_unknown_effect(db, step="s-1", tenant_id="t1"):
    from datetime import UTC, datetime, timedelta

    from packages.db.repositories.effect_repo import EffectRepository
    now = datetime.now(UTC)
    grant = CapabilityGrantModel(
        tenant_id=tenant_id, step_run_id=step, handle_digest="h" * 64,
        nonce="n" * 16, bound_args_hash="a" * 64, risk_level="high",
        resource_scope={}, security_context_digest="sc" * 32,
        status="issued", issued_at=now,
        expires_at=now + timedelta(hours=1), max_uses=1,
    )
    lease = LeaseModel(
        tenant_id=tenant_id, worker_id="w-1", step_run_id=step,
        fencing_token=1, status="active",
        expires_at=now + timedelta(hours=1),
    )
    db.add_all([grant, lease])
    db.flush()
    effect = EffectRepository.create(
        db,
        tenant_id=tenant_id, step_run_id=step, grant_id=grant.id,
        lease_id=lease.id, fencing_token=1,
        status=EffectStatusDB.UNKNOWN_OUTCOME,
        effect_class=EffectClassDB.NON_RETRYABLE, tool_name="file.delete",
        security_context_digest="sc" * 32, created_at=now,
    )
    EffectRepository.set_hashes(
        db, effect_id=effect.id, before_hash="b" * 64, after_hash=None,
    )
    db.commit()
    return effect.id


class TestSanitizeArgsUnit:
    def test_redacts_sensitive_keys_recursively(self):
        result = sanitize_args(SECRET_ARGS)
        assert result["path"] == "C:/data/report.txt"
        assert result["password"] == "***REDACTED***"
        assert result["api_key"] == "***REDACTED***"
        assert result["nested"]["db_password"] == "***REDACTED***"
        assert result["nested"]["keep"] == "visible"
        assert result["items"][0]["access_token"] == "***REDACTED***"
        assert result["items"][1]["name"] == "file.txt"

    def test_secret_ref_value_never_returned(self):
        result = sanitize_args(SECRET_ARGS)
        assert result["secret_ref"] == "***REDACTED***"

    def test_exact_only_stem_not_overredacted(self):
        result = sanitize_args({"author": "alice", "auth": "Basic xyz"})
        assert result["author"] == "alice"
        assert result["auth"] == "***REDACTED***"


class TestTaskDetailView:
    def test_task_detail_sanitizes_step_args(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        task_id, _ = _seed_task_with_secret_step(db)
        db.close()

        resp = TestClient(app).get(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.text
        assert "hunter2-secret" not in body
        assert "ak-plaintext-123" not in body
        assert "nested-secret" not in body
        assert "tok-1" not in body
        step = resp.json()["data"]["steps"][0]
        assert step["args"]["password"] == "***REDACTED***"
        assert step["args"]["path"] == "C:/data/report.txt"
        assert step["tool_name"] == "file.read"
        assert step["risk_level"] == "high"
        assert step["status"] == "pending"

    def test_task_detail_cross_tenant_404(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        task_id, _ = _seed_task_with_secret_step(db)
        db.close()

        holder["current"] = holder["mallory"]
        resp = TestClient(app).get(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 404


class TestApprovalSanitizedSnapshot:
    def test_list_includes_sanitized_args(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        _, step_id = _seed_task_with_secret_step(db)
        req_id = _seed_approval(db, step_id)
        db.close()

        resp = TestClient(app).get("/api/v1/gateway-approvals?status=pending")
        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["id"] == req_id)
        assert item["sanitized_args"]["password"] == "***REDACTED***"
        assert item["sanitized_args"]["path"] == "C:/data/report.txt"
        assert "hunter2-secret" not in resp.text
        # Manual: approval UI fields — tool/risk/requester/quorum.
        assert item["tool_name"] == "file.delete"
        assert item["risk_level"] == "high"
        assert item["requester_principal_id"] == "alice"
        assert item["required_quorum"] >= 1

    def test_detail_includes_sanitized_args_and_votes(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        _, step_id = _seed_task_with_secret_step(db)
        req_id = _seed_approval(db, step_id)
        db.close()

        resp = TestClient(app).get(f"/api/v1/gateway-approvals/{req_id}")
        assert resp.status_code == 200
        assert resp.json()["sanitized_args"]["api_key"] == "***REDACTED***"
        assert resp.json()["votes"] == []

    def test_approval_cross_tenant_404(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        _, step_id = _seed_task_with_secret_step(db)
        req_id = _seed_approval(db, step_id)
        db.close()

        holder["current"] = holder["mallory"]
        resp = TestClient(app).get(f"/api/v1/gateway-approvals/{req_id}")
        assert resp.status_code == 404


class TestApprovalVoting:
    def test_self_approval_403(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        _, step_id = _seed_task_with_secret_step(db)
        req_id = _seed_approval(db, step_id, requester="alice")
        db.close()

        holder["current"] = holder["alice"]
        resp = TestClient(app).post(
            f"/api/v1/gateway-approvals/{req_id}/vote",
            json={"decision": "approve"},
        )
        assert resp.status_code == 403

    def test_duplicate_vote_409(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        _, step_id = _seed_task_with_secret_step(db)
        req_id = _seed_approval(db, step_id, requester="alice")
        db.close()

        holder["current"] = holder["bob"]
        client = TestClient(app)
        first = client.post(
            f"/api/v1/gateway-approvals/{req_id}/vote",
            json={"decision": "approve"},
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/gateway-approvals/{req_id}/vote",
            json={"decision": "approve"},
        )
        assert second.status_code == 409


class TestEffectViewAndReconcile:
    def test_detail_includes_hashes_and_history(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        effect_id = _make_unknown_effect(db)
        db.close()

        resp = TestClient(app).get(f"/api/v1/effects/{effect_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["before_hash"] == "b" * 64
        assert data["after_hash"] is None
        assert data["status"] == "unknown_outcome"
        assert isinstance(data["dispatch_history"], list)

    def test_reconcile_then_terminal_409(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        effect_id = _make_unknown_effect(db, step="s-2")
        db.close()

        client = TestClient(app)
        first = client.post(
            f"/api/v1/effects/{effect_id}/reconcile",
            json={"final_status": "confirmed"},
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/effects/{effect_id}/reconcile",
            json={"final_status": "failed"},
        )
        assert second.status_code == 409

    def test_effect_cross_tenant_404(self, app_and_db):
        app, sf, holder = app_and_db
        db = sf()
        effect_id = _make_unknown_effect(db)
        db.close()

        holder["current"] = holder["mallory"]
        resp = TestClient(app).get(f"/api/v1/effects/{effect_id}")
        assert resp.status_code == 404


class TestFixtureToolGuard:
    def test_refuses_real_localappdata_zcode(self):
        import importlib.util
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        script = Path(__file__).resolve().parent.parent / "scripts" / "seed_unknown_outcome.py"
        spec = importlib.util.spec_from_file_location("seed_unknown_outcome", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # NOTE: no pytest tmp_path here — a stale locked basetemp dir in this
        # workspace breaks that fixture; use tempfile directly instead.
        with tempfile.TemporaryDirectory() as tmp:
            fake_local = Path(tmp) / "localappdata"
            (fake_local / "zcode").mkdir(parents=True)
            with patch.dict(os.environ, {"LOCALAPPDATA": str(fake_local)}):
                with pytest.raises(SystemExit, match="REFUSED"):
                    mod.ensure_not_real_data_dir(
                        (fake_local / "zcode" / "agent_platform.db").resolve()
                    )
                # A disposable path outside the real data dir is accepted.
                mod.ensure_not_real_data_dir(
                    (Path(tmp) / "fixture" / "test.db").resolve()
                )
