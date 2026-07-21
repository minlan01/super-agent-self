"""Tests for personal edition tools — FileSearch, FileSummarize."""

from __future__ import annotations

import pytest

from packages.executor.tools.personal_tools import FileSearch, FileSummarize


class _MockContext:
    def __init__(self, tmp_path):
        self.workspace_root = str(tmp_path)
        self.task_id = "test-task"
        self.step_id = "test-step"
        self.edition = "personal"


@pytest.mark.unit
class TestFileSearch:
    @pytest.mark.asyncio
    async def test_search_by_filename(self, tmp_path):
        # Create some files
        (tmp_path / "report.txt").write_text("sales data here")
        (tmp_path / "notes.md").write_text("meeting notes")

        ctx = _MockContext(tmp_path)
        tool = FileSearch()
        result = await tool.execute({"keyword": "report"}, ctx)

        assert result.success
        assert result.output["matches"] >= 1
        assert any("report" in r["path"] for r in result.output["results"])

    @pytest.mark.asyncio
    async def test_search_by_content(self, tmp_path):
        (tmp_path / "data.txt").write_text("quarterly revenue report 2025")

        ctx = _MockContext(tmp_path)
        tool = FileSearch()
        result = await tool.execute({"keyword": "revenue"}, ctx)

        assert result.success
        assert result.output["matches"] >= 1

    @pytest.mark.asyncio
    async def test_search_no_keyword(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = FileSearch()
        result = await tool.execute({"keyword": ""}, ctx)

        assert not result.success
        assert "keyword" in result.error

    @pytest.mark.asyncio
    async def test_search_path_outside_workspace(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = FileSearch()
        result = await tool.execute({"keyword": "test", "path": "../../etc"}, ctx)

        assert not result.success
        assert "outside workspace" in result.error.lower()

    @pytest.mark.asyncio
    async def test_search_no_results(self, tmp_path):
        (tmp_path / "file.txt").write_text("nothing relevant")

        ctx = _MockContext(tmp_path)
        tool = FileSearch()
        result = await tool.execute({"keyword": "xyznonexistent"}, ctx)

        assert result.success
        assert result.output["matches"] == 0


@pytest.mark.unit
class TestFileSummarize:
    @pytest.mark.asyncio
    async def test_summarize_text_file(self, tmp_path):
        content = "\n".join(f"Line {i}" for i in range(30))
        (tmp_path / "doc.txt").write_text(content)

        ctx = _MockContext(tmp_path)
        tool = FileSummarize()
        result = await tool.execute({"path": "doc.txt"}, ctx)

        assert result.success
        assert result.output["lines"] == 30
        assert "First 20 lines" in result.output["summary"]

    @pytest.mark.asyncio
    async def test_summarize_short_file(self, tmp_path):
        (tmp_path / "short.txt").write_text("Hello world")

        ctx = _MockContext(tmp_path)
        tool = FileSummarize()
        result = await tool.execute({"path": "short.txt"}, ctx)

        assert result.success
        assert result.output["lines"] == 1
        assert "more lines" not in result.output["summary"]

    @pytest.mark.asyncio
    async def test_summarize_no_path(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = FileSummarize()
        result = await tool.execute({"path": ""}, ctx)

        assert not result.success
        assert "path" in result.error

    @pytest.mark.asyncio
    async def test_summarize_nonexistent_file(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = FileSummarize()
        result = await tool.execute({"path": "missing.txt"}, ctx)

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_summarize_path_outside_workspace(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = FileSummarize()
        result = await tool.execute({"path": "../../etc/passwd"}, ctx)

        assert not result.success
        assert "outside workspace" in result.error.lower()
