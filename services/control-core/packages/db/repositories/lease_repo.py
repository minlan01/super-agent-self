"""Repository for Lease persistence (spec §4.3)."""

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from packages.db.models import LeaseModel, LeaseStatus


class LeaseRepository:
    """CRUD + renew/release for Lease records.

    fencing_token is assigned by LeaseManager (monotonic per worker+step);
    the repository just persists and queries.
    """

    @staticmethod
    def create(db: Session, **kwargs) -> LeaseModel:
        lease = LeaseModel(**kwargs)
        db.add(lease)
        db.flush()
        db.refresh(lease)
        return lease

    @staticmethod
    def get_by_id(db: Session, lease_id: str) -> LeaseModel | None:
        return db.scalar(
            select(LeaseModel).where(LeaseModel.id == lease_id)
        )

    @staticmethod
    def get_active_by_step(
        db: Session, *, tenant_id: str, step_run_id: str
    ) -> LeaseModel | None:
        """Get the single active lease for a step (if any)."""
        return db.scalar(
            select(LeaseModel).where(
                LeaseModel.tenant_id == tenant_id,
                LeaseModel.step_run_id == step_run_id,
                LeaseModel.status == LeaseStatus.ACTIVE,
            )
        )

    @staticmethod
    def get_max_fencing_token(
        db: Session, *, worker_id: str, step_run_id: str
    ) -> int:
        """Get the highest fencing_token ever issued for this worker+step.

        Used by LeaseManager to ensure monotonicity: next token = max + 1.
        """
        result = db.scalar(
            select(func.max(LeaseModel.fencing_token)).where(
                LeaseModel.worker_id == worker_id,
                LeaseModel.step_run_id == step_run_id,
            )
        )
        return result or 0

    @staticmethod
    def update_status(
        db: Session, lease_id: str, status: LeaseStatus
    ) -> LeaseModel | None:
        db.execute(
            update(LeaseModel)
            .where(LeaseModel.id == lease_id)
            .values(status=status)
        )
        db.flush()
        return LeaseRepository.get_by_id(db, lease_id)

    @staticmethod
    def renew(
        db: Session, lease_id: str, new_expires_at: datetime
    ) -> LeaseModel | None:
        """Extend a lease's expiry. Only works if still ACTIVE."""
        db.execute(
            update(LeaseModel)
            .where(
                LeaseModel.id == lease_id,
                LeaseModel.status == LeaseStatus.ACTIVE,
            )
            .values(expires_at=new_expires_at, last_heartbeat_at=datetime.now(UTC))
        )
        db.flush()
        return LeaseRepository.get_by_id(db, lease_id)

    @staticmethod
    def release(db: Session, lease_id: str) -> LeaseModel | None:
        """Mark a lease INACTIVE (released by worker)."""
        return LeaseRepository.update_status(db, lease_id, LeaseStatus.INACTIVE)

    @staticmethod
    def expire_stale(db: Session) -> int:
        """Mark all active-but-expired leases as EXPIRED. Returns count."""
        now = datetime.now(UTC)
        result = db.execute(
            update(LeaseModel)
            .where(
                LeaseModel.status == LeaseStatus.ACTIVE,
                LeaseModel.expires_at < now,
            )
            .values(status=LeaseStatus.EXPIRED)
        )
        db.flush()
        return result.rowcount  # type: ignore[return-value]

    @staticmethod
    def is_valid(
        db: Session, lease_id: str, fencing_token: int
    ) -> bool:
        """Check if a lease is active, not expired, and fencing_token matches."""
        lease = LeaseRepository.get_by_id(db, lease_id)
        if lease is None:
            return False
        if lease.status != LeaseStatus.ACTIVE:
            return False
        if lease.expires_at <= datetime.now(UTC):
            return False
        if lease.fencing_token != fencing_token:
            return False
        return True
