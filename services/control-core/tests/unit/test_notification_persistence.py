"""Tests for notification DB persistence: NotificationModel, NotificationRepository, and
NotificationService DB integration."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.db.models import Base, NotificationModel
from packages.db.repositories.notification_repo import NotificationRepository
from packages.notification.notification_service import Notification, NotificationService


@pytest.fixture()
def db() -> Session:
    """Provide a fresh SQLite in-memory session with all tables created."""
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


# ── NotificationModel tests ─────────────────────────────────────────────


class TestNotificationModel:
    def test_create_model_directly(self, db: Session):
        notif = NotificationModel(
            user_id="user-1",
            type="task_completed",
            title="Task done",
            message="Your task has completed",
            data={"task_id": "t-1"},
        )
        db.add(notif)
        db.commit()
        assert notif.id is not None
        assert len(notif.id) == 36  # UUID format
        assert notif.user_id == "user-1"
        assert notif.type == "task_completed"
        assert notif.title == "Task done"
        assert notif.message == "Your task has completed"
        assert notif.data == {"task_id": "t-1"}
        assert notif.read is False
        assert notif.created_at is not None

    def test_model_default_values(self, db: Session):
        notif = NotificationModel(
            user_id="user-2",
            type="info",
            title="Test",
        )
        db.add(notif)
        db.commit()
        assert notif.read is False
        assert notif.message is None
        assert notif.data is None
        assert notif.created_at is not None


# ── NotificationRepository tests ────────────────────────────────────────


class TestNotificationRepository:
    def test_create_and_get(self, db: Session):
        notif = NotificationRepository.create(
            db, user_id="u1", type="task_completed", title="Done", message="ok"
        )
        assert notif.id is not None

        fetched = NotificationRepository.get_by_id(db, notif.id)
        assert fetched is not None
        assert fetched.title == "Done"
        assert fetched.user_id == "u1"

    def test_get_by_id_not_found(self, db: Session):
        assert NotificationRepository.get_by_id(db, "nonexistent") is None

    def test_list_by_user_ordering(self, db: Session):
        """Newest notifications should come first."""
        NotificationRepository.create(db, user_id="u1", type="info", title="First")
        NotificationRepository.create(db, user_id="u1", type="info", title="Second")
        NotificationRepository.create(db, user_id="u1", type="info", title="Third")

        results = NotificationRepository.list_by_user(db, "u1")
        assert len(results) == 3
        assert results[0].title == "Third"
        assert results[2].title == "First"

    def test_list_by_user_skips_other_users(self, db: Session):
        NotificationRepository.create(db, user_id="u1", type="info", title="For u1")
        NotificationRepository.create(db, user_id="u2", type="info", title="For u2")

        results = NotificationRepository.list_by_user(db, "u1")
        assert len(results) == 1
        assert results[0].title == "For u1"

    def test_list_by_user_skip_and_limit(self, db: Session):
        for i in range(5):
            NotificationRepository.create(db, user_id="u1", type="info", title=f"N{i}")

        results = NotificationRepository.list_by_user(db, "u1", skip=1, limit=2)
        assert len(results) == 2
        # Ordered newest-first, skip 1 means we skip N4, get N3 and N2
        assert results[0].title == "N3"
        assert results[1].title == "N2"

    def test_get_unread_count(self, db: Session):
        NotificationRepository.create(db, user_id="u1", type="info", title="A")
        NotificationRepository.create(db, user_id="u1", type="info", title="B")

        count = NotificationRepository.get_unread_count(db, "u1")
        assert count == 2

    def test_get_unread_count_excludes_read(self, db: Session):
        notif = NotificationRepository.create(db, user_id="u1", type="info", title="A")
        NotificationRepository.mark_read(db, notif.id)
        NotificationRepository.create(db, user_id="u1", type="info", title="B")

        count = NotificationRepository.get_unread_count(db, "u1")
        assert count == 1

    def test_mark_read_found(self, db: Session):
        notif = NotificationRepository.create(db, user_id="u1", type="info", title="A")
        assert not notif.read

        result = NotificationRepository.mark_read(db, notif.id)
        assert result is True

        fetched = NotificationRepository.get_by_id(db, notif.id)
        assert fetched.read is True

    def test_mark_read_not_found(self, db: Session):
        result = NotificationRepository.mark_read(db, "nonexistent")
        assert result is False

    def test_mark_all_read(self, db: Session):
        NotificationRepository.create(db, user_id="u1", type="info", title="A")
        NotificationRepository.create(db, user_id="u1", type="info", title="B")
        NotificationRepository.create(db, user_id="u2", type="info", title="C")

        count = NotificationRepository.mark_all_read(db, "u1")
        assert count == 2

        assert NotificationRepository.get_unread_count(db, "u1") == 0
        assert NotificationRepository.get_unread_count(db, "u2") == 1

    def test_delete_all(self, db: Session):
        NotificationRepository.create(db, user_id="u1", type="info", title="A")
        NotificationRepository.create(db, user_id="u1", type="info", title="B")
        NotificationRepository.create(db, user_id="u2", type="info", title="C")

        deleted = NotificationRepository.delete_all(db, "u1")
        assert deleted == 2
        assert NotificationRepository.list_by_user(db, "u1") == []
        assert len(NotificationRepository.list_by_user(db, "u2")) == 1

    def test_cleanup_old(self, db: Session):
        # Insert a notification with an old created_at
        old_notif = NotificationModel(
            user_id="u1",
            type="info",
            title="Old",
            created_at=datetime.now(UTC) - timedelta(days=60),
        )
        db.add(old_notif)
        db.commit()

        # Insert a recent one via the repo
        NotificationRepository.create(db, user_id="u1", type="info", title="Recent")

        deleted = NotificationRepository.cleanup_old(db, days=30)
        assert deleted == 1

        remaining = NotificationRepository.list_by_user(db, "u1")
        assert len(remaining) == 1
        assert remaining[0].title == "Recent"

    def test_cleanup_old_nothing_to_delete(self, db: Session):
        NotificationRepository.create(db, user_id="u1", type="info", title="Recent")
        deleted = NotificationRepository.cleanup_old(db, days=30)
        assert deleted == 0


# ── NotificationService DB integration tests ────────────────────────────


class TestNotificationServiceDBIntegration:
    def test_create_with_db_persists(self, db: Session):
        svc = NotificationService()
        notif = svc.create("u1", "task_completed", "Done", "msg", db=db)

        # In-memory
        assert svc.get_all("u1")[0].id == notif.id

        # DB
        db_notifs = NotificationRepository.list_by_user(db, "u1")
        assert len(db_notifs) == 1
        assert db_notifs[0].title == "Done"

    def test_create_without_db_still_works(self, db: Session):
        svc = NotificationService()
        notif = svc.create("u1", "info", "Test", "msg")
        assert svc.get_all("u1")[0].id == notif.id
        # Nothing in DB
        assert NotificationRepository.list_by_user(db, "u1") == []

    def test_mark_read_persists_to_db(self, db: Session):
        svc = NotificationService()
        notif = svc.create("u1", "info", "Test", "msg", db=db)

        found = svc.mark_read("u1", notif.id, db=db)
        assert found is True

        # In-memory
        assert svc.get_unread_count("u1") == 0

        # DB — the DB row has its own ID, so look it up by user
        db_notifs = NotificationRepository.list_by_user(db, "u1")
        assert len(db_notifs) == 1
        assert db_notifs[0].read is True

    def test_mark_all_read_persists_to_db(self, db: Session):
        svc = NotificationService()
        svc.create("u1", "info", "A", "m", db=db)
        svc.create("u1", "info", "B", "m", db=db)

        count = svc.mark_all_read("u1", db=db)
        assert count == 2
        assert NotificationRepository.get_unread_count(db, "u1") == 0

    def test_clear_persists_to_db(self, db: Session):
        svc = NotificationService()
        svc.create("u1", "info", "A", "m", db=db)
        svc.create("u1", "info", "B", "m", db=db)

        deleted = svc.clear("u1", db=db)
        assert deleted == 2
        assert NotificationRepository.list_by_user(db, "u1") == []

    def test_load_from_db(self, db: Session):
        # Seed DB directly
        NotificationRepository.create(db, user_id="u1", type="task_failed", title="Failed", message="err")

        svc = NotificationService()
        restored = svc.load_from_db(db, "u1")
        assert len(restored) == 1
        assert restored[0].title == "Failed"
        assert restored[0].type == "task_failed"

        # In-memory cache is now populated
        assert svc.get_all("u1")[0].title == "Failed"

    def test_load_from_db_replaces_in_memory(self, db: Session):
        svc = NotificationService()
        svc.create("u1", "info", "In-mem only", "msg")

        NotificationRepository.create(db, user_id="u1", type="info", title="From DB")

        svc.load_from_db(db, "u1")
        all_notifs = svc.get_all("u1")
        assert len(all_notifs) == 1
        assert all_notifs[0].title == "From DB"

    def test_persist_to_db_failure_does_not_raise(self, db: Session):
        """persist_to_db should swallow exceptions so in-memory still works."""
        svc = NotificationService()
        notif = Notification(
            id=str(uuid.uuid4()),
            type="info",
            title="Test",
            message="msg",
            data=None,
            created_at=datetime.now(UTC).isoformat(),
            read=False,
        )
        # Close the session to force a DB error
        db.close()
        # Should not raise
        svc.persist_to_db(db, notif, "u1")
        # In-memory unaffected
        assert svc.get_all("u1") == []
