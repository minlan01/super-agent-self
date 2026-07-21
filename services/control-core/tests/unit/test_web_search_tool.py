"""Tests for WebSearch tool."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from packages.executor.tools.base import ExecutionContext
from packages.executor.tools.web_search_tool import WebSearch


@pytest.fixture
def context(tmp_path):
    return ExecutionContext(
        task_id="t1",
        step_id="s1",
        edition="enterprise",
        workspace_root=str(tmp_path),
    )


@pytest.fixture
def tool():
    return WebSearch()


# ── Engine detection ───────────────────────────────────────────────────────


class TestEngineDetection:
    def test_duckduckgo_always_available(self):
        with patch.dict(os.environ, {}, clear=True):
            engines = WebSearch._detect_engines()
            assert "duckduckgo" in engines

    def test_brave_detected_with_key(self):
        with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}, clear=False):
            engines = WebSearch._detect_engines()
            assert "brave" in engines
            assert "duckduckgo" in engines

    def test_brave_not_detected_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            engines = WebSearch._detect_engines()
            assert "brave" not in engines


# ── WebSearch.execute ──────────────────────────────────────────────────────


class TestWebSearchExecute:
    @pytest.mark.asyncio
    async def test_empty_query(self, tool, context):
        result = await tool.execute({"query": ""}, context)
        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_query(self, tool, context):
        result = await tool.execute({}, context)
        assert not result.success

    @pytest.mark.asyncio
    async def test_duckduckgo_success(self, context):
        tool = WebSearch()
        mock_results = [
            {"title": "Python", "href": "https://python.org", "body": "Python programming"},
        ]
        with patch.object(tool, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = [
                {"title": "Python", "url": "https://python.org", "snippet": "Python programming", "engine": "duckduckgo"},
            ]
            result = await tool.execute({"query": "Python"}, context)
            assert result.success
            assert result.output["query"] == "Python"
            assert len(result.output["results"]) == 1

    @pytest.mark.asyncio
    async def test_engine_fallback(self, context):
        tool = WebSearch()
        tool._engines = ["brave", "duckduckgo"]

        # Brave fails, DuckDuckGo succeeds
        with patch.object(tool, "_search_brave", new_callable=AsyncMock) as mock_brave:
            with patch.object(tool, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
                mock_brave.return_value = []
                mock_ddg.return_value = [
                    {"title": "Test", "url": "https://test.com", "snippet": "Test result", "engine": "duckduckgo"},
                ]
                result = await tool.execute({"query": "test"}, context)
                assert result.success
                assert result.output["engine"] == "duckduckgo"

    @pytest.mark.asyncio
    async def test_no_results(self, context):
        tool = WebSearch()
        tool._engines = ["duckduckgo"]
        with patch.object(tool, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = []
            result = await tool.execute({"query": "xyznonexistent12345"}, context)
            assert not result.success
            assert "no results" in result.error.lower()

    @pytest.mark.asyncio
    async def test_max_results_clamped(self, context):
        tool = WebSearch()
        with patch.object(tool, "_search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = [
                {"title": f"Result {i}", "url": f"https://r{i}.com", "snippet": f"Snip {i}", "engine": "duckduckgo"}
                for i in range(5)
            ]
            result = await tool.execute({"query": "test", "max_results": 100}, context)
            assert result.success
            # The engine should have been called with min(100, 10) = 10
            call_args = mock_ddg.call_args
            assert call_args[0][1] == 10  # max_results clamped to 10
