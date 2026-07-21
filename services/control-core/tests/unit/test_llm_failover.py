"""Tests for CredentialPool, ProviderHealthTracker, CostTracker, and failover."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.llm_gateway.base import BaseLLMProvider, LLMResponse, ProviderHealth
from packages.llm_gateway.cost_tracker import CostTracker
from packages.llm_gateway.credential_pool import CredentialPool
from packages.llm_gateway.health_tracker import ProviderHealthTracker

# ── CredentialPool ───────────────────────────────────────────────────────


class TestCredentialPool:
    def test_rotate_round_robin(self):
        pool = CredentialPool(["key1", "key2", "key3"])

        async def _test():
            assert await pool.rotate() == "key1"
            assert await pool.rotate() == "key2"
            assert await pool.rotate() == "key3"
            assert await pool.rotate() == "key1"  # wraps around

        asyncio.run(_test())

    def test_mark_invalid_removes_key(self):
        pool = CredentialPool(["key1", "key2"])

        async def _test():
            await pool.mark_invalid("key1")
            assert pool.size() == 1
            assert await pool.rotate() == "key2"

        asyncio.run(_test())

    def test_add_key(self):
        pool = CredentialPool(["key1"])

        async def _test():
            await pool.add_key("key2")
            assert pool.size() == 2

        asyncio.run(_test())

    def test_add_duplicate_ignored(self):
        pool = CredentialPool(["key1"])

        async def _test():
            await pool.add_key("key1")
            assert pool.size() == 1

        asyncio.run(_test())

    def test_empty_pool_returns_none(self):
        pool = CredentialPool([])

        async def _test():
            assert await pool.rotate() is None

        asyncio.run(_test())

    def test_is_empty(self):
        assert CredentialPool([]).is_empty() is True
        assert CredentialPool(["key1"]).is_empty() is False

    def test_from_env_keys(self):
        with patch.dict("os.environ", {"KEY_A": "val_a", "KEY_B": ""}):
            pool = CredentialPool.from_env_keys(["KEY_A", "KEY_B", "KEY_C"])
            assert pool.size() == 1


# ── ProviderHealthTracker ───────────────────────────────────────────────


class TestProviderHealthTracker:
    def test_initial_healthy(self):
        tracker = ProviderHealthTracker()
        assert tracker.is_healthy("test_provider") is True

    def test_record_success_resets_failures(self):
        tracker = ProviderHealthTracker()
        tracker.record_failure("p1", "error1")
        tracker.record_failure("p1", "error2")
        assert tracker.is_healthy("p1") is True  # 2 < 3

        tracker.record_failure("p1", "error3")
        assert tracker.is_healthy("p1") is False  # 3 >= 3

        tracker.record_success("p1")
        assert tracker.is_healthy("p1") is True  # reset

    def test_rate_limit_cooldown(self):
        tracker = ProviderHealthTracker()
        tracker.record_rate_limit("p1", time.time() + 3600)  # 1h from now
        assert tracker.is_healthy("p1") is False

    def test_rate_limit_expires(self):
        tracker = ProviderHealthTracker()
        tracker.record_rate_limit("p1", time.time() - 1)  # already expired
        assert tracker.is_healthy("p1") is True

    def test_get_all_health(self):
        tracker = ProviderHealthTracker()
        tracker.record_failure("p1", "error")
        health = tracker.get_all_health()
        assert "p1" in health
        assert health["p1"].consecutive_failures == 1

    def test_reset(self):
        tracker = ProviderHealthTracker()
        tracker.record_failure("p1", "error")
        tracker.record_failure("p1", "error")
        tracker.record_failure("p1", "error")
        assert tracker.is_healthy("p1") is False
        tracker.reset("p1")
        assert tracker.is_healthy("p1") is True


# ── CostTracker ──────────────────────────────────────────────────────────


class TestCostTracker:
    def test_record_cost(self):
        tracker = CostTracker()
        rec = tracker.record("deepseek", "deepseek-chat", 1000, 500)
        assert rec.estimated_cost_usd > 0
        assert rec.prompt_tokens == 1000
        assert rec.completion_tokens == 500

    def test_get_total_cost(self):
        tracker = CostTracker()
        tracker.record("deepseek", "deepseek-chat", 1000, 500)
        tracker.record("deepseek", "deepseek-chat", 2000, 1000)
        total = tracker.get_total_cost()
        assert total > 0

    def test_get_total_cost_by_provider(self):
        tracker = CostTracker()
        tracker.record("deepseek", "deepseek-chat", 1000, 500)
        tracker.record("ollama", "qwen3:8b", 1000, 500)
        ds_cost = tracker.get_total_cost(provider="deepseek")
        assert ds_cost > 0

    def test_usage_summary(self):
        tracker = CostTracker()
        tracker.record("deepseek", "deepseek-chat", 1000, 500)
        summary = tracker.get_usage_summary()
        assert "total_cost_usd" in summary
        assert "breakdown" in summary
        assert len(summary["breakdown"]) == 1

    def test_ollama_zero_cost(self):
        tracker = CostTracker()
        rec = tracker.record("ollama", "qwen3:8b", 10000, 5000)
        assert rec.estimated_cost_usd == 0.0

    def test_custom_cost_override(self):
        tracker = CostTracker()
        tracker.set_custom_costs("custom", "model-a", 0.01, 0.05)
        rec = tracker.record("custom", "model-a", 1000, 1000)
        expected = 1000 / 1000 * 0.01 + 1000 / 1000 * 0.05
        assert abs(rec.estimated_cost_usd - expected) < 0.001


# ── ProviderHealth dataclass ─────────────────────────────────────────────


class TestProviderHealth:
    def test_is_healthy_default(self):
        h = ProviderHealth(provider_name="test")
        assert h.is_healthy() is True

    def test_is_healthy_after_failures(self):
        h = ProviderHealth(provider_name="test", consecutive_failures=3)
        assert h.is_healthy() is False

    def test_is_healthy_during_rate_limit(self):
        h = ProviderHealth(provider_name="test", rate_limit_reset_at=time.time() + 60)
        assert h.is_healthy() is False

    def test_is_healthy_after_rate_limit_expires(self):
        h = ProviderHealth(provider_name="test", rate_limit_reset_at=time.time() - 1)
        assert h.is_healthy() is True


# ── Failover integration ────────────────────────────────────────────────


class TestFailoverIntegration:
    def test_failover_to_next_provider(self):
        """When primary fails, should try next provider in chain."""
        from packages.llm_gateway.provider_router import ProviderRouter

        router = ProviderRouter.__new__(ProviderRouter)
        router.providers = {}
        router.credential_pools = {}
        router.health_tracker = ProviderHealthTracker()
        router.cost_tracker = CostTracker()
        router.failover_chains = {"test": ["primary", "fallback"]}

        # Mock providers
        mock_primary = MagicMock(spec=BaseLLMProvider)
        mock_primary.generate = AsyncMock(side_effect=RuntimeError("Primary down"))

        mock_fallback = MagicMock(spec=BaseLLMProvider)
        mock_fallback.generate = AsyncMock(return_value=LLMResponse(
            content="fallback response", model="fallback-model", provider="fallback",
        ))

        router.providers["primary"] = mock_primary
        router.providers["fallback"] = mock_fallback

        async def _test():
            result = await router.generate_with_failover([], chain="test")
            assert result.content == "fallback response"
            assert result.provider == "fallback"

        asyncio.run(_test())

    def test_all_providers_fail_raises(self):
        from packages.llm_gateway.provider_router import ProviderRouter

        router = ProviderRouter.__new__(ProviderRouter)
        router.providers = {}
        router.credential_pools = {}
        router.health_tracker = ProviderHealthTracker()
        router.cost_tracker = CostTracker()
        router.failover_chains = {"test": ["p1", "p2"]}

        mock_p1 = MagicMock(spec=BaseLLMProvider)
        mock_p1.generate = AsyncMock(side_effect=RuntimeError("P1 down"))
        mock_p2 = MagicMock(spec=BaseLLMProvider)
        mock_p2.generate = AsyncMock(side_effect=RuntimeError("P2 down"))

        router.providers["p1"] = mock_p1
        router.providers["p2"] = mock_p2

        async def _test():
            with pytest.raises(RuntimeError, match="All providers"):
                await router.generate_with_failover([], chain="test")

        asyncio.run(_test())

    def test_healthy_provider_skips_unhealthy(self):
        from packages.llm_gateway.provider_router import ProviderRouter

        router = ProviderRouter.__new__(ProviderRouter)
        router.providers = {}
        router.credential_pools = {}
        router.health_tracker = ProviderHealthTracker()
        router.cost_tracker = CostTracker()
        router.failover_chains = {"test": ["unhealthy", "healthy"]}

        # Mark unhealthy
        for _ in range(3):
            router.health_tracker.record_failure("unhealthy", "error")

        mock_unhealthy = MagicMock(spec=BaseLLMProvider)
        mock_unhealthy.generate = AsyncMock(return_value=LLMResponse(
            content="should not be called", model="u", provider="unhealthy",
        ))

        mock_healthy = MagicMock(spec=BaseLLMProvider)
        mock_healthy.generate = AsyncMock(return_value=LLMResponse(
            content="healthy response", model="h", provider="healthy",
        ))

        router.providers["unhealthy"] = mock_unhealthy
        router.providers["healthy"] = mock_healthy

        async def _test():
            result = await router.generate_with_failover([], chain="test")
            assert result.content == "healthy response"
            # Unhealthy should NOT have been tried
            mock_unhealthy.generate.assert_not_called()

        asyncio.run(_test())
