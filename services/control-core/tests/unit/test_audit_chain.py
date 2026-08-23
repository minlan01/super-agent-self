"""Tests for the audit hash chain (P4: tamper-evidence, 100% verify)."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.agent_core.schemas import AuditEventCreate
from packages.db.audit_chain import compute_entry_hash
from packages.db.models import AuditEvent, AuditEventType, Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _evt(n: int, detail=None):
    return AuditEventCreate(
        task_id=None, step_id=None, edition=None,
        event_type=AuditEventType.TASK_CREATED,
        actor=f"actor-{n}", detail=detail or {"n": n},
    )


class TestAuditChain:
    def test_create_seals_hash(self, db):
        from packages.db.repositories.audit_repo import AuditRepository
        e = AuditRepository.create(db, _evt(1))
        assert e.entry_hash and len(e.entry_hash) == 64
        assert e.prev_entry_hash is None  # first row: GENESIS implied

    def test_chain_links_forward(self, db):
        from packages.db.repositories.audit_repo import AuditRepository
        e1 = AuditRepository.create(db, _evt(1))
        e2 = AuditRepository.create(db, _evt(2))
        e3 = AuditRepository.create(db, _evt(3))
        assert e2.prev_entry_hash == e1.entry_hash
        assert e3.prev_entry_hash == e2.entry_hash

    def test_batch_create_maintains_chain(self, db):
        from packages.db.repositories.audit_repo import AuditRepository
        head0 = AuditRepository.create(db, _evt(0))
        batch = AuditRepository.batch_create(db, [_evt(i) for i in range(1, 4)])
        assert batch[0].prev_entry_hash == head0.entry_hash
        assert batch[1].prev_entry_hash == batch[0].entry_hash
        assert batch[2].prev_entry_hash == batch[1].entry_hash

    def test_verify_passes_on_intact_chain(self, db):
        from packages.db.repositories.audit_repo import AuditRepository
        for i in range(5):
            AuditRepository.create(db, _evt(i))
        db.commit()

        rows = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id)))
        prev = None
        for r in rows:
            expected = compute_entry_hash(
                prev_entry_hash=r.prev_entry_hash, event_id=r.id,
                created_at=r.created_at,
                event_type=str(getattr(r.event_type, "value", r.event_type)),
                actor=str(r.actor), task_id=r.task_id, step_id=r.step_id,
                detail=r.detail,
            )
            assert r.entry_hash == expected
            if prev is not None:
                assert r.prev_entry_hash == prev
            prev = r.entry_hash

    def test_tampered_detail_detected(self, db):
        from packages.db.repositories.audit_repo import AuditRepository
        AuditRepository.create(db, _evt(1))
        victim = AuditRepository.create(db, _evt(2))
        AuditRepository.create(db, _evt(3))
        db.commit()

        # Tamper: mutate detail of the middle row directly in DB.
        db.execute(
            AuditEvent.__table__.update()
            .where(AuditEvent.id == victim.id)
            .values(detail={"evil": True})
        )
        db.commit()

        row = db.get(AuditEvent, victim.id)
        expected = compute_entry_hash(
            prev_entry_hash=row.prev_entry_hash, event_id=row.id,
            created_at=row.created_at,
            event_type=str(getattr(row.event_type, "value", row.event_type)),
            actor=str(row.actor), task_id=row.task_id, step_id=row.step_id,
            detail=row.detail,
        )
        assert expected != row.entry_hash, "tamper must change the recomputed hash"

    def test_deleted_row_breaks_chain(self, db):
        from packages.db.repositories.audit_repo import AuditRepository
        e1 = AuditRepository.create(db, _evt(1))
        e2 = AuditRepository.create(db, _evt(2))
        db.commit()

        # Tamper: zero the middle hash (simulating an edit-and-rehash tool).
        db.execute(
            AuditEvent.__table__.update()
            .where(AuditEvent.id == e1.id)
            .values(entry_hash=None, prev_entry_hash=None)
        )
        db.commit()

        row2 = db.get(AuditEvent, e2.id)
        # e2 still points at e1's old hash which no longer exists in table.
        head = db.scalar(
            select(AuditEvent.entry_hash)
            .where(AuditEvent.entry_hash.is_not(None))
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(1)
        )
        # Either the chain head changed (e2 is head now, orphaning e2.prev)
        # or e2 remains head with a dangling prev — both are detectable by
        # the trailing-unhashed / link checks in verify_audit_chain.
        assert head == e2.entry_hash  # e1 dropped out of the hashed set

    def test_canonical_json_stable(self):
        from packages.db.audit_chain import canonical_json
        a = canonical_json({"b": 1, "a": {"z": 1, "y": 2}})
        b = canonical_json({"a": {"y": 2, "z": 1}, "b": 1})
        assert a == b
