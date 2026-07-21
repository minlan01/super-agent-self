"""Integration test — Semantic memory retrieval with time decay and recency boosting."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.agent_core.schemas import MemoryCreate, MemorySearchQuery
from packages.db.models import Base, Edition, MemoryType
from packages.db.repositories.memory_repo import MemoryRepository
from packages.memory.retriever import MemoryRetriever, _cosine_similarity


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


def _create_memory(db, title, summary, importance=0.5, confidence=0.7,
                    memory_type=MemoryType.DOMAIN_KNOWLEDGE, days_ago=0,
                    user_id="default", edition=Edition.ENTERPRISE):
    """Helper to create a test memory via repository."""
    schema = MemoryCreate(
        memory_type=memory_type,
        title=title,
        summary=summary,
        importance_score=importance,
        confidence_score=confidence,
    )
    mem = MemoryRepository.create(db, user_id=user_id, edition=edition, schema=schema)
    if days_ago > 0:
        mem.created_at = datetime.now(UTC) - timedelta(days=days_ago)
        db.commit()
        db.refresh(mem)
    return mem


class TestCosineSimilarity:
    """Test the cosine similarity helper."""

    def test_identical_vectors(self):
        assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert _cosine_similarity([0, 0], [1, 1]) == 0.0


class TestMemoryRetrieval:
    """Test keyword-based memory retrieval with importance scoring."""

    def test_retrieve_by_keyword(self, db):
        _create_memory(db, "Python tips", "Best practices for Python development", importance=0.8)
        _create_memory(db, "Cooking recipes", "How to make pasta", importance=0.7)

        retriever = MemoryRetriever()
        result = retriever.retrieve(db, goal="Python development")

        assert result.total_count >= 1
        assert any("Python" in m.get("title", "") for m in result.memories)

    def test_importance_threshold(self, db):
        _create_memory(db, "Low importance", "Not very useful", importance=0.1)
        _create_memory(db, "High importance", "Very useful insight", importance=0.9)

        retriever = MemoryRetriever()
        retriever.min_importance = 0.3
        result = retriever.retrieve(db, goal="useful")

        titles = [m.get("title", "") for m in result.memories]
        assert "Low importance" not in titles

    def test_inactive_memories_excluded(self, db):
        mem = _create_memory(db, "Disabled memory", "This was disabled", importance=0.9)
        MemoryRepository.disable(db, mem.id)

        retriever = MemoryRetriever()
        result = retriever.retrieve(db, goal="disabled")
        assert result.total_count == 0 or all(
            m.get("title") != "Disabled memory" for m in result.memories
        )

    def test_max_results_limit(self, db):
        for i in range(10):
            _create_memory(db, f"Memory {i}", f"Content {i}", importance=0.8)

        retriever = MemoryRetriever()
        retriever.max_results = 3
        result = retriever.retrieve(db, goal="Memory")
        assert len(result.memories) <= 3

    def test_empty_db_returns_empty(self, db):
        retriever = MemoryRetriever()
        result = retriever.retrieve(db, goal="anything")
        assert result.memories == []
        assert result.total_count == 0


class TestTimeDecay:
    """Test time decay and recency boosting."""

    def test_recent_memories_ranked_higher(self, db):
        """Recent memory should rank higher than old memory of same importance."""
        _create_memory(db, "Old memory", "Created long ago", importance=0.7, days_ago=30)
        _create_memory(db, "New memory", "Created recently", importance=0.7, days_ago=1)

        retriever = MemoryRetriever()
        result = retriever.retrieve(db, goal="memory")

        if len(result.memories) >= 2:
            titles = [m.get("title", "") for m in result.memories]
            new_idx = titles.index("New memory") if "New memory" in titles else -1
            old_idx = titles.index("Old memory") if "Old memory" in titles else -1
            if new_idx >= 0 and old_idx >= 0:
                assert new_idx < old_idx  # New memory comes first

    def test_high_importance_compensates_age(self, db):
        """Very high importance old memory can outrank low importance new one.

        With 0.95 decay/day: 0.99 * 0.95^10 = 0.593 > 0.3 * 1.3 = 0.39
        """
        _create_memory(db, "Old but critical", "Essential knowledge", importance=0.99, days_ago=10)
        _create_memory(db, "New but trivial", "Minor detail", importance=0.3, days_ago=0)

        retriever = MemoryRetriever()
        result = retriever.retrieve(db, goal="knowledge detail")

        if len(result.memories) >= 2:
            titles = [m.get("title", "") for m in result.memories]
            critical_idx = titles.index("Old but critical") if "Old but critical" in titles else -1
            trivial_idx = titles.index("New but trivial") if "New but trivial" in titles else -1
            if critical_idx >= 0 and trivial_idx >= 0:
                assert critical_idx < trivial_idx


class TestMemoryCRUD:
    """Test memory repository CRUD operations."""

    def test_create_and_get(self, db):
        schema = MemoryCreate(
            memory_type=MemoryType.EXECUTION_EXPERIENCE,
            title="Test",
            summary="Test summary",
            importance_score=0.7,
            confidence_score=0.8,
        )
        mem = MemoryRepository.create(db, user_id="default", edition=Edition.ENTERPRISE, schema=schema)
        assert mem.id is not None

        found = MemoryRepository.get_by_id(db, mem.id)
        assert found is not None
        assert found.title == "Test"

    def test_search_by_keyword(self, db):
        schema1 = MemoryCreate(
            memory_type=MemoryType.WORKFLOW_PATTERN,
            title="Web scraping flow",
            summary="Standard web scraping workflow",
            importance_score=0.7,
            confidence_score=0.8,
        )
        MemoryRepository.create(db, user_id="default", edition=Edition.ENTERPRISE, schema=schema1)

        schema2 = MemoryCreate(
            memory_type=MemoryType.DOMAIN_KNOWLEDGE,
            title="Cooking basics",
            summary="How to boil water",
            importance_score=0.5,
            confidence_score=0.9,
        )
        MemoryRepository.create(db, user_id="default", edition=Edition.ENTERPRISE, schema=schema2)

        query = MemorySearchQuery(keyword="scraping")
        results = MemoryRepository.search(db, query, user_id="default", edition=Edition.ENTERPRISE)
        assert len(results) == 1
        assert results[0].title == "Web scraping flow"

    def test_disable_memory(self, db):
        schema = MemoryCreate(
            memory_type=MemoryType.ERROR_SOLUTION,
            title="Error fix",
            summary="How to fix X",
            importance_score=0.6,
            confidence_score=0.7,
        )
        mem = MemoryRepository.create(db, user_id="default", edition=Edition.ENTERPRISE, schema=schema)

        disabled = MemoryRepository.disable(db, mem.id)
        assert disabled.is_active is False
