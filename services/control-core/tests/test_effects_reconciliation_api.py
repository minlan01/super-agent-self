"""Tests for the effect reconciliation API (P2.6 backend queue)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from packages.auth.actor_scope import ActorScope
from packages.db.models import (
    Base,
    EffectClassDB,
    EffectStatusDB,
)
from packages.db.session import Base as AppBase


@pytest.fixture()
def app_and_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    SF = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    from apps.api_server.dependencies import get_current_actor_scope, get_db
    from apps.api_server.routes.effects import router

    scope = ActorScope(
        tenant_id="t1", principal_id="op-1", workspace_id="w1",
        roles=["admin"], permissions=[], auth_method="test",
        device_id="d", os_session_id="s",
    )

    def _db():
        s = SF()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_actor_scope] = lambda: scope
    app.include_router(router, prefix="/api/v1/effects")
    return app, SF


def _make_unknown_effect(db, step="s-1"):
    """Seed a grant + lease + effect driven to UNKNOWN_OUTCOME."""
    from datetime import UTC, datetime, timedelta

    from packages.db.models import CapabilityGrantModel, LeaseModel
    from packages.db.repositories.effect_repo import EffectRepository
    now = datetime.now(UTC)
    grant = CapabilityGrantModel(
        tenant_id="t1", step_run_id=step, handle_digest="h" * 64,
        nonce="n" * 16, bound_args_hash="a" * 64, risk_level="high",
        resource_scope={}, security_context_digest="sc" * 32,
        status="issued", issued_at=now,
        expires_at=now + timedelta(hours=1), max_uses=1,
    )
    lease = LeaseModel(
        tenant_id="t1", worker_id="w-1", step_run_id=step,
        fencing_token=1, status="active",
        expires_at=now + timedelta(hours=1),
    )
    db.add_all([grant, lease])
    db.flush()
    return EffectRepository.create(
        db,
        tenant_id="t1", step_run_id=step, grant_id=grant.id, lease_id=lease.id,
        fencing_token=1, status=EffectStatusDB.UNKNOWN_OUTCOME,
        effect_class=EffectClassDB.NON_RETRYABLE, tool_name="file.delete",
        security_context_digest="sc" * 32, created_at=now,
    )


class TestEffectReconciliationAPI:
    def test_queue_lists_unknown_outcomes(self, app_and_db):
        app, SF = app_and_db
        db = SF()
        _make_unknown_effect(db)
        db.commit()
        db.close()

        resp = TestClient(app).get("/api/v1/effects/unknown-outcomes")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["tool_name"] == "file.delete"
        assert body["items"][0]["status"] == "unknown_outcome"

    def test_detail_includes_dispatch_history(self, app_and_db):
        app, SF = app_and_db
        db = SF()
        effect = _make_unknown_effect(db, step="s-2")
        eid = effect.id
        lease_id = effect.lease_id
        from packages.db.repositories.dispatch_repo import DispatchAttemptRepository
        DispatchAttemptRepository.create(
            db, tenant_id="t1", effect_id=eid, attempt_ordinal=1,
            lease_id=lease_id, fencing_token=1, grant_digest="h" * 64,
            worker_id="w-1", adapter_name="FileAdapter",
        )
        db.commit()
        db.close()

        resp = TestClient(app).get(f"/api/v1/effects/{eid}")
        assert resp.status_code == 200
        assert len(resp.json()["dispatch_history"]) == 1

    def test_reconcile_to_confirmed(self, app_and_db):
        app, SF = app_and_db
        db = SF()
        effect = _make_unknown_effect(db, step="s-3")
        eid = effect.id
        db.commit()
        db.close()

        resp = TestClient(app).post(
            f"/api/v1/effects/{eid}/reconcile",
            json={"final_status": "confirmed", "note": "verified file deleted"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

    def test_reconcile_invalid_target_rejected(self, app_and_db):
        app, SF = app_and_db
        db = SF()
        effect = _make_unknown_effect(db, step="s-4")
        eid = effect.id
        db.commit()
        db.close()

        resp = TestClient(app).post(
            f"/api/v1/effects/{eid}/reconcile",
            json={"final_status": "prepared"},  # not a reconcile target
        )
        assert resp.status_code == 422

    def test_reconcile_non_unknown_conflict(self, app_and_db):
        """Reconciling an already-CONFIRMED effect → 409 (immutable terminal)."""
        app, SF = app_and_db
        db = SF()
        effect = _make_unknown_effect(db, step="s-5")
        eid = effect.id
        from packages.db.repositories.effect_repo import EffectRepository
        EffectRepository.update_status(db, eid, EffectStatusDB.CONFIRMED)
        db.commit()
        db.close()

        resp = TestClient(app).post(
            f"/api/v1/effects/{eid}/reconcile",
            json={"final_status": "confirmed"},
        )
        assert resp.status_code == 409

    def test_reconcile_audit_logged(self, app_and_db):
        app, SF = app_and_db
        db = SF()
        effect = _make_unknown_effect(db, step="s-6")
        eid = effect.id
        db.commit()
        db.close()

        TestClient(app).post(
            f"/api/v1/effects/{eid}/reconcile",
            json={"final_status": "failed", "note": "verified no delete"},
        )

        db2 = SF()
        from sqlalchemy import select
        from packages.db.models import AuditEvent
        rows = list(db2.scalars(select(AuditEvent)).all())
        db2.close()
        reconciled = [r for r in rows if (r.detail or {}).get("action") == "effect_reconciled"]
        assert len(reconciled) >= 1
        assert reconciled[0].actor == "op-1"
        assert reconciled[0].entry_hash  # chained

    def test_nonexistent_effect_404(self, app_and_db):
        app, _ = app_and_db
        resp = TestClient(app).get("/api/v1/effects/nope")
        assert resp.status_code == 404
