"""In-memory notification service with optional DB persistence and per-user ring buffer."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

NotificationType = Literal[
    "task_completed",
    "task_failed",
    "approval_requested",
    "system_warning",
    "info",
]


@dataclass
class Notification:
    id: str
    type: NotificationType
    title: str
    message: str
    data: dict | None
    created_at: str
    read: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class NotificationService:
    """Thread-safe in-memory notification store with optional DB persistence.

    Each user gets at most ``_max_per_user`` notifications in memory.  When the
    limit is exceeded the *oldest* notifications are dropped (ring buffer).

    If a ``db`` session is supplied to write methods the notification is also
    persisted to the database, surviving process restarts.
    """

    _MAX_TOTAL_USERS = 10_000
    _USER_TTL_SECONDS = 86400 * 7

    def __init__(self, max_per_user: int = 100) -> None:
        self._notifications: dict[str, list[Notification]] = {}
        self._last_access: dict[str, float] = {}
        self._max_per_user = max_per_user
        self._lock = threading.Lock()
        self._cleanup_task: asyncio.Task | None = None
        self._start_cleanup_task()

    def _start_cleanup_task(self) -> None:
        """Start a background asyncio task that periodically evicts stale users."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running yet (e.g., during import) — try to schedule later
            self._cleanup_task = None
            return
        self._cleanup_task = loop.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically evict stale users every 60 seconds."""
        while True:
            await asyncio.sleep(60)
            with self._lock:
                self._evict_stale()

    def shutdown(self) -> None:
        """Cancel the periodic cleanup task. Call on application shutdown."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            self._cleanup_task = None

    # ── Write operations ─────────────────────────────────────────────────

    def create(
        self,
        user_id: str,
        type: NotificationType,
        title: str,
        message: str,
        data: dict | None = None,
        *,
        db: Session | None = None,
    ) -> Notification:
        """Create a new notification for *user_id* and return it.

        When *db* is provided the notification is also persisted to the
        database via :class:`NotificationRepository`.
        """
        notification = Notification(
            id=str(uuid.uuid4()),
            type=type,
            title=title,
            message=message,
            data=data,
            created_at=datetime.now(UTC).isoformat(),
            read=False,
        )

        if db is not None:
            self.persist_to_db(db, notification, user_id)

        with self._lock:
            if user_id not in self._notifications:
                self._notifications[user_id] = []
            self._notifications[user_id].insert(0, notification)
            self._last_access[user_id] = time.time()
            if len(self._notifications[user_id]) > self._max_per_user:
                self._notifications[user_id] = self._notifications[user_id][: self._max_per_user]
        return notification

    def mark_read(self, user_id: str, notification_id: str, *, db: Session | None = None) -> bool:
        """Mark a single notification as read.  Returns True if found."""
        found = False
        with self._lock:
            for n in self._notifications.get(user_id, []):
                if n.id == notification_id:
                    n.read = True
                    found = True
                    break

        if found and db is not None:
            from packages.db.repositories.notification_repo import NotificationRepository
            NotificationRepository.mark_read(db, notification_id)

        return found

    def mark_all_read(self, user_id: str, *, db: Session | None = None) -> int:
        """Mark all unread notifications as read.  Returns count marked."""
        count = 0
        with self._lock:
            for n in self._notifications.get(user_id, []):
                if not n.read:
                    n.read = True
                    count += 1

        if db is not None:
            from packages.db.repositories.notification_repo import NotificationRepository
            NotificationRepository.mark_all_read(db, user_id)

        return count

    def clear(self, user_id: str, *, db: Session | None = None) -> int:
        """Delete all notifications for *user_id*.  Returns count deleted."""
        with self._lock:
            removed = self._notifications.pop(user_id, [])
        count = len(removed)

        if db is not None:
            from packages.db.repositories.notification_repo import NotificationRepository
            NotificationRepository.delete_all(db, user_id)

        return count

    # ── Read operations ──────────────────────────────────────────────────

    def get_unread(self, user_id: str) -> list[Notification]:
        """Return all unread notifications (newest first)."""
        with self._lock:
            return [n for n in self._notifications.get(user_id, []) if not n.read]

    def get_all(self, user_id: str, limit: int = 50) -> list[Notification]:
        """Return notifications for *user_id*, newest first, up to *limit*."""
        with self._lock:
            return list(self._notifications.get(user_id, [])[:limit])

    def get_unread_count(self, user_id: str) -> int:
        """Return number of unread notifications for *user_id*."""
        with self._lock:
            return sum(1 for n in self._notifications.get(user_id, []) if not n.read)

    # ── DB helpers ───────────────────────────────────────────────────────

    def _evict_stale(self) -> None:
        """Evict users not accessed within TTL. Must be called under self._lock."""
        now = time.time()
        cutoff = now - self._USER_TTL_SECONDS
        stale = [uid for uid, ts in self._last_access.items() if ts < cutoff]
        for uid in stale:
            del self._notifications[uid]
            del self._last_access[uid]
        if len(self._notifications) > self._MAX_TOTAL_USERS:
            sorted_users = sorted(self._last_access, key=self._last_access.get)
            excess = len(self._notifications) - self._MAX_TOTAL_USERS
            for uid in sorted_users[:excess]:
                self._notifications.pop(uid, None)
                self._last_access.pop(uid, None)

    def persist_to_db(self, db: Session, notification: Notification, user_id: str) -> None:
        """Write a single :class:`Notification` dataclass to the database."""
        from packages.db.models import NotificationModel
        try:
            row = NotificationModel(
                id=notification.id,
                user_id=user_id,
                type=notification.type,
                title=notification.title,
                message=notification.message,
                data=notification.data,
                created_at=datetime.fromisoformat(notification.created_at) if notification.created_at else None,
                read=notification.read,
            )
            db.add(row)
            db.flush()
        except Exception:
            logger.exception("Notification operation failed")

    def load_from_db(self, db: Session, user_id: str) -> list[Notification]:
        """Restore in-memory notifications for *user_id* from the database.

        Returns the list of restored notifications so callers can inspect.
        Existing in-memory notifications for the user are replaced.
        """
        from packages.db.repositories.notification_repo import NotificationRepository
        rows = NotificationRepository.list_by_user(db, user_id, limit=self._max_per_user)
        restored = [
            Notification(
                id=row.id,
                type=row.type,
                title=row.title,
                message=row.message or "",
                data=row.data,
                created_at=row.created_at.isoformat() if row.created_at else "",
                read=row.read,
            )
            for row in rows
        ]
        with self._lock:
            self._notifications[user_id] = restored
        return restored


# Module-level singleton
notification_service = NotificationService()
