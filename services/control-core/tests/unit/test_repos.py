"""Unit tests for repository CRUD operations."""


import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.agent_core.schemas import (
    ApprovalCreate,
    ApprovalResolve,
    ApprovalType,
    AuditEventCreate,
    AuditEventType,
    Edition,
    EditionProfileCreate,
    MemoryCreate,
    MemorySearchQuery,
    MemoryType,
    SkillCreate,
    SkillRunCreate,
    SkillUpdate,
    TaskCreate,
    TaskStepCreate,
    TaskStepUpdate,
    TaskUpdate,
)
from packages.db.models import (
    ApprovalStatus,
    SkillStatus,
    TaskStatus,
)
from packages.db.repositories.approval_repo import ApprovalRepository
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.edition_repo import EditionRepository
from packages.db.repositories.memory_repo import MemoryRepository
from packages.db.repositories.skill_repo import SkillRepository
from packages.db.repositories.task_repo import TaskRepository
from packages.db.session import Base


@pytest.fixture
def db_session():
    """Create a fresh in-memory SQLite session with all tables."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


# ── TaskRepository ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTaskRepository:
    def test_create(self, db_session: Session):
        schema = TaskCreate(goal="Test task creation")
        task = TaskRepository.create(db_session, schema)
        assert task.id is not None
        assert task.goal == "Test task creation"
        assert task.status == TaskStatus.PENDING

    def test_get_by_id(self, db_session: Session):
        task = TaskRepository.create(db_session, TaskCreate(goal="find me"))
        found = TaskRepository.get_by_id(db_session, task.id)
        assert found is not None
        assert found.goal == "find me"

    def test_get_by_id_not_found(self, db_session: Session):
        found = TaskRepository.get_by_id(db_session, "nonexistent-id")
        assert found is None

    def test_list_tasks(self, db_session: Session):
        TaskRepository.create(db_session, TaskCreate(goal="task-1"))
        TaskRepository.create(db_session, TaskCreate(goal="task-2"))
        TaskRepository.create(db_session, TaskCreate(goal="task-3"))
        tasks = TaskRepository.list_tasks(db_session, tenant_id="default")
        assert len(tasks) == 3
        # Ordered by created_at desc, so most recent first
        assert tasks[0].goal == "task-3"

    def test_list_tasks_with_status_filter(self, db_session: Session):
        t1 = TaskRepository.create(db_session, TaskCreate(goal="pending"))
        t2 = TaskRepository.create(db_session, TaskCreate(goal="done"))
        TaskRepository.update(db_session, t2.id, TaskUpdate(status=TaskStatus.COMPLETED))

        pending = TaskRepository.list_tasks(db_session, status=TaskStatus.PENDING, tenant_id="default")
        completed = TaskRepository.list_tasks(db_session, status=TaskStatus.COMPLETED, tenant_id="default")
        assert len(pending) == 1
        assert len(completed) == 1
        assert pending[0].goal == "pending"
        assert completed[0].goal == "done"

    def test_list_tasks_with_edition_filter(self, db_session: Session):
        TaskRepository.create(db_session, TaskCreate(goal="ent", edition=Edition.ENTERPRISE))
        TaskRepository.create(db_session, TaskCreate(goal="per", edition=Edition.PERSONAL))

        ent = TaskRepository.list_tasks(db_session, edition=Edition.ENTERPRISE, tenant_id="default")
        per = TaskRepository.list_tasks(db_session, edition=Edition.PERSONAL, tenant_id="default")
        assert len(ent) == 1
        assert len(per) == 1

    def test_count(self, db_session: Session):
        TaskRepository.create(db_session, TaskCreate(goal="a"))
        TaskRepository.create(db_session, TaskCreate(goal="b"))
        TaskRepository.create(db_session, TaskCreate(goal="c"))
        assert TaskRepository.count(db_session, tenant_id="default") == 3

    def test_count_with_filter(self, db_session: Session):
        t1 = TaskRepository.create(db_session, TaskCreate(goal="a"))
        t2 = TaskRepository.create(db_session, TaskCreate(goal="b"))
        TaskRepository.update(db_session, t2.id, TaskUpdate(status=TaskStatus.COMPLETED))

        assert TaskRepository.count(db_session, status=TaskStatus.PENDING, tenant_id="default") == 1
        assert TaskRepository.count(db_session, status=TaskStatus.COMPLETED, tenant_id="default") == 1

    def test_update(self, db_session: Session):
        task = TaskRepository.create(db_session, TaskCreate(goal="update me"))
        updated = TaskRepository.update(
            db_session, task.id, TaskUpdate(status=TaskStatus.EXECUTING, result="in progress")
        )
        assert updated is not None
        assert updated.status == TaskStatus.EXECUTING
        assert updated.result == "in progress"

    def test_update_not_found(self, db_session: Session):
        result = TaskRepository.update(db_session, "nope", TaskUpdate(status=TaskStatus.COMPLETED))
        assert result is None

    def test_add_step(self, db_session: Session):
        task = TaskRepository.create(db_session, TaskCreate(goal="with steps"))
        step_schema = TaskStepCreate(step_order=0, tool_name="bash", args={"cmd": "ls"})
        step = TaskRepository.add_step(db_session, task.id, step_schema)
        assert step.id is not None
        assert step.task_id == task.id
        assert step.tool_name == "bash"
        assert step.args == {"cmd": "ls"}

    def test_update_step(self, db_session: Session):
        task = TaskRepository.create(db_session, TaskCreate(goal="with steps"))
        step = TaskRepository.add_step(
            db_session, task.id, TaskStepCreate(step_order=0, tool_name="bash")
        )
        updated = TaskRepository.update_step(
            db_session, step.id, TaskStepUpdate(status=TaskStatus.COMPLETED, result="listed files")
        )
        assert updated is not None
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result == "listed files"

    def test_update_step_not_found(self, db_session: Session):
        result = TaskRepository.update_step(db_session, "nope", TaskStepUpdate(result="x"))
        assert result is None

    def test_get_steps(self, db_session: Session):
        task = TaskRepository.create(db_session, TaskCreate(goal="multi"))
        TaskRepository.add_step(db_session, task.id, TaskStepCreate(step_order=0, tool_name="bash"))
        TaskRepository.add_step(db_session, task.id, TaskStepCreate(step_order=1, tool_name="read"))
        TaskRepository.add_step(db_session, task.id, TaskStepCreate(step_order=2, tool_name="write"))

        steps = TaskRepository.get_steps(db_session, task.id)
        assert len(steps) == 3
        assert [s.step_order for s in steps] == [0, 1, 2]
        assert steps[0].tool_name == "bash"
        assert steps[2].tool_name == "write"

    def test_get_steps_empty(self, db_session: Session):
        task = TaskRepository.create(db_session, TaskCreate(goal="no steps"))
        steps = TaskRepository.get_steps(db_session, task.id)
        assert steps == []


# ── AuditRepository ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAuditRepository:
    def test_create(self, db_session: Session):
        schema = AuditEventCreate(event_type=AuditEventType.TASK_CREATED)
        event = AuditRepository.create(db_session, schema)
        assert event.id is not None
        assert event.event_type == AuditEventType.TASK_CREATED

    def test_create_with_task(self, db_session: Session):
        task = TaskRepository.create(db_session, TaskCreate(goal="audited"))
        schema = AuditEventCreate(
            task_id=task.id,
            event_type=AuditEventType.STEP_COMPLETED,
            actor="agent",
            detail={"step": 0},
        )
        event = AuditRepository.create(db_session, schema)
        assert event.task_id == task.id
        assert event.actor == "agent"
        assert event.detail == {"step": 0}

    def test_list_by_task(self, db_session: Session):
        task = TaskRepository.create(db_session, TaskCreate(goal="audited"))
        AuditRepository.create(db_session, AuditEventCreate(task_id=task.id, event_type=AuditEventType.TASK_CREATED))
        AuditRepository.create(db_session, AuditEventCreate(task_id=task.id, event_type=AuditEventType.PLAN_GENERATED))
        # Unrelated event
        AuditRepository.create(db_session, AuditEventCreate(event_type=AuditEventType.MEMORY_WRITTEN))

        events = AuditRepository.list_by_task(db_session, task.id)
        assert len(events) == 2
        types = [e.event_type for e in events]
        assert AuditEventType.TASK_CREATED in types
        assert AuditEventType.PLAN_GENERATED in types

    def test_list_by_task_empty(self, db_session: Session):
        events = AuditRepository.list_by_task(db_session, "no-task")
        assert events == []


# ── MemoryRepository ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestMemoryRepository:
    def _create_schema(self, **overrides):
        defaults = {
            "memory_type": MemoryType.DOMAIN_KNOWLEDGE,
            "title": "Test memory",
            "summary": "A test memory entry",
        }
        defaults.update(overrides)
        return MemoryCreate(**defaults)

    def test_create(self, db_session: Session):
        schema = self._create_schema()
        memory = MemoryRepository.create(db_session, "user-1", "enterprise", schema)
        assert memory.id is not None
        assert memory.user_id == "user-1"
        assert memory.title == "Test memory"
        assert memory.is_active is True

    def test_search_by_keyword(self, db_session: Session):
        MemoryRepository.create(db_session, "user-1", "enterprise", self._create_schema(title="Python tips", summary="Use list comprehensions"))
        MemoryRepository.create(db_session, "user-1", "enterprise", self._create_schema(title="SQLAlchemy tips", summary="ORM patterns"))
        MemoryRepository.create(db_session, "user-1", "enterprise", self._create_schema(title="Docker guide", summary="Container basics"))

        query = MemorySearchQuery(keyword="tips")
        results = MemoryRepository.search(db_session, query, "user-1", "enterprise")
        assert len(results) == 2
        titles = {r.title for r in results}
        assert "Python tips" in titles
        assert "SQLAlchemy tips" in titles

    def test_search_by_type(self, db_session: Session):
        MemoryRepository.create(db_session, "user-1", "enterprise", self._create_schema(memory_type=MemoryType.DOMAIN_KNOWLEDGE))
        MemoryRepository.create(db_session, "user-1", "enterprise", self._create_schema(memory_type=MemoryType.ERROR_SOLUTION))

        query = MemorySearchQuery(memory_type=MemoryType.ERROR_SOLUTION)
        results = MemoryRepository.search(db_session, query, "user-1", "enterprise")
        assert len(results) == 1
        assert results[0].memory_type == MemoryType.ERROR_SOLUTION

    def test_search_filters_inactive(self, db_session: Session):
        m1 = MemoryRepository.create(db_session, "user-1", "enterprise", self._create_schema(title="active"))
        m2 = MemoryRepository.create(db_session, "user-1", "enterprise", self._create_schema(title="inactive"))
        MemoryRepository.disable(db_session, m2.id)

        query = MemorySearchQuery(is_active=True)
        results = MemoryRepository.search(db_session, query, "user-1", "enterprise")
        assert len(results) == 1
        assert results[0].title == "active"

    def test_disable(self, db_session: Session):
        memory = MemoryRepository.create(db_session, "user-1", "enterprise", self._create_schema())
        assert memory.is_active is True

        disabled = MemoryRepository.disable(db_session, memory.id)
        assert disabled is not None
        assert disabled.is_active is False

    def test_disable_not_found(self, db_session: Session):
        result = MemoryRepository.disable(db_session, "nope")
        assert result is None

    def test_delete(self, db_session: Session):
        memory = MemoryRepository.create(db_session, "user-1", "enterprise", self._create_schema())
        memory_id = memory.id

        deleted = MemoryRepository.delete(db_session, memory_id)
        assert deleted is True
        assert MemoryRepository.get_by_id(db_session, memory_id) is None

    def test_delete_not_found(self, db_session: Session):
        deleted = MemoryRepository.delete(db_session, "nope")
        assert deleted is False

    def test_search_respects_limit(self, db_session: Session):
        for i in range(5):
            score = round(i * 0.2, 1)  # 0.0, 0.2, 0.4, 0.6, 0.8 — within [0.0, 1.0]
            MemoryRepository.create(
                db_session, "user-1", "enterprise",
                self._create_schema(title=f"Memory {i}", importance_score=score),
            )

        query = MemorySearchQuery(limit=2)
        results = MemoryRepository.search(db_session, query, "user-1", "enterprise")
        assert len(results) == 2
        # Ordered by importance_score desc
        assert results[0].importance_score == 0.8
        assert results[1].importance_score == 0.6


# ── SkillRepository ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSkillRepository:
    def _create_schema(self, **overrides):
        defaults = {
            "name": "test-skill",
            "definition": {"trigger": "test", "steps": []},
        }
        defaults.update(overrides)
        return SkillCreate(**defaults)

    def test_create(self, db_session: Session):
        schema = self._create_schema()
        skill = SkillRepository.create(db_session, schema)
        assert skill.id is not None
        assert skill.name == "test-skill"
        assert skill.status == SkillStatus.CANDIDATE
        assert skill.version == 1

    def test_add_run(self, db_session: Session):
        skill = SkillRepository.create(db_session, self._create_schema())
        run_schema = SkillRunCreate(
            skill_id=skill.id,
            task_id="task-001",
            success=True,
            metrics={"duration_ms": 200},
        )
        run = SkillRepository.add_run(db_session, skill.id, run_schema)
        assert run.id is not None
        assert run.skill_id == skill.id
        assert run.success is True
        assert run.metrics == {"duration_ms": 200}

    def test_add_run_failure(self, db_session: Session):
        skill = SkillRepository.create(db_session, self._create_schema())
        run_schema = SkillRunCreate(
            skill_id=skill.id,
            task_id="task-002",
            success=False,
            error="Connection refused",
        )
        run = SkillRepository.add_run(db_session, skill.id, run_schema)
        assert run.success is False
        assert run.error == "Connection refused"

    def test_update_status(self, db_session: Session):
        skill = SkillRepository.create(db_session, self._create_schema())
        updated = SkillRepository.update(
            db_session, skill.id, SkillUpdate(status=SkillStatus.STABLE)
        )
        assert updated is not None
        assert updated.status == SkillStatus.STABLE

    def test_update_description(self, db_session: Session):
        skill = SkillRepository.create(db_session, self._create_schema())
        updated = SkillRepository.update(
            db_session, skill.id, SkillUpdate(description="A useful skill")
        )
        assert updated is not None
        assert updated.description == "A useful skill"

    def test_update_not_found(self, db_session: Session):
        result = SkillRepository.update(db_session, "nope", SkillUpdate(status=SkillStatus.STABLE))
        assert result is None

    def test_get_runs(self, db_session: Session):
        skill = SkillRepository.create(db_session, self._create_schema())
        SkillRepository.add_run(db_session, skill.id, SkillRunCreate(skill_id=skill.id, task_id="t1", success=True))
        SkillRepository.add_run(db_session, skill.id, SkillRunCreate(skill_id=skill.id, task_id="t2", success=False))

        runs = SkillRepository.get_runs(db_session, skill.id)
        assert len(runs) == 2
        # Ordered by created_at desc
        assert runs[0].task_id == "t2"
        assert runs[1].task_id == "t1"


# ── ApprovalRepository ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestApprovalRepository:
    def _create_schema(self, **overrides):
        defaults = {
            "approval_type": ApprovalType.SKILL,
            "target_id": "skill-001",
        }
        defaults.update(overrides)
        return ApprovalCreate(**defaults)

    def test_create(self, db_session: Session):
        schema = self._create_schema()
        approval = ApprovalRepository.create(db_session, schema)
        assert approval.id is not None
        assert approval.status == ApprovalStatus.PENDING
        assert approval.approval_type == ApprovalType.SKILL

    def test_list_pending(self, db_session: Session):
        a1 = ApprovalRepository.create(db_session, self._create_schema(target_id="s1"))
        ApprovalRepository.create(db_session, self._create_schema(target_id="s2"))
        # Resolve one
        ApprovalRepository.resolve(db_session, a1.id, ApprovalResolve(approved=True, approved_by="admin"))

        pending = ApprovalRepository.list_pending(db_session)
        assert len(pending) == 1
        assert pending[0].target_id == "s2"

    def test_list_pending_with_edition(self, db_session: Session):
        ApprovalRepository.create(db_session, self._create_schema(edition=Edition.ENTERPRISE, target_id="e1"))
        ApprovalRepository.create(db_session, self._create_schema(edition=Edition.PERSONAL, target_id="p1"))

        ent = ApprovalRepository.list_pending(db_session, edition=Edition.ENTERPRISE)
        per = ApprovalRepository.list_pending(db_session, edition=Edition.PERSONAL)
        assert len(ent) == 1
        assert len(per) == 1

    def test_resolve_approve(self, db_session: Session):
        approval = ApprovalRepository.create(db_session, self._create_schema())
        resolved = ApprovalRepository.resolve(
            db_session, approval.id, ApprovalResolve(approved=True, approved_by="admin", reason="Looks good")
        )
        assert resolved is not None
        assert resolved.status == ApprovalStatus.APPROVED
        assert resolved.approved_by == "admin"
        assert resolved.reason == "Looks good"
        assert resolved.resolved_at is not None

    def test_resolve_reject(self, db_session: Session):
        approval = ApprovalRepository.create(db_session, self._create_schema())
        resolved = ApprovalRepository.resolve(
            db_session, approval.id, ApprovalResolve(approved=False, approved_by="admin", reason="Too risky")
        )
        assert resolved is not None
        assert resolved.status == ApprovalStatus.REJECTED
        assert resolved.reason == "Too risky"

    def test_resolve_not_found(self, db_session: Session):
        result = ApprovalRepository.resolve(db_session, "nope", ApprovalResolve(approved=True, approved_by="admin"))
        assert result is None


# ── EditionRepository ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestEditionRepository:
    def test_create(self, db_session: Session):
        schema = EditionProfileCreate(
            edition=Edition.ENTERPRISE,
            name="default-enterprise",
            config={"max_tasks": 10},
        )
        profile = EditionRepository.create(db_session, schema)
        assert profile.id is not None
        assert profile.edition == Edition.ENTERPRISE
        assert profile.name == "default-enterprise"
        assert profile.config == {"max_tasks": 10}
        assert profile.is_active is True

    def test_get_active(self, db_session: Session):
        EditionRepository.create(
            db_session,
            EditionProfileCreate(edition=Edition.ENTERPRISE, name="active", config={"a": 1}),
        )
        EditionRepository.create(
            db_session,
            EditionProfileCreate(edition=Edition.PERSONAL, name="personal", config={"b": 2}),
        )

        active = EditionRepository.get_active(db_session, "enterprise")
        assert active is not None
        assert active.name == "active"

    def test_get_active_returns_none_when_inactive(self, db_session: Session):
        profile = EditionRepository.create(
            db_session,
            EditionProfileCreate(edition=Edition.ENTERPRISE, name="old", config={"a": 1}),
        )
        # Manually deactivate since no disable method exists
        profile.is_active = False
        db_session.commit()

        active = EditionRepository.get_active(db_session, "enterprise")
        assert active is None

    def test_get_active_no_match(self, db_session: Session):
        active = EditionRepository.get_active(db_session, "nonexistent")
        assert active is None
