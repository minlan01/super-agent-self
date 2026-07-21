"""Repository for AuditEvent CRUD operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.agent_core.schemas import AuditEventCreate
from packages.db.models import AuditEvent


class AuditRepository:
    @staticmethod
    def create(db: Session, schema: AuditEventCreate) -> AuditEvent:
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
        db.refresh(event)
        return event

    @staticmethod
    def batch_create(db: Session, schemas: list[AuditEventCreate]) -> list[AuditEvent]:
        """Create multiple audit events in a single ``add_all`` + ``flush``.

        Skips per-row ``refresh`` (callers rarely need server-generated
        columns beyond the PK for audit events).
        """
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
