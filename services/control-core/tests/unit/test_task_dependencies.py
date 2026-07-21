"""Unit tests for TaskDependencyRepository and task dependency API routes."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api_server.routes.task_dependencies import (
    DependencyCreate,
    ExecutionOrderRequest,
    add_dependency,
    execution_order,
    list_dependencies,
    list_dependents,
    remove_dependency,
)
from packages.agent_core.schemas import TaskCreate, TaskUpdate
from packages.db.models import Base, Task, TaskDependency, TaskStatus
from packages.db.repositories.task_dependency_repo import TaskDependencyRepository
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


def _create_three_tasks(db: Session):
    """Create three tasks A, B, C and return them."""
    a = _create_task(db, "Task A")
    b = _create_task(db, "Task B")
    c = _create_task(db, "Task C")
    return a, b, c


# ═══════════════════════════════════════════════════════════════════════════
# TaskDependencyRepository — add / remove / list
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestAddDependency:
    def test_add_dependency(self, db):
        a, b, _ = _create_three_tasks(db)
        dep = TaskDependencyRepository.add_dependency(db, a.id, b.id)
        assert dep.task_id == a.id
        assert dep.depends_on_id == b.id
        assert dep.id is not None
        assert dep.created_at is not None

    def test_add_dependency_creates_row(self, db):
        a, b, _ = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        rows = list(db.scalars(
            __import__("sqlalchemy").select(TaskDependency)
        ).all())
        assert len(rows) == 1


@pytest.mark.unit
class TestRemoveDependency:
    def test_remove_existing(self, db):
        a, b, _ = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        removed = TaskDependencyRepository.remove_dependency(db, a.id, b.id)
        assert removed is True

    def test_remove_nonexistent(self, db):
        a, b, _ = _create_three_tasks(db)
        removed = TaskDependencyRepository.remove_dependency(db, a.id, b.id)
        assert removed is False


@pytest.mark.unit
class TestGetDependencies:
    def test_get_dependencies(self, db):
        a, b, c = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        TaskDependencyRepository.add_dependency(db, a.id, c.id)
        deps = TaskDependencyRepository.get_dependencies(db, a.id)
        assert len(deps) == 2
        dep_ids = {d.depends_on_id for d in deps}
        assert dep_ids == {b.id, c.id}

    def test_get_dependencies_empty(self, db):
        a = _create_task(db, "solo")
        deps = TaskDependencyRepository.get_dependencies(db, a.id)
        assert deps == []


@pytest.mark.unit
class TestGetDependents:
    def test_get_dependents(self, db):
        a, b, c = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, c.id)
        TaskDependencyRepository.add_dependency(db, b.id, c.id)
        deps = TaskDependencyRepository.get_dependents(db, c.id)
        assert len(deps) == 2
        task_ids = {d.task_id for d in deps}
        assert task_ids == {a.id, b.id}

    def test_get_dependents_empty(self, db):
        a = _create_task(db, "solo")
        deps = TaskDependencyRepository.get_dependents(db, a.id)
        assert deps == []


# ═══════════════════════════════════════════════════════════════════════════
# Cycle detection
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestCycleDetection:
    def test_self_dependency(self, db):
        a = _create_task(db, "self")
        assert TaskDependencyRepository.detect_cycle(db, a.id, a.id) is True

    def test_no_cycle(self, db):
        a, b, _ = _create_three_tasks(db)
        # A depends on B — no cycle
        assert TaskDependencyRepository.detect_cycle(db, a.id, b.id) is False

    def test_direct_cycle(self, db):
        """A depends on B, then B depends on A would be a cycle."""
        a, b, _ = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        # Adding B depends on A would create A->B->A
        assert TaskDependencyRepository.detect_cycle(db, b.id, a.id) is True

    def test_indirect_cycle(self, db):
        """A->B->C chain; adding C depends on A creates a cycle."""
        a, b, c = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        TaskDependencyRepository.add_dependency(db, b.id, c.id)
        # C depends on A: A->B->C->A cycle
        assert TaskDependencyRepository.detect_cycle(db, c.id, a.id) is True

    def test_no_cycle_with_chain(self, db):
        """A->B, B->C: A depends on C is fine (no cycle)."""
        a, b, c = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        TaskDependencyRepository.add_dependency(db, b.id, c.id)
        # A depends on C — extends the chain, no cycle
        assert TaskDependencyRepository.detect_cycle(db, a.id, c.id) is False


# ═══════════════════════════════════════════════════════════════════════════
# Execution order (topological sort)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestExecutionOrder:
    def test_empty_list(self, db):
        result = TaskDependencyRepository.get_execution_order(db, [])
        assert result == []

    def test_single_task(self, db):
        a = _create_task(db, "solo")
        result = TaskDependencyRepository.get_execution_order(db, [a.id])
        assert result == [a.id]

    def test_simple_chain(self, db):
        """A depends on B, B depends on C. Order: C, B, A."""
        a, b, c = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        TaskDependencyRepository.add_dependency(db, b.id, c.id)
        order = TaskDependencyRepository.get_execution_order(db, [a.id, b.id, c.id])
        assert order.index(c.id) < order.index(b.id)
        assert order.index(b.id) < order.index(a.id)

    def test_parallel_tasks(self, db):
        """A and B both depend on C. C must come first; A, B order is flexible."""
        a, b, c = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, c.id)
        TaskDependencyRepository.add_dependency(db, b.id, c.id)
        order = TaskDependencyRepository.get_execution_order(db, [a.id, b.id, c.id])
        assert order.index(c.id) < order.index(a.id)
        assert order.index(c.id) < order.index(b.id)
        assert len(order) == 3

    def test_diamond_pattern(self, db):
        """D depends on B and C; B depends on A; C depends on A.
        Valid order: A first, then B and C, then D."""
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        c = _create_task(db, "C")
        d = _create_task(db, "D")
        TaskDependencyRepository.add_dependency(db, b.id, a.id)
        TaskDependencyRepository.add_dependency(db, c.id, a.id)
        TaskDependencyRepository.add_dependency(db, d.id, b.id)
        TaskDependencyRepository.add_dependency(db, d.id, c.id)
        order = TaskDependencyRepository.get_execution_order(db, [a.id, b.id, c.id, d.id])
        assert order.index(a.id) < order.index(b.id)
        assert order.index(a.id) < order.index(c.id)
        assert order.index(b.id) < order.index(d.id)
        assert order.index(c.id) < order.index(d.id)

    def test_disconnected_graphs(self, db):
        """Two independent chains: A->B and C->D. All four in one call."""
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        c = _create_task(db, "C")
        d = _create_task(db, "D")
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        TaskDependencyRepository.add_dependency(db, c.id, d.id)
        order = TaskDependencyRepository.get_execution_order(db, [a.id, b.id, c.id, d.id])
        assert order.index(b.id) < order.index(a.id)
        assert order.index(d.id) < order.index(c.id)
        assert len(order) == 4

    def test_no_dependencies_all_parallel(self, db):
        """Four tasks with no dependencies — any order is valid."""
        ids = [_create_task(db, f"T{i}").id for i in range(4)]
        order = TaskDependencyRepository.get_execution_order(db, ids)
        assert set(order) == set(ids)
        assert len(order) == 4


# ═══════════════════════════════════════════════════════════════════════════
# Recursive dependency resolution
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestRecursiveDependencies:
    def test_chain_resolution(self, db):
        """A->B->C: recursive deps of A are [B, C]."""
        a, b, c = _create_three_tasks(db)
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        TaskDependencyRepository.add_dependency(db, b.id, c.id)
        result = TaskDependencyRepository.get_all_dependencies_recursive(db, a.id)
        assert b.id in result
        assert c.id in result

    def test_diamond_no_duplicates(self, db):
        """D->B->A, D->C->A: recursive deps of D include A, B, C (no dupes)."""
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        c = _create_task(db, "C")
        d = _create_task(db, "D")
        TaskDependencyRepository.add_dependency(db, b.id, a.id)
        TaskDependencyRepository.add_dependency(db, c.id, a.id)
        TaskDependencyRepository.add_dependency(db, d.id, b.id)
        TaskDependencyRepository.add_dependency(db, d.id, c.id)
        result = TaskDependencyRepository.get_all_dependencies_recursive(db, d.id)
        assert len(result) == len(set(result))  # no duplicates
        assert set(result) == {a.id, b.id, c.id}

    def test_no_deps(self, db):
        a = _create_task(db, "leaf")
        result = TaskDependencyRepository.get_all_dependencies_recursive(db, a.id)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════
# API route tests (direct function calls, no HTTP client)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestAddDependencyRoute:
    def test_add_dependency_success(self, db):
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        result = add_dependency(a.id, DependencyCreate(depends_on_id=b.id), db=db)
        assert result["success"] is True
        assert result["data"]["task_id"] == a.id
        assert result["data"]["depends_on_id"] == b.id

    def test_add_dependency_nonexistent_task(self, db):
        b = _create_task(db, "B")
        with pytest.raises(HTTPException) as exc_info:
            add_dependency("nonexistent", DependencyCreate(depends_on_id=b.id), db=db)
        assert exc_info.value.status_code == 404

    def test_add_dependency_nonexistent_dep(self, db):
        a = _create_task(db, "A")
        with pytest.raises(HTTPException) as exc_info:
            add_dependency(a.id, DependencyCreate(depends_on_id="nonexistent"), db=db)
        assert exc_info.value.status_code == 404

    def test_add_self_dependency_rejected(self, db):
        a = _create_task(db, "A")
        with pytest.raises(HTTPException) as exc_info:
            add_dependency(a.id, DependencyCreate(depends_on_id=a.id), db=db)
        assert exc_info.value.status_code == 400
        assert "itself" in exc_info.value.detail.lower()

    def test_add_cycle_rejected(self, db):
        """A->B exists; adding B->A should be rejected."""
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        with pytest.raises(HTTPException) as exc_info:
            add_dependency(b.id, DependencyCreate(depends_on_id=a.id), db=db)
        assert exc_info.value.status_code == 400
        assert "cycle" in exc_info.value.detail.lower()


@pytest.mark.unit
class TestRemoveDependencyRoute:
    def test_remove_dependency_success(self, db):
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        result = remove_dependency(a.id, b.id, db=db)
        assert result["success"] is True

    def test_remove_dependency_not_found(self, db):
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        with pytest.raises(HTTPException) as exc_info:
            remove_dependency(a.id, b.id, db=db)
        assert exc_info.value.status_code == 404


@pytest.mark.unit
class TestListDependenciesRoute:
    def test_list_dependencies(self, db):
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        result = list_dependencies(a.id, db=db)
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["depends_on_id"] == b.id

    def test_list_dependencies_empty(self, db):
        a = _create_task(db, "A")
        result = list_dependencies(a.id, db=db)
        assert result["success"] is True
        assert result["data"] == []


@pytest.mark.unit
class TestListDependentsRoute:
    def test_list_dependents(self, db):
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        result = list_dependents(b.id, db=db)
        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["task_id"] == a.id


@pytest.mark.unit
class TestExecutionOrderRoute:
    def test_execution_order(self, db):
        a = _create_task(db, "A")
        b = _create_task(db, "B")
        c = _create_task(db, "C")
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        TaskDependencyRepository.add_dependency(db, b.id, c.id)
        result = execution_order(
            ExecutionOrderRequest(task_ids=[a.id, b.id, c.id]), db=db
        )
        assert result["success"] is True
        order = result["data"]["task_ids"]
        assert order.index(c.id) < order.index(b.id)
        assert order.index(b.id) < order.index(a.id)

    def test_execution_order_empty(self, db):
        result = execution_order(
            ExecutionOrderRequest(task_ids=[]), db=db
        )
        assert result["success"] is True
        assert result["data"]["task_ids"] == []
