"""Repository for Approval CRUD operations."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from packages.agent_core.schemas import ApprovalCreate, ApprovalResolve
from packages.db.models import Approval, ApprovalStatus


class ApprovalRepository:
    @staticmethod
    def create(db: Session, schema: ApprovalCreate) -> Approval:
        approval = Approval(
            approval_type=schema.approval_type,
            target_id=schema.target_id,
            edition=schema.edition,
            requested_by=schema.requested_by,
            reason=schema.reason,
        )
        db.add(approval)
        db.flush()
        db.refresh(approval)
        return approval

    @staticmethod
    def get_by_id(db: Session, approval_id: str) -> Approval | None:
        return db.get(Approval, approval_id)

    @staticmethod
    def get_many_by_ids(db: Session, approval_ids: list[str]) -> dict[str, Approval]:
        """Fetch multiple approvals in a single SELECT.  Returns ``{id: Approval}``."""
        if not approval_ids:
            return {}
        stmt = select(Approval).where(Approval.id.in_(approval_ids))
        return {a.id: a for a in db.scalars(stmt).all()}

    @staticmethod
    def list_pending(
        db: Session,
        edition=None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[Approval]:
        stmt = (
            select(Approval)
            .where(Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.created_at.desc())
        )
        if edition is not None:
            stmt = stmt.where(Approval.edition == edition)
        stmt = stmt.offset(skip).limit(limit)
        return list(db.scalars(stmt).all())

    @staticmethod
    def resolve(db: Session, approval_id: str, schema: ApprovalResolve) -> Approval | None:
        new_status = ApprovalStatus.APPROVED if schema.approved else ApprovalStatus.REJECTED
        result = db.execute(
            update(Approval)
            .where(Approval.id == approval_id, Approval.status == ApprovalStatus.PENDING)
            .values(
                status=new_status,
                approved_by=schema.approved_by,
                reason=schema.reason,
                resolved_at=datetime.now(UTC),
            )
        )
        if result.rowcount == 0:
            return None
        db.flush()
        return db.get(Approval, approval_id)
