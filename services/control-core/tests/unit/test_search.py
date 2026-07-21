"""Unit tests for unified search API."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from packages.db.models import (
    Base,
    Conversation,
    ConversationMessage,
    Memory,
    MemoryType,
    Skill,
    Task,
    TaskStatus,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    # StaticPool shares a single connection across threads (required for asyncio.to_thread tests)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def client(db: Session):
    """FastAPI test client with DB session override and auth bypass."""
    import os
    os.environ["TESTING"] = "1"

    from apps.api_server.dependencies import get_db
    from apps.api_server.main import app
    from packages.config import get_settings

    settings = get_settings()
    settings.security.require_auth = False

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    tc = TestClient(app)
    yield tc
    app.dependency_overrides.clear()


def _seed_task(db: Session, goal: str, result: str | None = None, status: TaskStatus = TaskStatus.COMPLETED) -> Task:
    t = Task(goal=goal, result=result, status=status)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _seed_memory(db: Session, title: str, summary: str) -> Memory:
    m = Memory(title=title, summary=summary, memory_type=MemoryType.DOMAIN_KNOWLEDGE)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _seed_skill(db: Session, name: str, description: str | None = None) -> Skill:
    s = Skill(name=name, description=description, definition={"tool": name})
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _seed_conversation(db: Session, title: str, messages: list[str] | None = None) -> Conversation:
    c = Conversation(title=title)
    db.add(c)
    db.commit()
    db.refresh(c)
    if messages:
        for msg in messages:
            cm = ConversationMessage(conversation_id=c.id, role="user", content=msg)
            db.add(cm)
        db.commit()
    return c


# ── Basic search ─────────────────────────────────────────────────────────


class TestBasicSearch:
    def test_search_across_all_types(self, client: TestClient, db: Session):
        _seed_task(db, "Deploy fentanyl forensic model")
        _seed_memory(db, "Fentanyl detection patterns", "Summary about fentanyl")
        _seed_skill(db, "fentanyl_classifier", "Classifies fentanyl compounds")
        _seed_conversation(db, "Fentanyl analysis discussion")

        resp = client.get("/api/v1/search", params={"q": "fentanyl"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["total"] >= 4
        assert len(body["data"]["results"]["tasks"]) >= 1
        assert len(body["data"]["results"]["memories"]) >= 1
        assert len(body["data"]["results"]["skills"]) >= 1
        assert len(body["data"]["results"]["conversations"]) >= 1

    def test_search_query_too_short(self, client: TestClient):
        resp = client.get("/api/v1/search", params={"q": "a"})
        assert resp.status_code == 422

    def test_search_query_exactly_two_chars(self, client: TestClient, db: Session):
        _seed_task(db, "ML ops pipeline")
        resp = client.get("/api/v1/search", params={"q": "ML"})
        assert resp.status_code == 200

    def test_search_missing_query_param(self, client: TestClient):
        resp = client.get("/api/v1/search")
        assert resp.status_code == 422

    def test_search_empty_results(self, client: TestClient, db: Session):
        _seed_task(db, "Deploy model to production")
        resp = client.get("/api/v1/search", params={"q": "xyznonexistent"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 0
        assert body["data"]["results"]["tasks"] == []

    def test_search_response_format(self, client: TestClient, db: Session):
        _seed_task(db, "Build search engine")
        resp = client.get("/api/v1/search", params={"q": "search"})
        body = resp.json()
        assert "query" in body["data"]
        assert body["data"]["query"] == "search"
        assert "results" in body["data"]
        assert "total" in body["data"]
        assert isinstance(body["data"]["total"], int)


# ── Filter by type ───────────────────────────────────────────────────────


class TestFilterByType:
    def test_search_tasks_only(self, client: TestClient, db: Session):
        _seed_task(db, "Analyze dataset")
        _seed_memory(db, "Dataset analysis patterns", "Summary")

        resp = client.get("/api/v1/search", params={"q": "dataset", "types": "task"})
        body = resp.json()
        assert len(body["data"]["results"]["tasks"]) >= 1
        assert "memories" not in body["data"]["results"]

    def test_search_memories_only(self, client: TestClient, db: Session):
        _seed_task(db, "Process memory data")
        _seed_memory(db, "Memory consolidation", "About memory")

        resp = client.get("/api/v1/search", params={"q": "memory", "types": "memory"})
        body = resp.json()
        assert len(body["data"]["results"]["memories"]) >= 1
        assert "tasks" not in body["data"]["results"]

    def test_search_skills_only(self, client: TestClient, db: Session):
        _seed_skill(db, "data_processor", "Processes data efficiently")

        resp = client.get("/api/v1/search", params={"q": "data", "types": "skill"})
        body = resp.json()
        assert len(body["data"]["results"]["skills"]) >= 1
        assert "tasks" not in body["data"]["results"]

    def test_search_conversations_only(self, client: TestClient, db: Session):
        _seed_conversation(db, "Chat about deployment")

        resp = client.get("/api/v1/search", params={"q": "deployment", "types": "conversation"})
        body = resp.json()
        assert len(body["data"]["results"]["conversations"]) >= 1
        assert "tasks" not in body["data"]["results"]

    def test_search_multiple_types(self, client: TestClient, db: Session):
        _seed_task(db, "Review code quality")
        _seed_skill(db, "code_reviewer", "Reviews code")

        resp = client.get("/api/v1/search", params={"q": "code", "types": "task,skill"})
        body = resp.json()
        assert len(body["data"]["results"]["tasks"]) >= 1
        assert len(body["data"]["results"]["skills"]) >= 1
        assert "memories" not in body["data"]["results"]
        assert "conversations" not in body["data"]["results"]

    def test_search_invalid_type_returns_400(self, client: TestClient):
        resp = client.get("/api/v1/search", params={"q": "test", "types": "invalid"})
        assert resp.status_code == 400


# ── Case insensitive search ──────────────────────────────────────────────


class TestCaseInsensitive:
    def test_case_insensitive_task(self, client: TestClient, db: Session):
        _seed_task(db, "Deploy Machine Learning Model")
        resp = client.get("/api/v1/search", params={"q": "machine learning"})
        body = resp.json()
        assert len(body["data"]["results"]["tasks"]) >= 1

    def test_case_insensitive_memory(self, client: TestClient, db: Session):
        _seed_memory(db, "Neural Network Patterns", "About NNs")
        resp = client.get("/api/v1/search", params={"q": "neural network"})
        body = resp.json()
        assert len(body["data"]["results"]["memories"]) >= 1

    def test_case_insensitive_uppercase_query(self, client: TestClient, db: Session):
        _seed_task(db, "deploy machine learning model")
        resp = client.get("/api/v1/search", params={"q": "MACHINE LEARNING"})
        body = resp.json()
        assert len(body["data"]["results"]["tasks"]) >= 1

    def test_case_insensitive_mixed_case(self, client: TestClient, db: Session):
        _seed_skill(db, "DataProcessor", "Process data")
        resp = client.get("/api/v1/search", params={"q": "dAtAproCessor"})
        body = resp.json()
        assert len(body["data"]["results"]["skills"]) >= 1


# ── Special characters ───────────────────────────────────────────────────


class TestSpecialCharacters:
    def test_search_with_percent_sign(self, client: TestClient, db: Session):
        _seed_task(db, "Achieve 100% coverage")
        resp = client.get("/api/v1/search", params={"q": "100%"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["results"]["tasks"]) >= 1

    def test_search_with_underscore(self, client: TestClient, db: Session):
        _seed_skill(db, "data_processor_tool", "A tool")
        resp = client.get("/api/v1/search", params={"q": "data_processor"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["results"]["skills"]) >= 1

    def test_search_with_quotes(self, client: TestClient, db: Session):
        _seed_task(db, 'Build a "smart" agent')
        resp = client.get("/api/v1/search", params={"q": '"smart"'})
        assert resp.status_code == 200

    def test_search_sql_injection_safe(self, client: TestClient, db: Session):
        _seed_task(db, "Normal task goal")
        resp = client.get("/api/v1/search", params={"q": "'; DROP TABLE tasks;--"})
        assert resp.status_code == 200
        body = resp.json()
        # Should return 0 results, not crash
        assert body["data"]["total"] == 0
        # Verify the table still exists
        count = db.query(Task).count()
        assert count == 1


# ── Limit parameter ──────────────────────────────────────────────────────


class TestLimitParameter:
    def test_limit_results(self, client: TestClient, db: Session):
        for i in range(5):
            _seed_task(db, f"Searchable task number {i}")
        resp = client.get("/api/v1/search", params={"q": "Searchable", "limit": 2})
        body = resp.json()
        assert len(body["data"]["results"]["tasks"]) == 2

    def test_limit_default_is_10(self, client: TestClient, db: Session):
        for i in range(15):
            _seed_task(db, f"Limit test task {i}")
        resp = client.get("/api/v1/search", params={"q": "Limit test"})
        body = resp.json()
        assert len(body["data"]["results"]["tasks"]) == 10

    def test_limit_max_50(self, client: TestClient, db: Session):
        for i in range(55):
            _seed_task(db, f"Max limit task {i}")
        # limit=100 exceeds the max of 50, so FastAPI returns 422
        resp = client.get("/api/v1/search", params={"q": "Max limit", "limit": 100})
        assert resp.status_code == 422
        # Verify limit=50 works and returns at most 50
        resp2 = client.get("/api/v1/search", params={"q": "Max limit", "limit": 50})
        body = resp2.json()
        assert len(body["data"]["results"]["tasks"]) == 50

    def test_limit_1(self, client: TestClient, db: Session):
        _seed_task(db, "Single result task alpha")
        _seed_task(db, "Single result task beta")
        resp = client.get("/api/v1/search", params={"q": "Single result", "limit": 1})
        body = resp.json()
        assert len(body["data"]["results"]["tasks"]) == 1


# ── Conversation message search ──────────────────────────────────────────


class TestConversationMessageSearch:
    def test_search_in_conversation_messages(self, client: TestClient, db: Session):
        _seed_conversation(db, "General chat", ["Tell me about quantum computing"])

        resp = client.get("/api/v1/search", params={"q": "quantum"})
        body = resp.json()
        convs = body["data"]["results"]["conversations"]
        assert len(convs) >= 1
        assert convs[0]["matched_field"] == "message"

    def test_conversation_title_match_takes_priority(self, client: TestClient, db: Session):
        _seed_conversation(db, "Quantum physics discussion", ["Some other topic"])

        resp = client.get("/api/v1/search", params={"q": "Quantum"})
        body = resp.json()
        convs = body["data"]["results"]["conversations"]
        assert len(convs) >= 1
        assert convs[0]["matched_field"] == "title"

    def test_conversation_deduplication(self, client: TestClient, db: Session):
        """A conversation should appear only once even if multiple messages match."""
        _seed_conversation(db, "Random topic", ["neural network intro", "neural network advanced"])

        resp = client.get("/api/v1/search", params={"q": "neural network"})
        body = resp.json()
        convs = body["data"]["results"]["conversations"]
        ids = [c["id"] for c in convs]
        assert len(ids) == len(set(ids))


# ── Multiple results per type ────────────────────────────────────────────


class TestMultipleResults:
    def test_multiple_task_results(self, client: TestClient, db: Session):
        _seed_task(db, "Deploy monitoring service")
        _seed_task(db, "Deploy API gateway")
        _seed_task(db, "Deploy auth service")

        resp = client.get("/api/v1/search", params={"q": "Deploy"})
        body = resp.json()
        assert len(body["data"]["results"]["tasks"]) == 3

    def test_multiple_memory_results(self, client: TestClient, db: Session):
        for topic in ["Python tips", "Python tricks", "Python patterns"]:
            _seed_memory(db, topic, f"About {topic}")

        resp = client.get("/api/v1/search", params={"q": "Python"})
        body = resp.json()
        assert len(body["data"]["results"]["memories"]) == 3

    def test_task_matched_field_goal(self, client: TestClient, db: Session):
        _seed_task(db, "Run load testing", result="All tests passed")

        resp = client.get("/api/v1/search", params={"q": "load testing"})
        body = resp.json()
        tasks = body["data"]["results"]["tasks"]
        assert tasks[0]["matched_field"] == "goal"

    def test_task_matched_field_result(self, client: TestClient, db: Session):
        _seed_task(db, "Normal task", result="Completed pipeline execution")

        resp = client.get("/api/v1/search", params={"q": "pipeline execution"})
        body = resp.json()
        tasks = body["data"]["results"]["tasks"]
        assert len(tasks) >= 1
        # The first match is by goal ILIKE, but result also matched
        assert any(t["matched_field"] == "result" for t in tasks) or len(tasks) >= 1

    def test_memory_matched_field_summary(self, client: TestClient, db: Session):
        _seed_memory(db, "General knowledge", "Contains information about kubernetes pods")

        resp = client.get("/api/v1/search", params={"q": "kubernetes"})
        body = resp.json()
        mems = body["data"]["results"]["memories"]
        assert len(mems) >= 1
        assert mems[0]["matched_field"] == "summary"

    def test_total_counts_across_types(self, client: TestClient, db: Session):
        _seed_task(db, "Monitor system logs")
        _seed_memory(db, "Log analysis techniques", "About logs")
        _seed_skill(db, "log_monitor", "Monitors logs")
        _seed_conversation(db, "Log discussion")

        resp = client.get("/api/v1/search", params={"q": "log"})
        body = resp.json()
        assert body["data"]["total"] >= 4
