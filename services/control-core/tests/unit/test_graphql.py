"""Tests for the GraphQL query layer."""

import os

import pytest
from fastapi.testclient import TestClient

# Ensure TESTING mode before importing app
os.environ["TESTING"] = "1"

from packages.db.models import (
    AuditEvent,
    Edition,
    Memory,
    MemoryType,
    RiskLevel,
    Skill,
    SkillStatus,
    StepStatus,
    Task,
    TaskStatus,
    TaskStep,
)
from packages.db.session import SessionLocal

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_db():
    """Create all tables fresh for each test."""
    from packages.db.session import Base, engine
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    """TestClient with a clean DB per test."""
    from apps.api_server.main import app
    from packages.config import get_settings
    settings = get_settings()
    settings.security.require_auth = False
    return TestClient(app)


@pytest.fixture()
def db():
    """Provide a DB session that is cleaned up after the test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed_task(db, **overrides):
    """Helper to create a task in the DB."""
    defaults = {
        "id": "task-001",
        "goal": "Test task",
        "status": TaskStatus.COMPLETED,
        "edition": Edition.ENTERPRISE,
    }
    defaults.update(overrides)
    task = Task(**defaults)
    db.add(task)
    db.commit()
    return task


def _seed_step(db, task_id="task-001", **overrides):
    """Helper to create a task step in the DB."""
    defaults = {
        "id": "step-001",
        "task_id": task_id,
        "step_order": 1,
        "tool_name": "bash",
        "status": StepStatus.COMPLETED,
        "risk_level": RiskLevel.LOW,
    }
    defaults.update(overrides)
    step = TaskStep(**defaults)
    db.add(step)
    db.commit()
    return step


def _seed_memory(db, **overrides):
    """Helper to create a memory in the DB."""
    defaults = {
        "id": "mem-001",
        "title": "Test memory",
        "memory_type": MemoryType.EXECUTION_EXPERIENCE,
        "summary": "A summary",
        "importance_score": 0.8,
        "confidence_score": 0.7,
        "is_active": True,
    }
    defaults.update(overrides)
    memory = Memory(**defaults)
    db.add(memory)
    db.commit()
    return memory


def _seed_skill(db, **overrides):
    """Helper to create a skill in the DB."""
    defaults = {
        "id": "skill-001",
        "name": "test-skill",
        "version": 1,
        "status": SkillStatus.STABLE,
        "definition": {"tool": "bash", "command": "echo hello"},
        "success_rate": 0.95,
    }
    defaults.update(overrides)
    skill = Skill(**defaults)
    db.add(skill)
    db.commit()
    return skill


def _seed_audit_event(db, **overrides):
    """Helper to create an audit event in the DB."""
    defaults = {
        "id": "audit-001",
        "event_type": "task_created",
        "actor": "system",
        "detail": {"key": "value"},
    }
    defaults.update(overrides)
    event = AuditEvent(**defaults)
    db.add(event)
    db.commit()
    return event


def _graphql_post(client, query: str, variables: dict | None = None):
    """Helper to POST a GraphQL query."""
    body: dict = {"query": query}
    if variables:
        body["variables"] = variables
    return client.post("/api/v1/graphql", json=body)


# ═══════════════════════════════════════════════════════════════════════════
# TestGraphQLEndpoint
# ═══════════════════════════════════════════════════════════════════════════


class TestGraphQLEndpoint:
    """Test the GraphQL HTTP endpoint end-to-end."""

    def test_graphql_endpoint_exists(self, client):
        """GET /api/v1/graphql returns 200 (GraphiQL playground)."""
        resp = client.get("/api/v1/graphql")
        assert resp.status_code == 200

    def test_query_tasks(self, client, db):
        """query { tasks { id goal status } } returns list."""
        _seed_task(db, id="t1", goal="Goal 1", status=TaskStatus.COMPLETED)
        _seed_task(db, id="t2", goal="Goal 2", status=TaskStatus.PENDING)

        query = """{
            tasks {
                id
                goal
                status
            }
        }"""
        resp = _graphql_post(client, query)
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data, f"GraphQL errors: {data.get('errors')}"
        tasks = data["data"]["tasks"]
        assert len(tasks) == 2
        assert all("id" in t and "goal" in t and "status" in t for t in tasks)

    def test_query_tasks_with_limit(self, client, db):
        """query { tasks(limit: 5) { id } } respects limit."""
        for i in range(10):
            _seed_task(db, id=f"t-limit-{i}", goal=f"Goal {i}", status=TaskStatus.PENDING)

        query = """{
            tasks(limit: 5) {
                id
            }
        }"""
        resp = _graphql_post(client, query)
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data
        assert len(data["data"]["tasks"]) == 5

    def test_query_task_by_id(self, client, db):
        """query { task(taskId: "xxx") { id goal } }."""
        _seed_task(db, id="t-single", goal="Find me", status=TaskStatus.EXECUTING)

        query = """{
            task(taskId: "t-single") {
                id
                goal
            }
        }"""
        resp = _graphql_post(client, query)
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data
        assert data["data"]["task"]["id"] == "t-single"
        assert data["data"]["task"]["goal"] == "Find me"

    def test_query_task_not_found(self, client, db):
        """query returns null for nonexistent ID."""
        query = """{
            task(taskId: "nonexistent") {
                id
            }
        }"""
        resp = _graphql_post(client, query)
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data
        assert data["data"]["task"] is None

    def test_query_task_with_steps(self, client, db):
        """query { taskWithSteps(taskId: "xxx") { task { id } steps { id } } }."""
        _seed_task(db, id="t-steps", goal="With steps", status=TaskStatus.COMPLETED)
        _seed_step(db, id="s1", task_id="t-steps", step_order=1, tool_name="bash")
        _seed_step(db, id="s2", task_id="t-steps", step_order=2, tool_name="file_write")

        query = """{
            taskWithSteps(taskId: "t-steps") {
                task { id goal }
                steps { id toolName status }
            }
        }"""
        resp = _graphql_post(client, query)
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data
        result = data["data"]["taskWithSteps"]
        assert result["task"]["id"] == "t-steps"
        assert len(result["steps"]) == 2

    def test_query_dashboard_stats(self, client, db):
        """query { dashboardStats { totalTasks successRate } }."""
        _seed_task(db, id="ds-1", status=TaskStatus.COMPLETED)
        _seed_task(db, id="ds-2", status=TaskStatus.FAILED)
        _seed_task(db, id="ds-3", status=TaskStatus.PENDING)
        _seed_skill(db, id="ds-skill-1")
        _seed_memory(db, id="ds-mem-1")

        query = """{
            dashboardStats {
                totalTasks
                completedTasks
                failedTasks
                totalSkills
                totalMemories
                successRate
            }
        }"""
        resp = _graphql_post(client, query)
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data
        stats = data["data"]["dashboardStats"]
        assert stats["totalTasks"] == 3
        assert stats["completedTasks"] == 1
        assert stats["failedTasks"] == 1
        assert stats["totalSkills"] == 1
        assert stats["totalMemories"] == 1
        assert stats["successRate"] == 33.3

    def test_query_memories(self, client, db):
        """query { memories { id title } }."""
        _seed_memory(db, id="m1", title="Memory 1")
        _seed_memory(db, id="m2", title="Memory 2")

        query = """{
            memories {
                id
                title
            }
        }"""
        resp = _graphql_post(client, query)
        assert resp.status_code == 200
        data = resp.json()
        assert "errors" not in data
        assert len(data["data"]["memories"]) == 2


# ═══════════════════════════════════════════════════════════════════════════
# TestGraphQLTypes
# ═══════════════════════════════════════════════════════════════════════════


class TestGraphQLTypes:
    """Test type conversion functions."""

    def test_task_type_conversion(self, db):
        """_to_task_type correctly converts a Task ORM object."""
        from packages.graphql.resolvers import _to_task_type

        task = Task(
            id="conv-task",
            goal="Conversion test",
            status=TaskStatus.COMPLETED,
            edition=Edition.ENTERPRISE,
            risk_level=RiskLevel.HIGH,
            result="done",
            error=None,
        )
        db.add(task)
        db.commit()

        result = _to_task_type(task)
        assert result.id == "conv-task"
        assert result.goal == "Conversion test"
        assert result.status == "completed"
        assert result.edition == "enterprise"
        assert result.risk_level == "high"
        assert result.result == "done"

    def test_memory_type_conversion(self, db):
        """_to_memory_type correctly converts a Memory ORM object."""
        from packages.graphql.resolvers import _to_memory_type

        mem = Memory(
            id="conv-mem",
            title="Conv memory",
            memory_type=MemoryType.ERROR_SOLUTION,
            summary="Fixed a bug",
            importance_score=0.9,
            confidence_score=0.85,
            is_active=True,
        )
        db.add(mem)
        db.commit()

        result = _to_memory_type(mem)
        assert result.id == "conv-mem"
        assert result.title == "Conv memory"
        assert result.memory_type == "error_solution"
        assert result.importance_score == 0.9
        assert result.enabled is True

    def test_skill_type_conversion(self, db):
        """_to_skill_type correctly converts a Skill ORM object."""
        from packages.graphql.resolvers import _to_skill_type

        skill = Skill(
            id="conv-skill",
            name="conv-skill",
            version=2,
            status=SkillStatus.STABLE,
            definition={"tool": "bash"},
            success_rate=0.88,
        )
        db.add(skill)
        db.commit()

        result = _to_skill_type(skill)
        assert result.id == "conv-skill"
        assert result.name == "conv-skill"
        assert result.version == 2
        assert result.status == "stable"
        assert result.success_rate == 0.88

    def test_dashboard_stats_calculation(self, db):
        """Dashboard stats calculate correctly with mixed task statuses."""
        from packages.graphql.resolvers import get_dashboard_stats

        for i in range(5):
            _seed_task(db, id=f"stat-{i}", status=TaskStatus.COMPLETED)
        for i in range(3):
            _seed_task(db, id=f"stat-f-{i}", status=TaskStatus.FAILED)
        for i in range(2):
            _seed_task(db, id=f"stat-p-{i}", status=TaskStatus.PENDING)

        stats = get_dashboard_stats()
        assert stats.total_tasks == 10
        assert stats.completed_tasks == 5
        assert stats.failed_tasks == 3
        assert stats.success_rate == 50.0  # 5/10 * 100

    def test_empty_db_stats(self):
        """Dashboard stats return zeros on empty database."""
        from packages.graphql.resolvers import get_dashboard_stats

        stats = get_dashboard_stats()
        assert stats.total_tasks == 0
        assert stats.completed_tasks == 0
        assert stats.failed_tasks == 0
        assert stats.total_skills == 0
        assert stats.total_memories == 0
        assert stats.success_rate == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# TestGraphQLResolvers
# ═══════════════════════════════════════════════════════════════════════════


class TestGraphQLResolvers:
    """Test resolver data-fetching logic."""

    def test_get_tasks_with_status_filter(self, db):
        """get_tasks filters by status when provided."""
        from packages.graphql.resolvers import get_tasks

        _seed_task(db, id="f1", status=TaskStatus.COMPLETED)
        _seed_task(db, id="f2", status=TaskStatus.PENDING)
        _seed_task(db, id="f3", status=TaskStatus.COMPLETED)

        completed = get_tasks(status="completed")
        assert len(completed) == 2
        assert all(t.status == "completed" for t in completed)

        pending = get_tasks(status="pending")
        assert len(pending) == 1

    def test_get_memories_with_type_filter(self, db):
        """get_memories filters by memory_type when provided."""
        from packages.graphql.resolvers import get_memories

        _seed_memory(db, id="mf1", memory_type=MemoryType.ERROR_SOLUTION, title="Error fix")
        _seed_memory(db, id="mf2", memory_type=MemoryType.WORKFLOW_PATTERN, title="Pattern")
        _seed_memory(db, id="mf3", memory_type=MemoryType.ERROR_SOLUTION, title="Another fix")

        errors = get_memories(memory_type="error_solution")
        assert len(errors) == 2
        assert all(m.memory_type == "error_solution" for m in errors)

        patterns = get_memories(memory_type="workflow_pattern")
        assert len(patterns) == 1

    def test_get_skills_with_status_filter(self, db):
        """get_skills filters by status when provided."""
        from packages.graphql.resolvers import get_skills

        _seed_skill(db, id="sf1", status=SkillStatus.STABLE, name="stable-skill")
        _seed_skill(db, id="sf2", status=SkillStatus.CANDIDATE, name="candidate-skill")
        _seed_skill(db, id="sf3", status=SkillStatus.STABLE, name="another-stable")

        stable = get_skills(status="stable")
        assert len(stable) == 2
        assert all(s.status == "stable" for s in stable)

        candidates = get_skills(status="candidate")
        assert len(candidates) == 1

    def test_get_task_with_steps_joins_correctly(self, db):
        """get_task_with_steps returns the task with all its steps."""
        from packages.graphql.resolvers import get_task_with_steps

        _seed_task(db, id="join-task", goal="Joined", status=TaskStatus.EXECUTING)
        _seed_step(db, id="js1", task_id="join-task", step_order=1, tool_name="bash")
        _seed_step(db, id="js2", task_id="join-task", step_order=2, tool_name="file_read")
        _seed_step(db, id="js3", task_id="join-task", step_order=3, tool_name="web_search")

        result = get_task_with_steps("join-task")
        assert result is not None
        assert result.task.id == "join-task"
        assert len(result.steps) == 3
        # Steps should be ordered by step_order
        assert result.steps[0].tool_name == "bash"
        assert result.steps[1].tool_name == "file_read"
        assert result.steps[2].tool_name == "web_search"

    def test_resolvers_cleanup_db_sessions(self):
        """Resolvers properly open and close DB sessions (no leaks)."""
        from packages.graphql.resolvers import get_dashboard_stats, get_task, get_tasks

        # Call resolvers multiple times — if sessions leak, connections will exhaust
        for _ in range(10):
            get_tasks()
        for _ in range(10):
            get_task("nonexistent")
        for _ in range(10):
            get_dashboard_stats()

        # If we got here without hanging, sessions were properly closed
        assert True
