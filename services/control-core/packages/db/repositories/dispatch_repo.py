"""Repository for DispatchAttempt persistence (PROJECT-CONTEXT invariant).

Every dispatch attempt must persist: effect_id, attempt_ordinal, lease_id,
fencing_token, grant_digest, worker_id, adapter_name, dispatched_at.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.db.models import DispatchAttemptModel


class DispatchAttemptRepository:
    """CRUD + ordinal tracking for DispatchAttempt records."""

    @staticmethod
    def create(db: Session, **kwargs) -> DispatchAttemptModel:
        attempt = DispatchAttemptModel(**kwargs)
        db.add(attempt)
        db.flush()
        db.refresh(attempt)
        return attempt

    @staticmethod
    def get_by_effect(
        db: Session, *, tenant_id: str, effect_id: str
    ) -> list[DispatchAttemptModel]:
        """Get all dispatch attempts for an effect, ordered by ordinal."""
        return list(
            db.scalars(
                select(DispatchAttemptModel)
                .where(
                    DispatchAttemptModel.tenant_id == tenant_id,
                    DispatchAttemptModel.effect_id == effect_id,
                )
                .order_by(DispatchAttemptModel.attempt_ordinal)
            )
        )

    @staticmethod
    def get_latest(
        db: Session, *, tenant_id: str, effect_id: str
    ) -> DispatchAttemptModel | None:
        """Get the most recent dispatch attempt for an effect."""
        return db.scalar(
            select(DispatchAttemptModel)
            .where(
                DispatchAttemptModel.tenant_id == tenant_id,
                DispatchAttemptModel.effect_id == effect_id,
            )
            .order_by(DispatchAttemptModel.attempt_ordinal.desc())
            .limit(1)
        )

    @staticmethod
    def next_ordinal(db: Session, *, effect_id: str) -> int:
        """Get the next attempt ordinal for an effect (1-based)."""
        count = db.scalar(
            select(func.count(DispatchAttemptModel.id)).where(
                DispatchAttemptModel.effect_id == effect_id
            )
        )
        return (count or 0) + 1

    @staticmethod
    def set_result(
        db: Session, attempt_id: str, result_status: str
    ) -> DispatchAttemptModel | None:
        """Record the result status of a dispatch attempt."""
        from sqlalchemy import update as sa_update
        db.execute(
            sa_update(DispatchAttemptModel)
            .where(DispatchAttemptModel.id == attempt_id)
            .values(result_status=result_status)
        )
        db.flush()
        return db.scalar(
            select(DispatchAttemptModel).where(DispatchAttemptModel.id == attempt_id)
        )
