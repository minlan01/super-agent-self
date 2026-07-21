"""Tests for Tier 1 enhancements — context compressor integration, LLM chat intent, memory decay, step retry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.db.models import Base, Memory
from packages.llm_gateway.base import LLMMessage, LLMResponse
from packages.memory.retriever import (
    DECAY_FACTOR_PER_DAY,
    RECENCY_BOOST_MULTIPLIER,
    MemoryRetriever,
)


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


# ═══════════════════════════════════════════════════════════════════════════
# 1. ContextCompressor wiring into PlannerService
# ═══════════════════════════════════════════════════════════════════════════


class TestCompressorWiring:
    def test_planner_accepts_compressor(self):
        """PlannerService should accept an optional context_compressor."""
        from packages.planner.planner_service import PlannerService

        router = MagicMock()
        registry = MagicMock()
        registry.get_tools_summary.return_value = []

        compressor = MagicMock()
        svc = PlannerService(router, registry, context_compressor=compressor)
        assert svc.context_compressor is compressor

    def test_planner_without_compressor(self):
        from packages.planner.planner_service import PlannerService

        router = MagicMock()
        registry = MagicMock()
        svc = PlannerService(router, registry)
        assert svc.context_compressor is None

    def test_orchestrator_wires_compressor_to_planner(self):
        """Orchestrator should inject compressor into planner."""
        from packages.agent_core.orchestrator import Orchestrator
        from packages.planner.planner_service import PlannerService

        router = MagicMock()
        registry = MagicMock()
        registry.get_tools_summary.return_value = []
        planner = PlannerService(router, registry)
        executor = MagicMock()
        compressor = MagicMock()

        orch = Orchestrator(planner, executor, context_compressor=compressor)
        assert orch.context_compressor is compressor
        assert planner.context_compressor is compressor


class TestPlannerMaybeCompress:
    @pytest.mark.asyncio
    async def test_no_compress_when_under_threshold(self):
        from packages.planner.planner_service import PlannerService

        router = MagicMock()
        registry = MagicMock()
        registry.get_tools_summary.return_value = []

        compressor = MagicMock()
        compressor.should_compress.return_value = False

        svc = PlannerService(router, registry, context_compressor=compressor)
        msgs = [LLMMessage(role="user", content="short")]
        result = await svc._maybe_compress(msgs)
        assert result is msgs  # unchanged
        compressor.should_compress.assert_called_once()

    @pytest.mark.asyncio
    async def test_compress_when_over_threshold(self):
        from packages.planner.planner_service import PlannerService

        router = MagicMock()
        registry = MagicMock()
        registry.get_tools_summary.return_value = []

        compressed_msgs = [LLMMessage(role="system", content="summary")]
        compressor = MagicMock()
        compressor.should_compress.return_value = True
        compressor.compress = AsyncMock(return_value=compressed_msgs)

        svc = PlannerService(router, registry, context_compressor=compressor)
        msgs = [LLMMessage(role="user", content="x" * 40000)]
        result = await svc._maybe_compress(msgs)
        assert result is compressed_msgs


# ═══════════════════════════════════════════════════════════════════════════
# 2. LLM Intent Classification in Chat
# ═══════════════════════════════════════════════════════════════════════════


class TestIntentClassification:
    def test_keyword_fallback_task(self):
        from apps.api_server.routes.chat import _keyword_fallback

        result = _keyword_fallback("search for Python tutorials")
        assert result["intent"] == "task"

    def test_keyword_fallback_reminder(self):
        from apps.api_server.routes.chat import _keyword_fallback

        result = _keyword_fallback("remind me to call mom")
        assert result["intent"] == "reminder"

    def test_keyword_fallback_preference(self):
        from apps.api_server.routes.chat import _keyword_fallback

        result = _keyword_fallback("I prefer dark mode")
        assert result["intent"] == "preference"

    def test_keyword_fallback_info(self):
        from apps.api_server.routes.chat import _keyword_fallback

        result = _keyword_fallback("hello there")
        assert result["intent"] == "info"

    @pytest.mark.asyncio
    async def test_llm_classify_success(self):
        from apps.api_server.routes.chat import _classify_intent

        mock_response = LLMResponse(
            content='{"intent": "task", "confidence": 0.9, "extracted": "帮我查天气预报"}',
            model="mock",
            provider="mock",
        )

        mock_router = MagicMock()
        mock_router.generate_json = AsyncMock(return_value=mock_response)

        # Patch the cached dependency, not the ProviderRouter class
        with patch("apps.api_server.dependencies.get_provider_router", return_value=mock_router):
            result = await _classify_intent("帮我查一下天气预报")
            assert result["intent"] == "task"
            assert result["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_llm_classify_fallback_on_error(self):
        from apps.api_server.routes.chat import _classify_intent

        mock_router = MagicMock()
        mock_router.generate_json = AsyncMock(side_effect=RuntimeError("LLM down"))

        with patch("apps.api_server.dependencies.get_provider_router", return_value=mock_router):
            result = await _classify_intent("remind me to eat")
            assert result["intent"] == "reminder"  # fallback to keywords

    def test_keyword_chinese_task(self):
        from apps.api_server.routes.chat import _keyword_fallback

        result = _keyword_fallback("帮我写个文档")
        assert result["intent"] == "task"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Memory Time Decay + Recency Boosting
# ═══════════════════════════════════════════════════════════════════════════


class TestMemoryDecay:
    def test_recent_memory_gets_boost(self):
        """Memories created within 7 days should get a recency boost."""
        retriever = MemoryRetriever.__new__(MemoryRetriever)
        retriever.min_importance = 0.3

        recent_mem = Memory(
            title="Recent", summary="recent", importance_score=0.5,
            created_at=datetime.now(UTC),
        )
        score = retriever._adjusted_score(recent_mem)
        assert score >= 0.5 * RECENCY_BOOST_MULTIPLIER * 0.9  # allow small decay

    def test_old_memory_decays(self):
        """Memories from 30 days ago should have decayed importance."""
        retriever = MemoryRetriever.__new__(MemoryRetriever)
        retriever.min_importance = 0.3

        old_mem = Memory(
            title="Old", summary="old", importance_score=0.8,
            created_at=datetime.now(UTC) - timedelta(days=30),
        )
        score = retriever._adjusted_score(old_mem)
        expected = 0.8 * (DECAY_FACTOR_PER_DAY ** 30)
        assert abs(score - expected) < 0.01

    def test_very_old_memory_below_threshold(self):
        """Very old memories should score below fresh ones even with higher base importance."""
        retriever = MemoryRetriever.__new__(MemoryRetriever)
        retriever.min_importance = 0.3

        old_high = Memory(
            title="Old High", summary="old", importance_score=0.9,
            created_at=datetime.now(UTC) - timedelta(days=60),
        )
        new_low = Memory(
            title="New Low", summary="new", importance_score=0.5,
            created_at=datetime.now(UTC),
        )

        assert retriever._adjusted_score(new_low) > retriever._adjusted_score(old_high)

    def test_no_created_at_uses_base_score(self):
        """Memory with no created_at should use base importance."""
        retriever = MemoryRetriever.__new__(MemoryRetriever)
        retriever.min_importance = 0.3

        mem = Memory(title="Test", summary="test", importance_score=0.7)
        mem.created_at = None
        score = retriever._adjusted_score(mem)
        assert score == 0.7


# ═══════════════════════════════════════════════════════════════════════════
# 4. Step-level Retry + Re-planning
# ═══════════════════════════════════════════════════════════════════════════


class TestStepRetry:
    def test_executor_accepts_planner(self):
        """ExecutorService should accept optional planner for re-planning."""
        from packages.executor.executor_service import ExecutorService

        runner = MagicMock()
        engine = MagicMock()
        planner = MagicMock()

        svc = ExecutorService(runner, engine, planner=planner)
        assert svc.planner is planner

    def test_executor_without_planner(self):
        from packages.executor.executor_service import ExecutorService

        runner = MagicMock()
        engine = MagicMock()
        svc = ExecutorService(runner, engine)
        assert svc.planner is None

    @pytest.mark.asyncio
    async def test_retry_on_step_failure(self):
        """Step should be retried once on failure."""
        from packages.agent_core.schemas import TaskCreate
        from packages.executor.executor_service import ExecutorService
        from packages.executor.tools.base import ToolResult

        db = _make_session()
        task_repo = MagicMock()

        # Create a real task in DB
        from packages.db.repositories.task_repo import TaskRepository
        task = TaskRepository.create(db, TaskCreate(goal="test", edition="enterprise"))

        tool_runner = MagicMock()
        # First call fails, second call succeeds
        tool_runner.run = AsyncMock(side_effect=[
            ToolResult(success=False, error="timeout"),
            ToolResult(success=True, output="ok"),
        ])

        token_issuer = MagicMock()
        from packages.policy.capability_token import TokenIssuer
        from packages.policy.policy_engine import PolicyEngine
        from packages.policy.tool_registry import ToolRegistry

        issuer = TokenIssuer(secret_key="test")
        registry = ToolRegistry()
        engine = PolicyEngine(registry, issuer)

        # Need to register the tool in both runner and registry
        # Actually, let's use a simpler approach with mocks
        svc = ExecutorService(tool_runner, MagicMock(), planner=None)

        # Patch the policy engine to always allow
        svc.policy_engine = MagicMock()
        svc.policy_engine.check.return_value = MagicMock(
            allowed=True, token="test-token", reason="", risk_level="low",
        )

        from packages.planner.plan_validator import Plan, PlanStep
        plan = Plan(
            reasoning="test",
            steps=[PlanStep(step_id=1, tool_name="file.read", args={"path": "test.txt"}, reasoning="test")],
        )

        from packages.executor.tools.base import ExecutionContext
        ctx = ExecutionContext(task_id=task.id, step_id="s1", edition="enterprise")

        result = await svc.execute_plan(task.id, plan, ctx, db=db)
        assert result["success"] is True
        assert tool_runner.run.call_count == 2  # original + retry

    @pytest.mark.asyncio
    async def test_replan_on_persistent_failure(self):
        """After retry fails, executor should attempt re-planning if planner is available."""
        from packages.agent_core.schemas import TaskCreate
        from packages.db.repositories.task_repo import TaskRepository
        from packages.executor.executor_service import ExecutorService
        from packages.executor.tools.base import ExecutionContext, ToolResult
        from packages.planner.plan_validator import Plan, PlanStep

        db = _make_session()
        task = TaskRepository.create(db, TaskCreate(goal="test replan", edition="enterprise"))

        tool_runner = MagicMock()
        # All calls fail
        tool_runner.run = AsyncMock(return_value=ToolResult(success=False, error="persistent error"))

        # Mock planner that returns a recovery plan
        recovery_plan = Plan(
            reasoning="recovery",
            steps=[PlanStep(step_id=1, tool_name="file.list", args={}, reasoning="try listing")],
        )
        planner = MagicMock()
        planner.plan = AsyncMock(return_value=recovery_plan)

        svc = ExecutorService(tool_runner, MagicMock(), planner=planner)
        svc.policy_engine = MagicMock()
        svc.policy_engine.check.return_value = MagicMock(
            allowed=True, token="test-token", reason="", risk_level="low",
        )

        ctx = ExecutionContext(task_id=task.id, step_id="s1", edition="enterprise")
        plan = Plan(
            reasoning="test",
            steps=[PlanStep(step_id=1, tool_name="file.read", args={"path": "x"}, reasoning="test")],
        )

        result = await svc.execute_plan(task.id, plan, ctx, db=db)
        # Recovery plan also fails (all tool_runner.run returns failure)
        assert result["success"] is False
        # Planner should have been called for re-planning
        planner.plan.assert_called_once()
