"""Repository for CapabilityGrant persistence (spec §4.3)."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from packages.db.models import CapabilityGrantModel, GrantStatusDB


class GrantRepository:
    """CRUD + atomic consume/revoke for CapabilityGrant records.

    The plaintext handle is never stored; only its SHA-256 digest.
    """

    @staticmethod
    def create(db: Session, **kwargs) -> CapabilityGrantModel:
        """Insert a new grant record. Caller supplies all fields."""
        grant = CapabilityGrantModel(**kwargs)
        db.add(grant)
        db.flush()
        db.refresh(grant)
        return grant

    @staticmethod
    def get_by_id(db: Session, grant_id: str) -> CapabilityGrantModel | None:
        return db.scalar(
            select(CapabilityGrantModel).where(CapabilityGrantModel.id == grant_id)
        )

    @staticmethod
    def get_by_handle_digest(db: Session, handle_digest: str) -> CapabilityGrantModel | None:
        """Lookup by SHA-256(handle) - the only way to find a grant from a handle."""
        return db.scalar(
            select(CapabilityGrantModel).where(
                CapabilityGrantModel.handle_digest == handle_digest
            )
        )

    @staticmethod
    def get_by_step(
        db: Session, *, tenant_id: str, step_run_id: str
    ) -> list[CapabilityGrantModel]:
        return list(
            db.scalars(
                select(CapabilityGrantModel)
                .where(
                    CapabilityGrantModel.tenant_id == tenant_id,
                    CapabilityGrantModel.step_run_id == step_run_id,
                )
                .order_by(CapabilityGrantModel.issued_at)
            )
        )

    @staticmethod
    def update_status(
        db: Session, grant_id: str, status: GrantStatusDB
    ) -> CapabilityGrantModel | None:
        db.execute(
            update(CapabilityGrantModel)
            .where(CapabilityGrantModel.id == grant_id)
            .values(status=status)
        )
        db.flush()
        return GrantRepository.get_by_id(db, grant_id)

    @staticmethod
    def consume(db: Session, grant_id: str) -> bool:
        """Atomically mark a grant CONSUMED. Returns True if this call won the race.

        Uses a conditional UPDATE (WHERE status='issued') so concurrent
        consumers cannot both succeed - exactly one will affect 0 rows.
        """
        now = datetime.now(UTC)
        result = db.execute(
            update(CapabilityGrantModel)
            .where(
                CapabilityGrantModel.id == grant_id,
                CapabilityGrantModel.status == GrantStatusDB.ISSUED,
            )
            .values(status=GrantStatusDB.CONSUMED, consumed_at=now)
        )
        db.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    @staticmethod
    def revoke(db: Session, grant_id: str) -> CapabilityGrantModel | None:
        """Mark a grant REVOKED. Only works if not yet consumed."""
        db.execute(
            update(CapabilityGrantModel)
            .where(
                CapabilityGrantModel.id == grant_id,
                CapabilityGrantModel.status == GrantStatusDB.ISSUED,
            )
            .values(status=GrantStatusDB.REVOKED)
        )
        db.flush()
        return GrantRepository.get_by_id(db, grant_id)

    @staticmethod
    def expire_stale(db: Session) -> int:
        """Mark all expired-but-still-ISSUED grants as EXPIRED. Returns count."""
        now = datetime.now(UTC).replace(tzinfo=None)
        result = db.execute(
            update(CapabilityGrantModel)
            .where(
                CapabilityGrantModel.status == GrantStatusDB.ISSUED,
                CapabilityGrantModel.expires_at < now,
            )
            .values(status=GrantStatusDB.EXPIRED)
        )
        db.flush()
        return result.rowcount  # type: ignore[return-value]
