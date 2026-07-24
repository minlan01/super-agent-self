"""Repository for EffectRecord persistence (spec §4.3 + v3 M9)."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from packages.db.models import EffectRecordModel, EffectStatusDB


# Terminal states - once reached, cannot transition back.
_EFFECT_TERMINAL_STATES = frozenset({
    EffectStatusDB.CONFIRMED,
    EffectStatusDB.FAILED,
    EffectStatusDB.UNKNOWN_OUTCOME,
    EffectStatusDB.RECONCILED,
})


class EffectRepository:
    """CRUD + state-machine transitions for EffectRecord.

    Enforces: terminal states are irreversible.  Any attempt to update
    a terminal effect to a non-terminal state is a no-op (returns None).
    """

    @staticmethod
    def create(db: Session, **kwargs) -> EffectRecordModel:
        effect = EffectRecordModel(**kwargs)
        db.add(effect)
        db.flush()
        db.refresh(effect)
        return effect

    @staticmethod
    def get_by_id(db: Session, effect_id: str) -> EffectRecordModel | None:
        return db.scalar(
            select(EffectRecordModel).where(EffectRecordModel.id == effect_id)
        )

    @staticmethod
    def get_by_step(
        db: Session, *, tenant_id: str, step_run_id: str
    ) -> list[EffectRecordModel]:
        return list(
            db.scalars(
                select(EffectRecordModel)
                .where(
                    EffectRecordModel.tenant_id == tenant_id,
                    EffectRecordModel.step_run_id == step_run_id,
                )
                .order_by(EffectRecordModel.created_at)
            )
        )

    @staticmethod
    def update_status(
        db: Session, effect_id: str, new_status: EffectStatusDB
    ) -> EffectRecordModel | None:
        """Transition an effect to a new status.

        Enforces terminal-state immutability: if the effect is already in a
        terminal state and new_status is different, the update is rejected
        (returns the unchanged record).  This is a fail-closed guard.
        """
        effect = EffectRepository.get_by_id(db, effect_id)
        if effect is None:
            return None

        # Terminal states are irreversible.
        if effect.status in _EFFECT_TERMINAL_STATES and new_status != effect.status:
            return effect  # reject transition

        values: dict = {"status": new_status}
        if new_status in _EFFECT_TERMINAL_STATES:
            values["finalized_at"] = datetime.now(UTC)

        db.execute(
            update(EffectRecordModel)
            .where(EffectRecordModel.id == effect_id)
            .values(**values)
        )
        db.flush()
        return EffectRepository.get_by_id(db, effect_id)

    @staticmethod
    def set_hashes(
        db: Session, effect_id: str, *, before_hash: str | None, after_hash: str | None
    ) -> EffectRecordModel | None:
        """Record before/after content hashes for side-effect verification."""
        db.execute(
            update(EffectRecordModel)
            .where(EffectRecordModel.id == effect_id)
            .values(before_hash=before_hash, after_hash=after_hash)
        )
        db.flush()
        return EffectRepository.get_by_id(db, effect_id)

    @staticmethod
    def get_unknown_outcomes(
        db: Session, *, tenant_id: str
    ) -> list[EffectRecordModel]:
        """Get all effects in UNKNOWN_OUTCOME state (for reconciliation queue)."""
        return list(
            db.scalars(
                select(EffectRecordModel)
                .where(
                    EffectRecordModel.tenant_id == tenant_id,
                    EffectRecordModel.status == EffectStatusDB.UNKNOWN_OUTCOME,
                )
                .order_by(EffectRecordModel.created_at)
            )
        )

    @staticmethod
    def get_non_terminal_by_step(
        db: Session, *, tenant_id: str, step_run_id: str
    ) -> list[EffectRecordModel]:
        """Get effects that are not yet in a terminal state."""
        return list(
            db.scalars(
                select(EffectRecordModel)
                .where(
                    EffectRecordModel.tenant_id == tenant_id,
                    EffectRecordModel.step_run_id == step_run_id,
                    ~EffectRecordModel.status.in_(_EFFECT_TERMINAL_STATES),
                )
                .order_by(EffectRecordModel.created_at)
            )
        )
