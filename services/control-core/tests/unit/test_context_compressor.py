"""Tests for ContextCompressor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.agent_core.context_compressor import ContextCompressor
from packages.llm_gateway.base import LLMMessage, LLMResponse


def _make_messages(n: int) -> list[LLMMessage]:
    """Create n simple user messages."""
    return [LLMMessage(role="user", content=f"Message {i}") for i in range(n)]


def _make_provider_router(summary_text: str = "Test summary"):
    """Create a mock provider router."""
    router = MagicMock()
    router.generate = AsyncMock(return_value=LLMResponse(
        content=summary_text, model="mock", provider="mock",
    ))
    return router


# ── should_compress ────────────────────────────────────────────────────────


class TestShouldCompress:
    def test_below_threshold(self):
        router = _make_provider_router()
        comp = ContextCompressor(router, threshold_percent=0.6)
        assert not comp.should_compress(token_count=50, context_length=1000)

    def test_at_threshold(self):
        router = _make_provider_router()
        comp = ContextCompressor(router, threshold_percent=0.6)
        assert comp.should_compress(token_count=6000, context_length=10000)

    def test_minimum_context(self):
        router = _make_provider_router()
        comp = ContextCompressor(router, threshold_percent=0.6)
        # Below MIN_CONTEXT_FOR_COMPRESSION (4000) even if ratio exceeded
        assert not comp.should_compress(token_count=2000, context_length=2001)


# ── _trim_tool_outputs ─────────────────────────────────────────────────────


class TestTrimToolOutputs:
    def test_short_tool_output_preserved(self):
        router = _make_provider_router()
        comp = ContextCompressor(router)
        msgs = [LLMMessage(role="tool", content="short")]
        result = comp._trim_tool_outputs(msgs)
        assert result[0].content == "short"

    def test_long_tool_output_trimmed(self):
        router = _make_provider_router()
        comp = ContextCompressor(router)
        long_content = "x" * 500
        msgs = [LLMMessage(role="tool", content=long_content)]
        result = comp._trim_tool_outputs(msgs)
        assert len(result[0].content) < len(long_content)
        assert "Trimmed" in result[0].content

    def test_non_tool_messages_unchanged(self):
        router = _make_provider_router()
        comp = ContextCompressor(router)
        msgs = [LLMMessage(role="user", content="hello")]
        result = comp._trim_tool_outputs(msgs)
        assert result[0].content == "hello"


# ── _split_protected ───────────────────────────────────────────────────────


class TestSplitProtected:
    def test_head_tail_split(self):
        router = _make_provider_router()
        comp = ContextCompressor(router)
        msgs = _make_messages(20)
        head, tail = comp._split_protected(msgs)
        assert len(head) <= 3  # PROTECTED_HEAD_COUNT
        assert len(tail) >= 1

    def test_few_messages(self):
        router = _make_provider_router()
        comp = ContextCompressor(router)
        msgs = _make_messages(2)
        head, tail = comp._split_protected(msgs)
        assert len(head) == 2


# ── _fix_orphaned_pairs ────────────────────────────────────────────────────


class TestFixOrphanedPairs:
    def test_removes_orphaned_tool_result(self):
        msgs = [
            LLMMessage(role="user", content="hi"),
            LLMMessage(role="tool", content="orphaned"),
        ]
        result = ContextCompressor._fix_orphaned_pairs(msgs)
        assert len(result) == 1
        assert result[0].role == "user"

    def test_keeps_paired_tool_result(self):
        msgs = [
            LLMMessage(role="assistant", content="calling tool"),
            LLMMessage(role="tool", content="result"),
        ]
        result = ContextCompressor._fix_orphaned_pairs(msgs)
        assert len(result) == 2


# ── compress ────────────────────────────────────────────────────────────────


class TestCompress:
    @pytest.mark.asyncio
    async def test_empty_messages(self):
        router = _make_provider_router()
        comp = ContextCompressor(router)
        result = await comp.compress([], context_length=8000)
        assert result == []

    @pytest.mark.asyncio
    async def test_few_messages_unchanged(self):
        router = _make_provider_router()
        comp = ContextCompressor(router)
        msgs = _make_messages(3)
        # With few messages, head covers all → no middle → return trimmed
        result = await comp.compress(msgs, context_length=8000)
        assert len(result) <= len(msgs)

    @pytest.mark.asyncio
    async def test_compresses_many_messages(self):
        router = _make_provider_router()
        comp = ContextCompressor(router)
        msgs = _make_messages(50)
        result = await comp.compress(msgs, context_length=8000)
        # Should be significantly fewer messages
        assert len(result) < len(msgs)
        # Should contain a summary system message
        summary_msgs = [m for m in result if m.role == "system" and "Compressed" in m.content]
        assert len(summary_msgs) == 1

    @pytest.mark.asyncio
    async def test_preserves_previous_summary(self):
        router = _make_provider_router()
        comp = ContextCompressor(router)
        comp._previous_summary = "Old summary"
        msgs = _make_messages(50)
        result = await comp.compress(msgs, context_length=8000)
        assert len(result) < len(msgs)
