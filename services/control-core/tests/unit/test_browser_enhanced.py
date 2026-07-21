"""Tests for enhanced browser tools — BrowserBookmark, BrowserMonitor."""

from __future__ import annotations

import json

import pytest

from packages.executor.tools.browser_enhanced import BrowserBookmark, BrowserMonitor


class _MockContext:
    def __init__(self, tmp_path):
        self.workspace_root = str(tmp_path)
        self.task_id = "test-task"
        self.step_id = "test-step"
        self.edition = "personal"


@pytest.mark.unit
class TestBrowserBookmark:
    @pytest.mark.asyncio
    async def test_list_empty_bookmarks(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserBookmark()
        result = await tool.execute({"action": "list"}, ctx)

        assert result.success
        assert result.output["bookmarks"] == []

    @pytest.mark.asyncio
    async def test_save_bookmark(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserBookmark()
        result = await tool.execute({
            "action": "save",
            "url": "https://example.com",
            "title": "Example",
        }, ctx)

        assert result.success
        assert result.output["url"] == "https://example.com"

        # Verify persisted
        bookmarks_file = tmp_path / "bookmarks.json"
        assert bookmarks_file.exists()
        data = json.loads(bookmarks_file.read_text())
        assert len(data) == 1
        assert data[0]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_save_duplicate_bookmark(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserBookmark()

        await tool.execute({"action": "save", "url": "https://example.com"}, ctx)
        result = await tool.execute({"action": "save", "url": "https://example.com"}, ctx)

        assert result.success
        assert "Already bookmarked" in result.output["message"]

    @pytest.mark.asyncio
    async def test_save_bookmark_no_url(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserBookmark()
        result = await tool.execute({"action": "save", "url": ""}, ctx)

        assert not result.success
        assert "url" in result.error

    @pytest.mark.asyncio
    async def test_list_after_save(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserBookmark()

        await tool.execute({"action": "save", "url": "https://a.com", "title": "A"}, ctx)
        await tool.execute({"action": "save", "url": "https://b.com", "title": "B"}, ctx)

        result = await tool.execute({"action": "list"}, ctx)
        assert result.success
        assert len(result.output["bookmarks"]) == 2

    @pytest.mark.asyncio
    async def test_delete_bookmark(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserBookmark()

        await tool.execute({"action": "save", "url": "https://keep.com"}, ctx)
        await tool.execute({"action": "save", "url": "https://delete.com"}, ctx)

        result = await tool.execute({"action": "delete", "url": "https://delete.com"}, ctx)
        assert result.success

        # Verify only one remains
        listed = await tool.execute({"action": "list"}, ctx)
        urls = [b["url"] for b in listed.output["bookmarks"]]
        assert "https://keep.com" in urls
        assert "https://delete.com" not in urls

    @pytest.mark.asyncio
    async def test_unknown_action(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserBookmark()
        result = await tool.execute({"action": "invalid"}, ctx)

        assert not result.success
        assert "Unknown action" in result.error


@pytest.mark.unit
class TestBrowserMonitor:
    @pytest.mark.asyncio
    async def test_first_check(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserMonitor()
        result = await tool.execute({"url": "https://example.com"}, ctx)

        assert result.success
        assert result.output["status"] == "first_check"
        assert result.output["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_subsequent_check(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserMonitor()

        # First check
        await tool.execute({"url": "https://example.com"}, ctx)
        # Second check
        result = await tool.execute({"url": "https://example.com"}, ctx)

        assert result.success
        assert result.output["status"] == "updated"
        assert "previous_check" in result.output

    @pytest.mark.asyncio
    async def test_monitor_no_url(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserMonitor()
        result = await tool.execute({"url": ""}, ctx)

        assert not result.success
        assert "url" in result.error

    @pytest.mark.asyncio
    async def test_monitor_creates_directory(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserMonitor()
        await tool.execute({"url": "https://test.com"}, ctx)

        assert (tmp_path / "monitors").exists()

    @pytest.mark.asyncio
    async def test_monitor_different_urls(self, tmp_path):
        ctx = _MockContext(tmp_path)
        tool = BrowserMonitor()

        r1 = await tool.execute({"url": "https://a.com"}, ctx)
        r2 = await tool.execute({"url": "https://b.com"}, ctx)

        assert r1.success
        assert r2.success
        # Each URL should have its own state file
        monitor_dir = tmp_path / "monitors"
        assert len(list(monitor_dir.glob("*.json"))) == 2
