"""ApprovalService — high-risk step gating with quorum + anti-self-approve.

Spec §4.3 + PROJECT-CONTEXT §授权与审批不变量:
  - Approval identity comes from server-side ActorScope, not client claims.
  - Requester cannot self-approve (even if quorum=1).
  - ApprovalRequest is bound to plan/resource/policy_digest/security_digest.
  - Key content change after request invalidates the old resolution.
  - On APPROVED: persist a unique resume command (not a generic resume API).
  - GrantIssuer issues a Grant bound to the resolution_id.

Flow:
  PolicyDecision.WAIT_APPROVAL
    -> create_request (bound to step/tool/args/policy/security digests)
    -> vote (approver from ActorScope, self-approve rejected)
    -> resolve (quorum reached: APPROVED or REJECTED)
    -> if APPROVED: issue Grant (approval_resolution_id = request.id)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session

from packages.db.models import (
    ApprovalRequestStatus,
    VoteDecision,
)
from packages.db.repositories.approval_request_repo import (
    ApprovalRequestRepository,
    ApprovalVoteRepository,
)

logger = structlog.get_logger()

_DEFAULT_REQUEST_TTL = timedelta(hours=24)  # approval requests expire in 24h


@dataclass(frozen=True)
class ApprovalRequestResult:
    """Result of create_request()."""
    request_id: str
    step_run_id: str
    status: ApprovalRequestStatus
    expires_at: datetime


@dataclass(frozen=True)
class VoteResult:
    """Result of cast_vote()."""
    vote_id: str
    request_id: str
    decision: VoteDecision
    accepted: bool
    reason: str = ""


@dataclass(frozen=True)
class ResolutionResult:
    """Result of resolve()."""
    request_id: str
    status: ApprovalRequestStatus
    resolution_id: str | None
    reason: str = ""


class SelfApprovalError(Exception):
    """Raised when the requester tries to approve their own request."""


class DuplicateVoteError(Exception):
    """Raised when a voter tries to vote twice on the same request."""


class ApprovalRequestExpired(Exception):
    """Raised when operating on an expired request."""


class ApprovalService:
    """Manages high-risk step approval lifecycle.

    Does NOT issue grants directly (that's GrantIssuer's job).  Instead,
    resolve() returns a ResolutionResult that the executor uses to call
    GrantIssuer.issue(approval_resolution_id=...).

    This separation keeps ApprovalService as a pure decision service.
    """

    def __init__(self, db: Session):
        self.db = db

    def create_request(
        self,
        *,
        tenant_id: str,
        step_run_id: str,
        tool_name: str,
        normalized_args_hash: str,
        risk_level: str,
        resource_scope: dict[str, Any],
        policy_digest: str,
        security_context_digest: str,
        requester_principal_id: str,
        requester_workspace_id: str | None = None,
        required_quorum: int = 1,
        ttl: timedelta | None = None,
    ) -> ApprovalRequestResult:
        """Create a new approval request for a high-risk step.

        The request is bound to the exact policy/args/security context at
        creation time.  If any of these change before resolution, the old
        request should be invalidated (see invalidate_if_stale()).
        """
        expires_at = datetime.now(UTC) + (ttl or _DEFAULT_REQUEST_TTL)

        req = ApprovalRequestRepository.create(
            self.db,
            tenant_id=tenant_id,
            step_run_id=step_run_id,
            tool_name=tool_name,
            normalized_args_hash=normalized_args_hash,
            risk_level=risk_level,
            resource_scope=resource_scope,
            policy_digest=policy_digest,
            security_context_digest=security_context_digest,
            requester_principal_id=requester_principal_id,
            requester_workspace_id=requester_workspace_id,
            status=ApprovalRequestStatus.PENDING,
            required_quorum=required_quorum,
            expires_at=expires_at,
            created_at=datetime.now(UTC),
        )

        logger.info(
            "ApprovalRequest created: request=%s step=%s tool=%s risk=%s requester=%s",
            req.id, step_run_id, tool_name, risk_level, requester_principal_id,
        )

        return ApprovalRequestResult(
            request_id=req.id,
            step_run_id=step_run_id,
            status=ApprovalRequestStatus.PENDING,
            expires_at=expires_at,
        )

    def cast_vote(
        self,
        *,
        request_id: str,
        voter_principal_id: str,
        decision: VoteDecision,
        reason: str | None = None,
    ) -> VoteResult:
        """Cast a vote on an approval request.

        Enforces:
          - Requester cannot self-approve (SelfApprovalError).
          - Each voter can only vote once (DuplicateVoteError).
          - Request must be PENDING and not expired.
        """
        req = ApprovalRequestRepository.get_by_id(self.db, request_id)
        if req is None:
            return VoteResult(
                vote_id="", request_id=request_id,
                decision=decision, accepted=False,
                reason="approval request not found",
            )

        # Check expiry.
        now = datetime.now(UTC)
        expires = req.expires_at
        if expires.tzinfo is None:
            now = now.replace(tzinfo=None)
        if req.status != ApprovalRequestStatus.PENDING or expires <= now:
            if req.status == ApprovalRequestStatus.PENDING:
                ApprovalRequestRepository.update_status(
                    self.db, request_id, ApprovalRequestStatus.EXPIRED,
                )
            return VoteResult(
                vote_id="", request_id=request_id,
                decision=decision, accepted=False,
                reason=f"request is {req.status.value} or expired",
            )

        # Anti-self-approve: requester cannot vote on their own request.
        if req.requester_principal_id == voter_principal_id:
            raise SelfApprovalError(
                f"principal {voter_principal_id} cannot approve their own request "
                f"(requester == voter is forbidden, even with quorum=1)"
            )

        # Check for duplicate vote.
        existing = ApprovalVoteRepository.get_by_request_and_voter(
            self.db, request_id=request_id,
            voter_principal_id=voter_principal_id,
        )
        if existing is not None:
            raise DuplicateVoteError(
                f"principal {voter_principal_id} already voted on request {request_id}"
            )

        vote = ApprovalVoteRepository.create(
            self.db,
            tenant_id=req.tenant_id,
            request_id=request_id,
            voter_principal_id=voter_principal_id,
            decision=decision,
            reason=reason,
            voted_at=datetime.now(UTC),
        )

        logger.info(
            "Vote cast: vote=%s request=%s voter=%s decision=%s",
            vote.id, request_id, voter_principal_id, decision.value,
        )

        return VoteResult(
            vote_id=vote.id,
            request_id=request_id,
            decision=decision,
            accepted=True,
        )

    def resolve(self, request_id: str) -> ResolutionResult:
        """Check if quorum is reached and resolve the request.

        Resolution logic:
          - count APPROVE votes >= required_quorum -> APPROVED
          - count REJECT votes >= required_quorum -> REJECTED
          - otherwise stays PENDING

        On APPROVED, a unique resolution_id is generated (uuid4).  This ID
        is used by GrantIssuer to bind the Grant to this specific approval.
        """
        req = ApprovalRequestRepository.get_by_id(self.db, request_id)
        if req is None:
            return ResolutionResult(
                request_id=request_id,
                status=ApprovalRequestStatus.PENDING,
                resolution_id=None,
                reason="request not found",
            )

        if req.status != ApprovalRequestStatus.PENDING:
            return ResolutionResult(
                request_id=request_id,
                status=req.status,
                resolution_id=req.resolution_id,
                reason=f"already {req.status.value}",
            )

        approve_count = ApprovalRequestRepository.count_votes(
            self.db, request_id=request_id, decision=VoteDecision.APPROVE,
        )
        reject_count = ApprovalRequestRepository.count_votes(
            self.db, request_id=request_id, decision=VoteDecision.REJECT,
        )

        if reject_count >= req.required_quorum:
            ApprovalRequestRepository.update_status(
                self.db, request_id, ApprovalRequestStatus.REJECTED,
            )
            logger.info(
                "ApprovalRequest REJECTED: request=%s reject_votes=%d",
                request_id, reject_count,
            )
            return ResolutionResult(
                request_id=request_id,
                status=ApprovalRequestStatus.REJECTED,
                resolution_id=None,
                reason=f"{reject_count} reject votes >= quorum {req.required_quorum}",
            )

        if approve_count >= req.required_quorum:
            resolution_id = str(uuid.uuid4())
            ApprovalRequestRepository.update_status(
                self.db, request_id, ApprovalRequestStatus.APPROVED,
                resolution_id=resolution_id,
            )
            logger.info(
                "ApprovalRequest APPROVED: request=%s resolution=%s approve_votes=%d",
                request_id, resolution_id, approve_count,
            )
            return ResolutionResult(
                request_id=request_id,
                status=ApprovalRequestStatus.APPROVED,
                resolution_id=resolution_id,
                reason=f"{approve_count} approve votes >= quorum {req.required_quorum}",
            )

        return ResolutionResult(
            request_id=request_id,
            status=ApprovalRequestStatus.PENDING,
            resolution_id=None,
            reason=f"quorum not reached ({approve_count}/{req.required_quorum} approve)",
        )

    def invalidate_if_stale(
        self,
        *,
        request_id: str,
        current_policy_digest: str,
        current_security_digest: str,
        current_args_hash: str,
    ) -> bool:
        """Invalidate a request if key content changed after creation.

        Returns True if the request was invalidated.
        """
        req = ApprovalRequestRepository.get_by_id(self.db, request_id)
        if req is None or req.status != ApprovalRequestStatus.PENDING:
            return False

        if (
            req.policy_digest != current_policy_digest
            or req.security_context_digest != current_security_digest
            or req.normalized_args_hash != current_args_hash
        ):
            ApprovalRequestRepository.update_status(
                self.db, request_id, ApprovalRequestStatus.INVALIDATED,
            )
            logger.warning(
                "ApprovalRequest invalidated (stale content): request=%s", request_id,
            )
            return True
        return False

    def get_request(self, request_id: str) -> Any:
        return ApprovalRequestRepository.get_by_id(self.db, request_id)
