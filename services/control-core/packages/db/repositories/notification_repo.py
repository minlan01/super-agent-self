"""Repository for NotificationModel CRUD and cleanup."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from packages.db.models import NotificationModel


class NotificationRepository:
    """Data-access layer for persisted notifications."""

    @staticmethod
    def create(
        db: Session,
        *,
        user_id: str,
        type: str,
        title: str,
        message: str | None = None,
        data: dict | None = None,
    ) -> NotificationModel:
        """Insert a new notification row and return it."""
        notif = NotificationModel(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            data=data,
        )
        db.add(notif)
        db.flush()
        db.refresh(notif)
        return notif

    @staticmethod
    def get_by_id(db: Session, notification_id: str) -> NotificationModel | None:
        """Return a single notification by primary key, or None."""
        return db.get(NotificationModel, notification_id)

    @staticmethod
    def list_by_user(
        db: Session,
        user_id: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> list[NotificationModel]:
        """Return notifications for *user_id*, newest first."""
        stmt = (
            select(NotificationModel)
            .where(NotificationModel.user_id == user_id)
            .order_by(NotificationModel.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_unread_count(db: Session, user_id: str) -> int:
        """Return number of unread notifications for *user_id*."""
        stmt = (
            select(func.count())
            .select_from(NotificationModel)
            .where(NotificationModel.user_id == user_id, NotificationModel.read.is_(False))
        )
        return db.scalar(stmt) or 0

    @staticmethod
    def mark_read(db: Session, notification_id: str) -> bool:
        """Mark a single notification as read.  Returns True if found."""
        notif = db.get(NotificationModel, notification_id)
        if notif is None:
            return False
        notif.read = True
        db.flush()
        return True

    @staticmethod
    def mark_all_read(db: Session, user_id: str) -> int:
        """Mark all unread notifications as read.  Returns count updated."""
        stmt = (
            update(NotificationModel)
            .where(NotificationModel.user_id == user_id, NotificationModel.read.is_(False))
            .values(read=True)
        )
        result = db.execute(stmt)
        db.flush()
        return result.rowcount

    @staticmethod
    def delete_all(db: Session, user_id: str) -> int:
        """Delete all notifications for *user_id*.  Returns count deleted."""
        stmt = delete(NotificationModel).where(NotificationModel.user_id == user_id)
        result = db.execute(stmt)
        db.flush()
        return result.rowcount

    @staticmethod
    def cleanup_old(db: Session, days: int = 30) -> int:
        """Delete notifications older than *days*.  Returns count deleted."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = delete(NotificationModel).where(NotificationModel.created_at < cutoff)
        result = db.execute(stmt)
        db.flush()
        return result.rowcount
