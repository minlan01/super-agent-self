"""Repository for ApprovalRequest + ApprovalVote (spec §4.3 high-risk gating)."""

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from packages.db.models import (
    ApprovalRequestModel,
    ApprovalRequestStatus,
    ApprovalVoteModel,
    VoteDecision,
)


class ApprovalRequestRepository:
    """CRUD for approval_requests."""

    @staticmethod
    def create(db: Session, **kwargs) -> ApprovalRequestModel:
        req = ApprovalRequestModel(**kwargs)
        db.add(req)
        db.flush()
        db.refresh(req)
        return req

    @staticmethod
    def get_by_id(db: Session, request_id: str) -> ApprovalRequestModel | None:
        return db.scalar(
            select(ApprovalRequestModel).where(ApprovalRequestModel.id == request_id)
        )

    @staticmethod
    def get_by_step(
        db: Session, *, tenant_id: str, step_run_id: str
    ) -> ApprovalRequestModel | None:
        """Get the (latest) approval request for a step."""
        return db.scalar(
            select(ApprovalRequestModel)
            .where(
                ApprovalRequestModel.tenant_id == tenant_id,
                ApprovalRequestModel.step_run_id == step_run_id,
            )
            .order_by(ApprovalRequestModel.created_at.desc())
        )

    @staticmethod
    def update_status(
        db: Session, request_id: str, status: ApprovalRequestStatus,
        resolution_id: str | None = None,
    ) -> ApprovalRequestModel | None:
        values: dict = {"status": status}
        if status in (ApprovalRequestStatus.APPROVED, ApprovalRequestStatus.REJECTED):
            values["resolved_at"] = datetime.now(UTC)
        if resolution_id is not None:
            values["resolution_id"] = resolution_id
        db.execute(
            update(ApprovalRequestModel)
            .where(ApprovalRequestModel.id == request_id)
            .values(**values)
        )
        db.flush()
        return ApprovalRequestRepository.get_by_id(db, request_id)

    @staticmethod
    def count_votes(
        db: Session, *, request_id: str, decision: VoteDecision,
    ) -> int:
        result = db.scalar(
            select(func.count(ApprovalVoteModel.id)).where(
                ApprovalVoteModel.request_id == request_id,
                ApprovalVoteModel.decision == decision,
            )
        )
        return result or 0

    @staticmethod
    def get_pending(db: Session, *, tenant_id: str) -> list[ApprovalRequestModel]:
        return list(
            db.scalars(
                select(ApprovalRequestModel)
                .where(
                    ApprovalRequestModel.tenant_id == tenant_id,
                    ApprovalRequestModel.status == ApprovalRequestStatus.PENDING,
                )
                .order_by(ApprovalRequestModel.created_at)
            )
        )


class ApprovalVoteRepository:
    """CRUD for approval_votes."""

    @staticmethod
    def create(db: Session, **kwargs) -> ApprovalVoteModel:
        vote = ApprovalVoteModel(**kwargs)
        db.add(vote)
        db.flush()
        db.refresh(vote)
        return vote

    @staticmethod
    def get_by_request_and_voter(
        db: Session, *, request_id: str, voter_principal_id: str,
    ) -> ApprovalVoteModel | None:
        return db.scalar(
            select(ApprovalVoteModel).where(
                ApprovalVoteModel.request_id == request_id,
                ApprovalVoteModel.voter_principal_id == voter_principal_id,
            )
        )

    @staticmethod
    def get_by_request(db: Session, *, request_id: str) -> list[ApprovalVoteModel]:
        return list(
            db.scalars(
                select(ApprovalVoteModel)
                .where(ApprovalVoteModel.request_id == request_id)
                .order_by(ApprovalVoteModel.voted_at)
            )
        )
