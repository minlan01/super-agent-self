"""Repository for AuditEvent CRUD operations."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.agent_core.schemas import AuditEventCreate
from packages.db.audit_chain import compute_entry_hash
from packages.db.models import AuditEvent


def _chain_head(db: Session) -> str | None:
    """Return the entry_hash of the latest hashed audit row (chain head)."""
    return db.scalar(
        select(AuditEvent.entry_hash)
        .where(AuditEvent.entry_hash.is_not(None))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.entry_hash.desc())
        .limit(1)
    )


class AuditRepository:
    @staticmethod
    def create(db: Session, schema: AuditEventCreate) -> AuditEvent:
        # flush first to materialize id/created_at, then seal the chain link.
        event = AuditEvent(
            task_id=schema.task_id,
            step_id=schema.step_id,
            edition=schema.edition,
            event_type=schema.event_type,
            actor=schema.actor,
            detail=schema.detail,
        )
        db.add(event)
        db.flush()
        # The new row's hash columns are still NULL, so the head query
        # naturally returns the previous hashed row.
        prev = _chain_head(db)
        event.prev_entry_hash = prev
        event.entry_hash = compute_entry_hash(
            prev_entry_hash=prev,
            event_id=event.id,
            created_at=event.created_at,
            event_type=str(getattr(event.event_type, "value", event.event_type)),
            actor=str(event.actor),
            task_id=event.task_id,
            step_id=event.step_id,
            detail=event.detail,
        )
        db.flush()
        db.refresh(event)
        return event

    @staticmethod
    def batch_create(db: Session, schemas: list[AuditEventCreate]) -> list[AuditEvent]:
        """Create multiple audit events in a single ``add_all`` + ``flush``,
        sealing each into the hash chain in order."""
        if not schemas:
            return []
        events = [
            AuditEvent(
                task_id=s.task_id,
                step_id=s.step_id,
                edition=s.edition,
                event_type=s.event_type,
                actor=s.actor,
                detail=s.detail,
            )
            for s in schemas
        ]
        db.add_all(events)
        db.flush()

        prev = _chain_head(db)
        for event in events:
            event.prev_entry_hash = prev
            event.entry_hash = compute_entry_hash(
                prev_entry_hash=prev,
                event_id=event.id,
                created_at=event.created_at,
                event_type=str(getattr(event.event_type, "value", event.event_type)),
                actor=str(event.actor),
                task_id=event.task_id,
                step_id=event.step_id,
                detail=event.detail,
            )
            prev = event.entry_hash
        db.flush()
        return events

    @staticmethod
    def list_by_task(db: Session, task_id: str, limit: int = 200) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.task_id == task_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def list_filters(
        db: Session,
        task_id: str | None = None,
        event_type=None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[AuditEvent]:
        stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc())
        if task_id is not None:
            stmt = stmt.where(AuditEvent.task_id == task_id)
        if event_type is not None:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        stmt = stmt.offset(skip).limit(limit)
        return list(db.scalars(stmt).all())
