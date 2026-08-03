"""Tests for LeaseManager (P2.3) — fencing token monotonicity, renew, release."""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import Base, LeaseStatus
from packages.db.session import Base as AppBase
from packages.execution.lease_manager import LeaseConflictError, LeaseManager


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


class TestLeaseManager:
    def _mgr(self, db: Session) -> LeaseManager:
        return LeaseManager(db)

    def test_acquire_returns_monotonic_fencing_token(self, db_session):
        """fencing_token must be strictly monotonic per worker+step."""
        mgr = self._mgr(db_session)

        # First acquisition
        l1 = mgr.acquire(
            tenant_id="t1", worker_id="w1", step_run_id="s1",
        )
        assert l1.fencing_token == 1
        mgr.release(l1.lease_id)

        # Second acquisition for same worker+step -> token must be 2
        l2 = mgr.acquire(
            tenant_id="t1", worker_id="w1", step_run_id="s1",
        )
        assert l2.fencing_token == 2
        assert l2.fencing_token > l1.fencing_token

    def test_different_workers_independent_tokens(self, db_session):
        mgr = self._mgr(db_session)
        l1 = mgr.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        l2 = mgr.acquire(tenant_id="t1", worker_id="w2", step_run_id="s2")
        # Each worker starts at token 1 for their own step
        assert l1.fencing_token == 1
        assert l2.fencing_token == 1

    def test_active_lease_blocks_other_worker(self, db_session):
        mgr = self._mgr(db_session)
        mgr.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        # Worker 2 cannot steal worker 1's lease
        with pytest.raises(LeaseConflictError):
            mgr.acquire(tenant_id="t1", worker_id="w2", step_run_id="s1")

    def test_same_worker_reacquire_extends(self, db_session):
        mgr = self._mgr(db_session)
        l1 = mgr.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        original_token = l1.fencing_token
        # Same worker re-acquires -> extends, keeps same token
        l2 = mgr.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        assert l2.lease_id == l1.lease_id
        assert l2.fencing_token == original_token

    def test_release_lease(self, db_session):
        mgr = self._mgr(db_session)
        l = mgr.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        assert mgr.is_valid(l.lease_id, l.fencing_token) is True
        mgr.release(l.lease_id)
        assert mgr.is_valid(l.lease_id, l.fencing_token) is False

    def test_stale_fencing_token_invalid(self, db_session):
        """Old fencing token must be rejected even if lease is active."""
        mgr = self._mgr(db_session)
        l = mgr.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        assert l.fencing_token == 1
        mgr.release(l.lease_id)

        # Re-acquire -> token becomes 2
        l2 = mgr.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        assert l2.fencing_token == 2

        # Old token 1 on the new lease -> invalid
        assert mgr.is_valid(l2.lease_id, 1) is False
        # Current token 2 -> valid
        assert mgr.is_valid(l2.lease_id, 2) is True

    def test_heartbeat_extends_lease(self, db_session):
        mgr = self._mgr(db_session)
        l = mgr.acquire(
            tenant_id="t1", worker_id="w1", step_run_id="s1",
            ttl=timedelta(seconds=1),
        )
        # Before expiry
        assert mgr.heartbeat(l.lease_id) is True

    def test_heartbeat_expired_lease_fails(self, db_session):
        mgr = self._mgr(db_session)
        l = mgr.acquire(
            tenant_id="t1", worker_id="w1", step_run_id="s1",
            ttl=timedelta(seconds=1),
        )
        # Manually expire the lease by setting expires_at to the past.
        from packages.db.repositories.lease_repo import LeaseRepository
        from datetime import datetime, UTC
        lease = LeaseRepository.get_by_id(db_session, l.lease_id)
        lease.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        db_session.flush()
        # Expired lease -> heartbeat fails
        assert mgr.heartbeat(l.lease_id) is False
        assert mgr.is_valid(l.lease_id, l.fencing_token) is False

    def test_expire_stale_marks_expired(self, db_session):
        mgr = self._mgr(db_session)
        l = mgr.acquire(
            tenant_id="t1", worker_id="w1", step_run_id="s1",
            ttl=timedelta(seconds=1),
        )
        # Manually set expires_at to the past.
        from packages.db.repositories.lease_repo import LeaseRepository
        from datetime import datetime, UTC
        lease = LeaseRepository.get_by_id(db_session, l.lease_id)
        lease.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        db_session.flush()
        count = mgr.expire_stale()
        assert count >= 1
        assert mgr.is_valid(l.lease_id, l.fencing_token) is False

    def test_is_valid_wrong_token_fails(self, db_session):
        """Even an active lease with a wrong token must fail."""
        mgr = self._mgr(db_session)
        l = mgr.acquire(tenant_id="t1", worker_id="w1", step_run_id="s1")
        assert l.fencing_token == 1
        # Wrong token
        assert mgr.is_valid(l.lease_id, 999) is False
