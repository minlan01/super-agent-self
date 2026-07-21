"""Unit tests for the DAG graph API endpoint."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api_server.routes.task_dependencies import get_dag_graph
from packages.agent_core.schemas import TaskCreate, TaskUpdate
from packages.db.models import Base, RiskLevel, Task, TaskStatus
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


# ═══════════════════════════════════════════════════════════════════════════
# DAG endpoint tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestGetDAGGraph:
    def test_dag_endpoint_returns_nodes_and_edges_structure(self, db):
        """DAG endpoint returns the expected top-level keys."""
        result = get_dag_graph(db=db)
        assert result["success"] is True
        assert "data" in result
        assert "nodes" in result["data"]
        assert "edges" in result["data"]

    def test_dag_endpoint_empty_database(self, db):
        """DAG endpoint returns empty lists when no tasks exist."""
        result = get_dag_graph(db=db)
        assert result["success"] is True
        assert result["data"]["nodes"] == []
        assert result["data"]["edges"] == []

    def test_dag_endpoint_with_tasks_no_dependencies(self, db):
        """DAG endpoint returns nodes but no edges when tasks exist without deps."""
        _create_task(db, "Task A")
        _create_task(db, "Task B")
        result = get_dag_graph(db=db)
        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 2
        assert len(result["data"]["edges"]) == 0

    def test_dag_endpoint_with_sample_tasks_and_dependencies(self, db):
        """DAG endpoint returns correct nodes and edges with tasks and deps."""
        a = _create_task(db, "Task A", TaskStatus.COMPLETED)
        b = _create_task(db, "Task B", TaskStatus.EXECUTING)
        c = _create_task(db, "Task C", TaskStatus.PENDING)

        # A depends on B, B depends on C
        TaskDependencyRepository.add_dependency(db, a.id, b.id)
        TaskDependencyRepository.add_dependency(db, b.id, c.id)

        result = get_dag_graph(db=db)
        assert result["success"] is True

        nodes = result["data"]["nodes"]
        edges = result["data"]["edges"]

        assert len(nodes) == 3
        assert len(edges) == 2

        # Verify node fields
        node_ids = {n["id"] for n in nodes}
        assert node_ids == {a.id, b.id, c.id}

        node_map = {n["id"]: n for n in nodes}
        assert node_map[a.id]["status"] == "completed"
        assert node_map[b.id]["status"] == "executing"
        assert node_map[c.id]["status"] == "pending"

        # Verify edge direction: source=depends_on, target=dependent
        edge_pairs = {(e["source"], e["target"]) for e in edges}
        assert (b.id, a.id) in edge_pairs
        assert (c.id, b.id) in edge_pairs

    def test_dag_node_name_truncation(self, db):
        """DAG endpoint truncates long goal text to 40 chars."""
        long_goal = "A" * 100
        task = _create_task(db, long_goal)
        result = get_dag_graph(db=db)
        node = result["data"]["nodes"][0]
        assert node["name"] == long_goal[:40] + "..."

    def test_dag_node_name_short_goal(self, db):
        """DAG endpoint does not truncate short goal text."""
        short_goal = "Short task"
        task = _create_task(db, short_goal)
        result = get_dag_graph(db=db)
        node = result["data"]["nodes"][0]
        assert node["name"] == short_goal

    def test_dag_node_risk_level(self, db):
        """DAG endpoint includes risk_level in node data."""
        task = _create_task(db, "Risky task")
        # Manually set risk level
        TaskRepository.update(db, task.id, TaskUpdate(risk_level=RiskLevel.HIGH))
        updated_task = db.get(Task, task.id)

        result = get_dag_graph(db=db)
        node = result["data"]["nodes"][0]
        assert node["risk_level"] == "high"

    def test_dag_node_risk_level_none(self, db):
        """DAG endpoint handles tasks with no risk level."""
        _create_task(db, "Safe task")
        result = get_dag_graph(db=db)
        node = result["data"]["nodes"][0]
        assert node["risk_level"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Node status coloring logic
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestNodeStatusColoring:
    """Verify that status values map correctly for frontend color assignment."""

    STATUS_COLORS = {
        "pending": "#909399",
        "planning": "#409eff",
        "awaiting_approval": "#e6a23c",
        "executing": "#e6a23c",
        "completed": "#67c23a",
        "failed": "#f56c6c",
        "cancelled": "#606266",
    }

    @pytest.mark.parametrize(
        "status,expected_color",
        [
            (TaskStatus.PENDING, "#909399"),
            (TaskStatus.PLANNING, "#409eff"),
            (TaskStatus.AWAITING_APPROVAL, "#e6a23c"),
            (TaskStatus.EXECUTING, "#e6a23c"),
            (TaskStatus.COMPLETED, "#67c23a"),
            (TaskStatus.FAILED, "#f56c6c"),
            (TaskStatus.CANCELLED, "#606266"),
        ],
    )
    def test_status_color_mapping(self, db, status, expected_color):
        """Each TaskStatus maps to the expected frontend color."""
        _create_task(db, f"Task {status.value}", status)
        result = get_dag_graph(db=db)
        node = result["data"]["nodes"][0]
        assert node["status"] == status.value
        # Verify the color mapping is defined for this status
        assert self.STATUS_COLORS[node["status"]] == expected_color

    def test_all_statuses_have_colors(self):
        """Every valid TaskStatus enum value has a color defined."""
        for status in TaskStatus:
            assert status.value in self.STATUS_COLORS, f"Missing color for status: {status.value}"

    def test_mixed_statuses_in_dag(self, db):
        """DAG returns correct status values for a mix of task statuses."""
        statuses = [
            TaskStatus.PENDING,
            TaskStatus.PLANNING,
            TaskStatus.EXECUTING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ]
        for s in statuses:
            _create_task(db, f"Task-{s.value}", s)

        result = get_dag_graph(db=db)
        returned_statuses = {n["status"] for n in result["data"]["nodes"]}
        expected_statuses = {s.value for s in statuses}
        assert returned_statuses == expected_statuses
