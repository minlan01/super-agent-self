"""Reminder Service — create, list, and dismiss reminders."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import Memory, MemoryType

logger = logging.getLogger(__name__)


class ReminderService:
    """Manages reminders stored as memories."""

    def create_reminder(
        self,
        db: Session,
        title: str,
        description: str = "",
        user_id: str = "default",
        edition: str = "personal",
        expires_at: datetime | None = None,
    ) -> Memory:
        """Create a new reminder."""
        memory = Memory(
            user_id=user_id,
            edition=edition,
            memory_type=MemoryType.REMINDER,
            title=title,
            summary=description or title,
            content={"type": "reminder", "description": description},
            importance_score=0.6,
            confidence_score=1.0,
            is_active=True,
            expires_at=expires_at,
        )
        db.add(memory)
        db.flush()
        db.refresh(memory)
        logger.info("Reminder created: %s (%s)", title, memory.id)
        return memory

    def list_active(
        self,
        db: Session,
        user_id: str = "default",
        edition: str = "personal",
    ) -> list[Memory]:
        """List active, non-expired reminders."""
        now = datetime.now(UTC)
        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.edition == edition,
                Memory.memory_type == MemoryType.REMINDER,
                Memory.is_active == True,  # noqa: E712
            )
            .where(
                (Memory.expires_at == None) | (Memory.expires_at > now)  # noqa: E711
            )
            .order_by(Memory.created_at.desc())
        )
        return list(db.scalars(stmt).all())

    def dismiss(self, db: Session, reminder_id: str) -> Memory | None:
        """Dismiss (deactivate) a reminder."""
        memory = db.get(Memory, reminder_id)
        if memory is None:
            return None
        memory.is_active = False
        db.flush()
        db.refresh(memory)
        logger.info("Reminder dismissed: %s", reminder_id)
        return memory

    def get(self, db: Session, reminder_id: str) -> Memory | None:
        return db.get(Memory, reminder_id)
