"""Unit tests for audit API route — list audit events with filters."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api_server.routes.audit import list_audit_events
from packages.agent_core.schemas import AuditEventCreate
from packages.db.models import AuditEventType, Base
from packages.db.repositories.audit_repo import AuditRepository

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


def _create_event(db, **overrides) -> None:
    """Helper to create an audit event with sensible defaults."""
    defaults = dict(
        task_id="task-001",
        event_type=AuditEventType.TASK_CREATED,
        actor="system",
        detail={"action": "test"},
    )
    defaults.update(overrides)
    AuditRepository.create(db, AuditEventCreate(**defaults))


# ── list_audit_events ────────────────────────────────────────────────────


@pytest.mark.unit
class TestListAuditEvents:
    def test_empty_list(self, db):
        """No audit events returns empty data."""
        result = list_audit_events(skip=0, limit=50, db=db)
        assert result.data == []

    def test_returns_all_events(self, db):
        """All events are returned when no filters are applied."""
        _create_event(db, task_id="t1", event_type=AuditEventType.TASK_CREATED)
        _create_event(db, task_id="t2", event_type=AuditEventType.TASK_COMPLETED)

        result = list_audit_events(skip=0, limit=50, db=db)
        assert len(result.data) == 2

    def test_filter_by_task_id(self, db):
        """Filtering by task_id returns only matching events."""
        _create_event(db, task_id="t1", event_type=AuditEventType.TASK_CREATED)
        _create_event(db, task_id="t2", event_type=AuditEventType.TASK_COMPLETED)
        _create_event(db, task_id="t1", event_type=AuditEventType.STEP_EXECUTING)

        result = list_audit_events(task_id="t1", skip=0, limit=50, db=db)
        assert len(result.data) == 2
        for event in result.data:
            assert event.task_id == "t1"

    def test_filter_by_event_type(self, db):
        """Filtering by event_type returns only matching events."""
        _create_event(db, event_type=AuditEventType.TASK_CREATED)
        _create_event(db, event_type=AuditEventType.TASK_COMPLETED)
        _create_event(db, event_type=AuditEventType.TASK_CREATED)

        result = list_audit_events(event_type="task_completed", skip=0, limit=50, db=db)
        assert len(result.data) == 1
        assert result.data[0].event_type == AuditEventType.TASK_COMPLETED

    def test_filter_by_task_id_and_event_type(self, db):
        """Both filters applied together narrow results correctly."""
        _create_event(db, task_id="t1", event_type=AuditEventType.TASK_CREATED)
        _create_event(db, task_id="t1", event_type=AuditEventType.TASK_COMPLETED)
        _create_event(db, task_id="t2", event_type=AuditEventType.TASK_CREATED)

        result = list_audit_events(task_id="t1", event_type="task_created", skip=0, limit=50, db=db)
        assert len(result.data) == 1
        assert result.data[0].task_id == "t1"
        assert result.data[0].event_type == AuditEventType.TASK_CREATED

    def test_pagination_skip(self, db):
        """skip parameter skips the first N events."""
        for i in range(5):
            _create_event(db, task_id=f"t{i}")

        result = list_audit_events(skip=3, limit=10, db=db)
        assert len(result.data) == 2  # 5 total - 3 skipped = 2

    def test_pagination_limit(self, db):
        """limit parameter caps returned items."""
        for i in range(10):
            _create_event(db, task_id=f"t{i}")

        result = list_audit_events(skip=0, limit=3, db=db)
        assert len(result.data) == 3

    def test_response_structure(self, db):
        """Response includes success flag and list of events."""
        _create_event(db, event_type=AuditEventType.POLICY_CHECK, actor="policy-engine")

        result = list_audit_events(skip=0, limit=50, db=db)
        assert result.success is True
        assert len(result.data) == 1
        event = result.data[0]
        assert event.event_type == AuditEventType.POLICY_CHECK
        assert event.actor == "policy-engine"
        assert event.detail == {"action": "test"}

    def test_no_match_filters_return_empty(self, db):
        """Filters matching nothing return empty list."""
        _create_event(db, task_id="t1", event_type=AuditEventType.TASK_CREATED)

        result = list_audit_events(task_id="nonexistent", skip=0, limit=50, db=db)
        assert result.data == []

    def test_filter_event_type_with_no_match(self, db):
        """An event_type filter that matches nothing returns empty."""
        _create_event(db, event_type=AuditEventType.TASK_CREATED)

        result = list_audit_events(event_type="task_failed", skip=0, limit=50, db=db)
        assert result.data == []
