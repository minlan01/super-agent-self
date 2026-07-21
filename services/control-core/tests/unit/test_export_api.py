"""Unit tests for export endpoints — JSON and CSV export of tasks, memories, audit."""

from __future__ import annotations

import asyncio
import csv
import io

import pytest
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api_server.routes.export import (
    _audit_to_dict,
    _memory_to_dict,
    _task_to_dict,
    _to_csv_rows,
    export_audit,
    export_memories,
    export_tasks,
)
from packages.agent_core.schemas import AuditEventCreate, TaskCreate, TaskUpdate
from packages.db.models import (
    AuditEvent,
    AuditEventType,
    Base,
    Memory,
    MemoryType,
    TaskStatus,
)
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


@pytest.fixture
def db_with_data(db):
    """Seed DB with tasks, memories, and audit events."""
    # Tasks
    t1 = TaskRepository.create(db, TaskCreate(goal="Task A"))
    t2 = TaskRepository.create(db, TaskCreate(goal="Task B"))
    TaskRepository.update(db, t2.id, TaskUpdate(status=TaskStatus.COMPLETED))

    # Memories
    db.add(Memory(
        title="Memory 1", summary="summary-1", memory_type=MemoryType.EXECUTION_EXPERIENCE,
        is_active=True, user_id="default",
    ))
    db.add(Memory(
        title="Memory 2", summary="summary-2", memory_type=MemoryType.DOMAIN_KNOWLEDGE,
        is_active=False, user_id="default",
    ))
    db.flush()

    # Audit events
    AuditRepository.create(db, AuditEventCreate(
        task_id=t1.id, event_type=AuditEventType.TASK_CREATED,
        detail={"goal": "Task A"},
    ))
    AuditRepository.create(db, AuditEventCreate(
        task_id=t2.id, event_type=AuditEventType.TASK_COMPLETED,
        detail={"goal": "Task B"},
    ))
    db.flush()
    return db


def _read_csv_body(response: StreamingResponse) -> str:
    """Extract body from a StreamingResponse (async body_iterator) via asyncio."""

    async def _collect():
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        return body.decode("utf-8")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # If already in async context, create a task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, _collect()).result()
    else:
        return asyncio.run(_collect())


# ── Helper functions ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestExportHelpers:
    """Direct tests for the internal serialization helpers."""

    def test_to_csv_rows_empty(self):
        assert _to_csv_rows([]) == ""

    def test_to_csv_rows_single(self):
        rows = [{"id": "1", "goal": "test"}]
        result = _to_csv_rows(rows)
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert header == ["id", "goal"]
        data = next(reader)
        assert data == ["1", "test"]

    def test_task_to_dict(self, db):
        task = TaskRepository.create(db, TaskCreate(goal="test"))
        d = _task_to_dict(task)
        assert d["goal"] == "test"
        assert d["status"] == "pending"
        assert "created_at" in d

    def test_memory_to_dict(self, db):
        db.add(Memory(
            title="M", summary="s", memory_type=MemoryType.ERROR_SOLUTION,
            is_active=True, user_id="u",
        ))
        db.flush()
        mem = db.query(Memory).first()
        d = _memory_to_dict(mem)
        assert d["title"] == "M"
        assert d["memory_type"] == "error_solution"

    def test_audit_to_dict(self, db):
        t = TaskRepository.create(db, TaskCreate(goal="audit test"))
        AuditRepository.create(db, AuditEventCreate(
            task_id=t.id, event_type=AuditEventType.TASK_CREATED,
            detail={"goal": "audit test"},
        ))
        evt = db.query(AuditEvent).first()
        d = _audit_to_dict(evt)
        assert d["event_type"] == "task_created"


# ── export_tasks ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExportTasks:
    def test_export_tasks_json(self, db_with_data):
        result = export_tasks(format="json", limit=1000, db=db_with_data)
        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["data"]) == 2
        goals = [item["goal"] for item in result["data"]]
        assert "Task A" in goals
        assert "Task B" in goals

    def test_export_tasks_csv(self, db_with_data):
        result = export_tasks(format="csv", limit=1000, db=db_with_data)
        assert isinstance(result, StreamingResponse)
        csv_text = _read_csv_body(result)
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        assert len(rows) == 2
        goals = [r["goal"] for r in rows]
        assert "Task A" in goals
        assert "Task B" in goals

    def test_export_tasks_csv_headers(self, db_with_data):
        result = export_tasks(format="csv", limit=1000, db=db_with_data)
        csv_text = _read_csv_body(result)
        reader = csv.reader(io.StringIO(csv_text))
        headers = next(reader)
        assert "id" in headers
        assert "goal" in headers
        assert "status" in headers
        assert "edition" in headers
        assert "user_id" in headers
        assert "created_at" in headers

    def test_export_empty_tasks(self, db):
        """Empty DB returns count=0 and empty list for JSON."""
        result = export_tasks(format="json", limit=1000, db=db)
        assert result["success"] is True
        assert result["count"] == 0
        assert result["data"] == []


# ── export_memories ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestExportMemories:
    def test_export_memories_json(self, db_with_data):
        result = export_memories(format="json", limit=1000, db=db_with_data)
        assert result["success"] is True
        assert result["count"] == 2
        titles = [item["title"] for item in result["data"]]
        assert "Memory 1" in titles
        assert "Memory 2" in titles

    def test_export_memories_csv(self, db_with_data):
        result = export_memories(format="csv", limit=1000, db=db_with_data)
        assert isinstance(result, StreamingResponse)
        csv_text = _read_csv_body(result)
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        assert len(rows) == 2
        titles = [r["title"] for r in rows]
        assert set(titles) == {"Memory 1", "Memory 2"}


# ── export_audit ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExportAudit:
    def test_export_audit_json(self, db_with_data):
        result = export_audit(format="json", limit=1000, db=db_with_data)
        assert result["success"] is True
        assert result["count"] == 2
        event_types = [item["event_type"] for item in result["data"]]
        assert "task_created" in event_types
        assert "task_completed" in event_types

    def test_export_audit_csv(self, db_with_data):
        result = export_audit(format="csv", limit=1000, db=db_with_data)
        assert isinstance(result, StreamingResponse)
        csv_text = _read_csv_body(result)
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        assert len(rows) == 2
