"""Unit tests for task retry and batch creation routes."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api_server.routes.tasks import BatchTaskCreate, batch_create_tasks, retry_task
from packages.agent_core.schemas import TaskCreate, TaskUpdate
from packages.db.models import AuditEventType, Base, Task, TaskStatus
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.task_repo import TaskRepository

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


def _create_task(db: Session, goal: str, status: TaskStatus = TaskStatus.PENDING) -> Task:
    """Helper: create a task via the repository."""
    task = TaskRepository.create(db, TaskCreate(goal=goal))
    if status != TaskStatus.PENDING:
        TaskRepository.update(db, task.id, TaskUpdate(status=status))
    return db.get(Task, task.id)


# ── retry_task ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestRetryTask:
    def test_retry_failed_task(self, db):
        task = _create_task(db, "will fail", status=TaskStatus.FAILED)
        result = retry_task(task_id=task.id, db=db)
        assert result.data.status == TaskStatus.PENDING

    def test_retry_completed_task(self, db):
        task = _create_task(db, "done already", status=TaskStatus.COMPLETED)
        result = retry_task(task_id=task.id, db=db)
        assert result.data.status == TaskStatus.PENDING

    def test_retry_pending_task_fails(self, db):
        """Pending tasks cannot be retried."""
        task = _create_task(db, "still waiting", status=TaskStatus.PENDING)
        with pytest.raises(HTTPException) as exc_info:
            retry_task(task_id=task.id, db=db)
        assert exc_info.value.status_code == 400

    def test_retry_nonexistent_task(self, db):
        with pytest.raises(HTTPException) as exc_info:
            retry_task(task_id="nonexistent-id", db=db)
        assert exc_info.value.status_code == 404

    def test_retry_creates_audit_event(self, db):
        """Retrying a task should create an audit event with retried=True."""
        task = _create_task(db, "audit check", status=TaskStatus.FAILED)
        retry_task(task_id=task.id, db=db)

        events = AuditRepository.list_by_task(db, task.id)
        retry_events = [e for e in events if e.detail and e.detail.get("retried")]
        assert len(retry_events) >= 1
        assert retry_events[0].detail["retried"] is True


# ── batch_create_tasks ────────────────────────────────────────────────────


@pytest.mark.unit
class TestBatchCreateTasks:
    def test_batch_create_tasks(self, db):
        body = BatchTaskCreate(
            tasks=[
                TaskCreate(goal="batch task 1"),
                TaskCreate(goal="batch task 2"),
                TaskCreate(goal="batch task 3"),
            ]
        )
        result = batch_create_tasks(body=body, db=db)
        assert result.count == 3
        assert len(result.created) == 3

    def test_batch_create_empty_list(self, db):
        body = BatchTaskCreate(tasks=[])
        with pytest.raises(HTTPException) as exc_info:
            batch_create_tasks(body=body, db=db)
        assert exc_info.value.status_code == 400

    def test_batch_create_over_limit(self, db):
        """51 tasks should fail (limit is 50)."""
        tasks = [TaskCreate(goal=f"task-{i}") for i in range(51)]
        body = BatchTaskCreate(tasks=tasks)
        with pytest.raises(HTTPException) as exc_info:
            batch_create_tasks(body=body, db=db)
        assert exc_info.value.status_code == 400
        assert "50" in exc_info.value.detail

    def test_batch_create_at_limit(self, db):
        """Exactly 50 tasks should succeed."""
        tasks = [TaskCreate(goal=f"task-{i}") for i in range(50)]
        body = BatchTaskCreate(tasks=tasks)
        result = batch_create_tasks(body=body, db=db)
        assert result.count == 50

    def test_batch_creates_audit_events(self, db):
        """Each batch-created task should have an audit event."""
        body = BatchTaskCreate(
            tasks=[
                TaskCreate(goal="audited task 1"),
                TaskCreate(goal="audited task 2"),
            ]
        )
        result = batch_create_tasks(body=body, db=db)

        for task_resp in result.created:
            events = AuditRepository.list_by_task(db, task_resp.id)
            created_events = [e for e in events if e.event_type == AuditEventType.TASK_CREATED]
            assert len(created_events) == 1
            assert created_events[0].detail.get("source") == "batch"
