"""Tests for Memory system — summarizer, importance scorer, service, retriever."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.db.models import Base, MemoryType
from packages.memory.importance_scorer import ImportanceScorer
from packages.memory.memory_service import MemoryService
from packages.memory.schemas import MemoryWriteRequest
from packages.memory.summarizer import MemorySummarizer


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


# ── Summarizer ────────────────────────────────────────────────────────────────


class TestMemorySummarizer:
    @pytest.mark.asyncio
    async def test_rule_based_summary(self):
        summarizer = MemorySummarizer()
        request = MemoryWriteRequest(
            task_id="t1", goal="Open example.com and extract text",
            steps_summary=[
                {"step_id": 1, "tool_name": "browser.open", "status": "completed"},
                {"step_id": 2, "tool_name": "browser.extract_text", "status": "completed"},
            ],
            success=True,
        )
        result = await summarizer.summarize(request)
        assert len(result.title) > 0
        assert len(result.summary) > 0
        assert "succeeded" in result.summary.lower()
        assert result.importance_score > 0

    @pytest.mark.asyncio
    async def test_rule_based_failure_summary(self):
        summarizer = MemorySummarizer()
        request = MemoryWriteRequest(
            task_id="t2", goal="Navigate to bad site",
            steps_summary=[{"step_id": 1, "tool_name": "browser.open", "status": "failed"}],
            success=False,
        )
        result = await summarizer.summarize(request)
        assert "failed" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_llm_fallback_to_rule_based(self):
        mock_router = MagicMock()
        mock_router.generate_json = AsyncMock(side_effect=Exception("LLM down"))
        summarizer = MemorySummarizer(provider_router=mock_router)
        request = MemoryWriteRequest(task_id="t3", goal="Test fallback")
        result = await summarizer.summarize(request)
        assert result.title == "Test fallback"


# ── Importance Scorer ─────────────────────────────────────────────────────────


class TestImportanceScorer:
    def setup_method(self):
        self.scorer = ImportanceScorer()

    def test_error_solution_high_importance(self):
        score = self.scorer.score(MemoryType.ERROR_SOLUTION, base_importance=0.5)
        assert score >= 0.7

    def test_daily_context_lower_importance(self):
        score = self.scorer.score(MemoryType.DAILY_CONTEXT, base_importance=0.5)
        assert score < 0.7

    def test_failure_boost(self):
        success_score = self.scorer.score(MemoryType.EXECUTION_EXPERIENCE, success=True)
        fail_score = self.scorer.score(MemoryType.EXECUTION_EXPERIENCE, success=False)
        assert fail_score > success_score

    def test_complexity_boost(self):
        simple = self.scorer.score(MemoryType.EXECUTION_EXPERIENCE, step_count=2)
        complex_ = self.scorer.score(MemoryType.EXECUTION_EXPERIENCE, step_count=7)
        assert complex_ > simple

    def test_duplicate_penalty(self):
        unique = self.scorer.score(MemoryType.EXECUTION_EXPERIENCE, is_unique=True)
        dup = self.scorer.score(MemoryType.EXECUTION_EXPERIENCE, is_unique=False)
        assert dup < unique

    def test_score_clamped(self):
        score = self.scorer.score(MemoryType.ERROR_SOLUTION, base_importance=1.0, success=False, step_count=10)
        assert 0.0 <= score <= 1.0

    def test_should_retrieve(self):
        assert self.scorer.should_retrieve(0.7, 0.8)
        assert not self.scorer.should_retrieve(0.2, 0.8)
        assert not self.scorer.should_retrieve(0.7, 0.3)


# ── Memory Service ────────────────────────────────────────────────────────────


class TestMemoryService:
    @pytest.mark.asyncio
    async def test_write_memory_from_task(self):
        db = _make_session()
        service = MemoryService(summarizer=MemorySummarizer())
        request = MemoryWriteRequest(
            task_id="t1", goal="Scrape example.com",
            steps_summary=[
                {"step_id": 1, "tool_name": "browser.open", "status": "completed"},
            ],
            success=True,
        )
        memory = await service.write_from_task(db, request)
        assert memory is not None
        assert memory.title != ""
        assert memory.source_task_id == "t1"
        db.close()

    @pytest.mark.asyncio
    async def test_write_memory_dedup(self):
        db = _make_session()
        service = MemoryService(summarizer=MemorySummarizer())
        request = MemoryWriteRequest(
            task_id="t1", goal="Scrape example.com",
            steps_summary=[{"step_id": 1, "tool_name": "browser.open", "status": "completed"}],
            success=True,
        )
        m1 = await service.write_from_task(db, request)
        assert m1 is not None
        m2 = await service.write_from_task(db, request)
        assert m2 is None  # deduplicated
        db.close()

    @pytest.mark.asyncio
    async def test_get_list_disable_delete(self):
        db = _make_session()
        service = MemoryService(summarizer=MemorySummarizer())
        request = MemoryWriteRequest(task_id="t1", goal="Test memory")
        memory = await service.write_from_task(db, request)
        assert memory is not None

        found = service.get_memory(db, memory.id)
        assert found is not None

        items = service.list_memories(db)
        assert len(items) >= 1

        disabled = service.disable_memory(db, memory.id)
        assert disabled.is_active is False

        assert service.delete_memory(db, memory.id) is True
        assert service.get_memory(db, memory.id) is None
        db.close()


# ── Retriever ─────────────────────────────────────────────────────────────────


class TestMemoryRetriever:
    def test_extract_keywords(self):
        from packages.memory.retriever import MemoryRetriever
        retriever = MemoryRetriever()
        keywords = retriever._extract_keywords(
            "Open the browser and extract text from example.com"
        )
        assert "browser" in keywords
        assert "extract" in keywords
        assert "example" in keywords  # "example.com" is split by replace(".", " ")
        assert "the" not in keywords

    def test_retrieve_from_empty_db(self):
        from packages.memory.retriever import MemoryRetriever
        db = _make_session()
        retriever = MemoryRetriever()
        result = retriever.retrieve(db, goal="test query")
        assert result.total_count == 0
        assert len(result.memories) == 0
        db.close()

    @pytest.mark.asyncio
    async def test_retrieve_with_data(self):
        from packages.memory.retriever import MemoryRetriever
        db = _make_session()

        service = MemoryService(summarizer=MemorySummarizer())
        for i in range(3):
            await service.write_from_task(db, MemoryWriteRequest(
                task_id=f"t{i}", goal=f"Browse website {i} and extract articles",
                steps_summary=[{"step_id": 1, "tool_name": "browser.open", "status": "completed"}],
                success=True,
            ))

        retriever = MemoryRetriever()
        result = retriever.retrieve(db, goal="Browse website and extract")
        assert result.total_count > 0
        db.close()
