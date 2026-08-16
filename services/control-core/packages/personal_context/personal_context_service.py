"""Personal Context Service — manages user preferences, projects, and reminders."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from packages.db.models import MemoryType
from packages.memory.memory_service import MemoryService
from packages.memory.schemas import MemoryWriteRequest

logger = logging.getLogger(__name__)


class PersonalContextService:
    """Manages personal context: preferences, projects, reminders, daily context."""

    def __init__(self, memory_service: MemoryService):
        self.memory_service = memory_service

    def get_user_preferences(self, db: Session, user_id: str = "default") -> list[dict[str, Any]]:
        """Get all active user preference memories."""
        memories = self.memory_service.search(
            db, memory_type="user_preference", user_id=user_id, edition="personal", limit=20,
        )
        return [
            {"id": m.id, "title": m.title, "summary": m.summary, "content": m.content}
            for m in memories
        ]

    def get_project_context(self, db: Session, user_id: str = "default") -> list[dict[str, Any]]:
        """Get personal project context."""
        memories = self.memory_service.search(
            db, memory_type="personal_project", user_id=user_id, edition="personal", limit=10,
        )
        return [
            {"id": m.id, "title": m.title, "summary": m.summary}
            for m in memories
        ]

    def get_active_reminders(self, db: Session, user_id: str = "default") -> list[dict[str, Any]]:
        """Get active reminders."""
        memories = self.memory_service.search(
            db, memory_type="reminder", user_id=user_id, edition="personal", limit=20,
        )
        return [
            {"id": m.id, "title": m.title, "summary": m.summary, "content": m.content}
            for m in memories
        ]

    def get_daily_context(self, db: Session, user_id: str = "default") -> dict[str, Any]:
        """Get today's context (daily context + reminders)."""
        daily = self.memory_service.search(
            db, memory_type="daily_context", user_id=user_id, edition="personal", limit=5,
        )
        reminders = self.get_active_reminders(db, user_id)

        return {
            "daily_context": [
                {"title": m.title, "summary": m.summary} for m in daily
            ],
            "reminders": reminders,
            "preferences_count": len(self.get_user_preferences(db, user_id)),
            "projects_count": len(self.get_project_context(db, user_id)),
        }

    async def save_preference(
        self,
        db: Session,
        key: str,
        value: str,
        user_id: str = "default",
    ) -> Any:
        """Save a user preference as a memory."""
        return await self.memory_service.write_from_task(
            db,
            MemoryWriteRequest(
                task_id=None,  # preference: not bound to any task (FK safety)
                goal=f"Save preference: {key} = {value}",
                steps_summary=[],
                success=True,
                memory_type=MemoryType.USER_PREFERENCE,
            ),
            user_id=user_id,
            edition="personal",
        )

    async def save_reminder(
        self,
        db: Session,
        title: str,
        description: str,
        user_id: str = "default",
    ) -> Any:
        """Save a reminder."""
        return await self.memory_service.write_from_task(
            db,
            MemoryWriteRequest(
                task_id=None,  # reminder: not bound to any task (FK safety)
                goal=title,
                steps_summary=[{"tool": "reminder", "status": "completed"}],
                success=True,
                memory_type=MemoryType.REMINDER,
            ),
            user_id=user_id,
            edition="personal",
        )
