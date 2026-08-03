"""Tests for ApprovalService (P2.6) — request, vote, resolve, anti-self-approve."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.approval.approval_service import (
    ApprovalService,
    DuplicateVoteError,
    SelfApprovalError,
)
from packages.db.models import (
    ApprovalRequestStatus,
    Base,
    VoteDecision,
)
from packages.db.session import Base as AppBase


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    AppBase.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


class TestApprovalService:
    def _svc(self, db: Session) -> ApprovalService:
        return ApprovalService(db)

    def _create_request(self, svc, requester="user-alice"):
        return svc.create_request(
            tenant_id="t1",
            step_run_id="s1",
            tool_name="file.delete",
            normalized_args_hash="a" * 64,
            risk_level="high",
            resource_scope={"workspace_id": "w1"},
            policy_digest="p" * 64,
            security_context_digest="sc" * 32,
            requester_principal_id=requester,
        )

    def test_create_request_pending(self, db_session):
        svc = self._svc(db_session)
        result = self._create_request(svc)
        assert result.status == ApprovalRequestStatus.PENDING
        assert result.request_id is not None

    def test_self_approve_rejected(self, db_session):
        """Requester cannot vote on their own request."""
        svc = self._svc(db_session)
        req = self._create_request(svc, requester="alice")
        with pytest.raises(SelfApprovalError):
            svc.cast_vote(
                request_id=req.request_id,
                voter_principal_id="alice",  # same as requester!
                decision=VoteDecision.APPROVE,
            )

    def test_different_user_can_vote(self, db_session):
        svc = self._svc(db_session)
        req = self._create_request(svc, requester="alice")
        vote = svc.cast_vote(
            request_id=req.request_id,
            voter_principal_id="bob",  # different from requester
            decision=VoteDecision.APPROVE,
        )
        assert vote.accepted is True

    def test_duplicate_vote_rejected(self, db_session):
        svc = self._svc(db_session)
        req = self._create_request(svc, requester="alice")
        svc.cast_vote(
            request_id=req.request_id,
            voter_principal_id="bob",
            decision=VoteDecision.APPROVE,
        )
        with pytest.raises(DuplicateVoteError):
            svc.cast_vote(
                request_id=req.request_id,
                voter_principal_id="bob",
                decision=VoteDecision.APPROVE,
            )

    def test_quorum_approve_resolves_approved(self, db_session):
        svc = self._svc(db_session)
        req = self._create_request(svc, requester="alice")
        svc.cast_vote(
            request_id=req.request_id,
            voter_principal_id="bob",
            decision=VoteDecision.APPROVE,
        )
        result = svc.resolve(req.request_id)
        assert result.status == ApprovalRequestStatus.APPROVED
        assert result.resolution_id is not None

    def test_quorum_reject_resolves_rejected(self, db_session):
        svc = self._svc(db_session)
        req = self._create_request(svc, requester="alice")
        svc.cast_vote(
            request_id=req.request_id,
            voter_principal_id="bob",
            decision=VoteDecision.REJECT,
        )
        result = svc.resolve(req.request_id)
        assert result.status == ApprovalRequestStatus.REJECTED
        assert result.resolution_id is None

    def test_quorum_not_reached_stays_pending(self, db_session):
        svc = self._svc(db_session)
        req = self._create_request(svc, requester="alice")
        # No votes cast yet
        result = svc.resolve(req.request_id)
        assert result.status == ApprovalRequestStatus.PENDING

    def test_higher_quorum_requires_multiple_votes(self, db_session):
        svc = self._svc(db_session)
        req = svc.create_request(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            normalized_args_hash="a" * 64, risk_level="critical",
            resource_scope={}, policy_digest="p" * 64,
            security_context_digest="sc" * 32,
            requester_principal_id="alice",
            required_quorum=2,
        )
        # One vote not enough
        svc.cast_vote(request_id=req.request_id, voter_principal_id="bob",
                      decision=VoteDecision.APPROVE)
        r1 = svc.resolve(req.request_id)
        assert r1.status == ApprovalRequestStatus.PENDING

        # Second vote reaches quorum
        svc.cast_vote(request_id=req.request_id, voter_principal_id="carol",
                      decision=VoteDecision.APPROVE)
        r2 = svc.resolve(req.request_id)
        assert r2.status == ApprovalRequestStatus.APPROVED

    def test_invalidate_if_stale_content_changed(self, db_session):
        """If policy/args/security digest changed, old request is invalidated."""
        svc = self._svc(db_session)
        req = self._create_request(svc)
        # Content unchanged -> not invalidated
        assert svc.invalidate_if_stale(
            request_id=req.request_id,
            current_policy_digest="p" * 64,
            current_security_digest="sc" * 32,
            current_args_hash="a" * 64,
        ) is False

        # Policy changed -> invalidated
        assert svc.invalidate_if_stale(
            request_id=req.request_id,
            current_policy_digest="DIFFERENT",
            current_security_digest="sc" * 32,
            current_args_hash="a" * 64,
        ) is True

        # Now status is INVALIDATED
        req2 = svc.get_request(req.request_id)
        assert req2.status == ApprovalRequestStatus.INVALIDATED

    def test_vote_on_expired_request_rejected(self, db_session):
        from datetime import timedelta
        svc = self._svc(db_session)
        req = svc.create_request(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            normalized_args_hash="a" * 64, risk_level="high",
            resource_scope={}, policy_digest="p" * 64,
            security_context_digest="sc" * 32,
            requester_principal_id="alice",
            ttl=timedelta(seconds=0),
        )
        # Manually expire it
        from packages.db.repositories.approval_request_repo import ApprovalRequestRepository
        from datetime import datetime, UTC
        ar = ApprovalRequestRepository.get_by_id(db_session, req.request_id)
        ar.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        db_session.flush()

        vote = svc.cast_vote(
            request_id=req.request_id,
            voter_principal_id="bob",
            decision=VoteDecision.APPROVE,
        )
        assert vote.accepted is False
        assert "expired" in vote.reason.lower()

    def test_approved_request_triggers_grant_binding(self, db_session):
        """After APPROVED, the resolution_id can be passed to GrantIssuer.

        This test verifies the wiring: resolution_id is non-null and can
        be used as approval_resolution_id in GrantIssuer.issue().
        """
        from packages.policy.grant_issuer import GrantIssuer
        svc = self._svc(db_session)
        req = self._create_request(svc, requester="alice")

        # Approver votes
        svc.cast_vote(
            request_id=req.request_id,
            voter_principal_id="bob",
            decision=VoteDecision.APPROVE,
        )
        resolution = svc.resolve(req.request_id)
        assert resolution.status == ApprovalRequestStatus.APPROVED

        # GrantIssuer can issue a high-risk grant bound to this resolution
        gi = GrantIssuer(db_session)
        grant = gi.issue(
            tenant_id="t1", step_run_id="s1", tool_name="file.delete",
            bound_args_hash="a" * 64, risk_level="high",
            resource_scope={}, security_context_digest="sc" * 32,
            approval_resolution_id=resolution.resolution_id,
        )
        assert grant.grant_id is not None
