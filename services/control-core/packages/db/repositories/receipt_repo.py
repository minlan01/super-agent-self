"""Repository for ToolReceipt persistence (spec §4.3)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import ToolReceiptModel


class ReceiptRepository:
    """CRUD for ToolReceipt records."""

    @staticmethod
    def create(db: Session, **kwargs) -> ToolReceiptModel:
        receipt = ToolReceiptModel(**kwargs)
        db.add(receipt)
        db.flush()
        db.refresh(receipt)
        return receipt

    @staticmethod
    def get_by_id(db: Session, receipt_id: str) -> ToolReceiptModel | None:
        return db.scalar(
            select(ToolReceiptModel).where(ToolReceiptModel.id == receipt_id)
        )

    @staticmethod
    def get_by_effect(
        db: Session, *, tenant_id: str, effect_id: str
    ) -> ToolReceiptModel | None:
        """Get the receipt for a specific effect (1:1 in normal flow)."""
        return db.scalar(
            select(ToolReceiptModel)
            .where(
                ToolReceiptModel.tenant_id == tenant_id,
                ToolReceiptModel.effect_id == effect_id,
            )
            .order_by(ToolReceiptModel.ended_at.desc())
        )

    @staticmethod
    def get_by_step(
        db: Session, *, tenant_id: str, step_run_id: str
    ) -> list[ToolReceiptModel]:
        """Get all receipts for a step (via effect -> step join is not available
        directly; caller should iterate effects then receipts)."""
        return list(
            db.scalars(
                select(ToolReceiptModel)
                .where(ToolReceiptModel.tenant_id == tenant_id)
                .order_by(ToolReceiptModel.ended_at)
            )
        )
