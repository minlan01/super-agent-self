"""Tests for GrantIssuer (P2.2) — opaque handle, digest, consume, revoke."""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import Base, GrantStatusDB
from packages.db.session import Base as AppBase
from packages.policy.grant_issuer import GrantIssuer, IssuedGrant


@pytest.fixture()
def db_session():
    """In-memory SQLite session for isolated testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


class TestGrantIssuer:
    def _issuer(self, db: Session) -> GrantIssuer:
        return GrantIssuer(db)

    def test_issue_returns_opaque_handle_and_persists_digest(self, db_session):
        gi = self._issuer(db_session)
        result = gi.issue(
            tenant_id="t1",
            step_run_id="s1",
            tool_name="file.read",
            bound_args_hash="a" * 64,
            risk_level="low",
            resource_scope={"workspace_id": "w1"},
            security_context_digest="b" * 64,
        )
        assert isinstance(result, IssuedGrant)
        # Handle is opaque (not empty, not a digest)
        assert len(result.handle) > 20
        assert result.handle_digest == gi._digest(result.handle)
        # DB record exists with correct status
        from packages.db.repositories.grant_repo import GrantRepository
        grant = GrantRepository.get_by_handle_digest(db_session, result.handle_digest)
        assert grant is not None
        assert grant.status == GrantStatusDB.ISSUED
        assert grant.max_uses == 1

    def test_verify_valid_handle(self, db_session):
        gi = self._issuer(db_session)
        result = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={}, security_context_digest="b" * 64,
        )
        verified = gi.verify(result.handle)
        assert verified.valid is True
        assert verified.grant_id == result.grant_id

    def test_verify_unknown_handle_fails(self, db_session):
        gi = self._issuer(db_session)
        verified = gi.verify("nonexistent-handle-12345")
        assert verified.valid is False
        assert "not found" in verified.reason

    def test_consume_grant_atomic(self, db_session):
        gi = self._issuer(db_session)
        result = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={}, security_context_digest="b" * 64,
        )
        # First consume wins
        assert gi.consume(result.handle) is True
        # Second consume fails (nonce replay protection)
        assert gi.consume(result.handle) is False
        # Verify now shows consumed
        verified = gi.verify(result.handle)
        assert verified.valid is False
        assert "consumed" in verified.reason

    def test_revoke_grant(self, db_session):
        gi = self._issuer(db_session)
        result = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={}, security_context_digest="b" * 64,
        )
        assert gi.revoke(result.grant_id) is True
        verified = gi.verify(result.handle)
        assert verified.valid is False
        assert "revoked" in verified.reason

    def test_revoke_after_consume_fails(self, db_session):
        gi = self._issuer(db_session)
        result = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={}, security_context_digest="b" * 64,
        )
        gi.consume(result.handle)
        # Cannot revoke a consumed grant
        assert gi.revoke(result.grant_id) is False

    def test_high_risk_requires_approval_resolution(self, db_session):
        gi = self._issuer(db_session)
        with pytest.raises(ValueError, match="approval_resolution_id"):
            gi.issue(
                tenant_id="t1", step_run_id="s1", tool_name="file.delete",
                bound_args_hash="a" * 64, risk_level="high",
                resource_scope={}, security_context_digest="b" * 64,
            )

    def test_high_risk_with_approval_resolution_ok(self, db_session):
        gi = self._issuer(db_session)
        result = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            bound_args_hash="a" * 64, risk_level="high",
            resource_scope={}, security_context_digest="b" * 64,
            approval_resolution_id="approval-res-1",
        )
        assert result.grant_id is not None

    def test_break_glass_exempt_from_approval(self, db_session):
        gi = self._issuer(db_session)
        result = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            bound_args_hash="a" * 64, risk_level="critical",
            resource_scope={}, security_context_digest="b" * 64,
            key_id="break_glass",
        )
        assert result.grant_id is not None

    def test_handle_digest_is_sha256_not_plaintext(self, db_session):
        """DB must never store the plaintext handle."""
        gi = self._issuer(db_session)
        result = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.read",
            bound_args_hash="a" * 64, risk_level="low",
            resource_scope={}, security_context_digest="b" * 64,
        )
        # Query all grant rows and ensure plaintext handle is NOT in any column
        from packages.db.models import CapabilityGrantModel
        grants = db_session.query(CapabilityGrantModel).all()
        assert len(grants) == 1
        for col_val in [grants[0].handle_digest, grants[0].nonce,
                        grants[0].bound_args_hash, grants[0].security_context_digest]:
            assert result.handle not in col_val
