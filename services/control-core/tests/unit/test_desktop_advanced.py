"""Tests for FileSystemTool and WindowManagerTool (Sprint 39 desktop automation)."""

import os
os.environ["TESTING"] = "1"

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from packages.executor.tools.desktop_tools import FileSystemTool, WindowManagerTool


class TestFileSystemTool:
    """Tests for the FileSystemTool (desktop.files)."""

    def test_name_and_description(self):
        tool = FileSystemTool()
        assert tool.name == "desktop.files"

    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_path):
        tool = FileSystemTool()
        (tmp_path / "file.txt").write_text("hello")
        (tmp_path / "subdir").mkdir()

        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"action": "list", "path": "."}, ctx)

        assert result.success is True
        entries = result.output["entries"]
        names = [e["name"] for e in entries]
        assert "file.txt" in names
        assert "subdir" in names

    @pytest.mark.asyncio
    async def test_list_not_directory(self, tmp_path):
        tool = FileSystemTool()
        (tmp_path / "file.txt").write_text("hello")

        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"action": "list", "path": "file.txt"}, ctx)

        assert result.success is False
        assert "Not a directory" in result.error

    @pytest.mark.asyncio
    async def test_read_file(self, tmp_path):
        tool = FileSystemTool()
        (tmp_path / "test.txt").write_text("hello world", encoding="utf-8")

        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"action": "read", "path": "test.txt"}, ctx)

        assert result.success is True
        assert result.output["content"] == "hello world"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path):
        tool = FileSystemTool()
        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"action": "read", "path": "nope.txt"}, ctx)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_write_file(self, tmp_path):
        tool = FileSystemTool()
        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"action": "write", "path": "new.txt", "content": "created"}, ctx)

        assert result.success is True
        assert (tmp_path / "new.txt").read_text() == "created"

    @pytest.mark.asyncio
    async def test_write_no_content(self, tmp_path):
        tool = FileSystemTool()
        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"action": "write", "path": "new.txt"}, ctx)

        assert result.success is False
        assert "content" in result.error

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, tmp_path):
        tool = FileSystemTool()
        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"action": "read", "path": "../../etc/passwd"}, ctx)

        assert result.success is False
        assert "outside workspace" in result.error

    @pytest.mark.asyncio
    async def test_unknown_action(self, tmp_path):
        tool = FileSystemTool()
        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"action": "delete", "path": "."}, ctx)

        assert result.success is False
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_write_too_large(self, tmp_path):
        tool = FileSystemTool()
        ctx = MagicMock(workspace_root=str(tmp_path))
        result = await tool.execute({"action": "write", "path": "big.txt", "content": "x" * 200_000}, ctx)

        assert result.success is False
        assert "too large" in result.error.lower()


class TestWindowManagerTool:
    """Tests for the WindowManagerTool (desktop.windows)."""

    def test_name_and_description(self):
        tool = WindowManagerTool()
        assert tool.name == "desktop.windows"

    @pytest.mark.asyncio
    async def test_list_windows_windows(self):
        tool = WindowManagerTool()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(
            b'[{"Id": 1234, "ProcessName": "notepad", "MainWindowTitle": "test.txt"}]', b""
        ))

        with patch("platform.system", return_value="Windows"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            ctx = MagicMock(workspace_root="/tmp")
            result = await tool.execute({"action": "list"}, ctx)

        assert result.success is True
        assert len(result.output["windows"]) == 1
        assert result.output["windows"][0]["title"] == "test.txt"

    @pytest.mark.asyncio
    async def test_list_windows_empty(self):
        tool = WindowManagerTool()
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("platform.system", return_value="Windows"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            ctx = MagicMock(workspace_root="/tmp")
            result = await tool.execute({"action": "list"}, ctx)

        assert result.success is True
        assert result.output["windows"] == []

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        tool = WindowManagerTool()
        ctx = MagicMock(workspace_root="/tmp")
        result = await tool.execute({"action": "close"}, ctx)

        assert result.success is False
        assert "Unknown action" in result.error
