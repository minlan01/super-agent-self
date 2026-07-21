"""Unit tests for File tools -- FileWriteMarkdown, FileRead, FileList, FileWriteDocx."""

from pathlib import Path

import pytest

from packages.executor.tools.base import ExecutionContext
from packages.executor.tools.file_tools import (
    FileList,
    FileRead,
    FileWriteDocx,
    FileWriteMarkdown,
    _check_path_within_base,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(tmp_dir: str) -> ExecutionContext:
    return ExecutionContext(
        task_id="t1",
        step_id="s1",
        workspace_root=tmp_dir,
        outputs_dir="outputs",
        screenshots_dir="screenshots",
    )


# ---------------------------------------------------------------------------
# _check_path_within_base tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckPathWithinBase:
    def test_path_inside_base(self, tmp_path):
        inner = tmp_path / "subdir" / "file.txt"
        ok, err = _check_path_within_base(inner, tmp_path)
        assert ok is True
        assert err == ""

    def test_path_equals_base(self, tmp_path):
        ok, err = _check_path_within_base(tmp_path, tmp_path)
        assert ok is True

    def test_path_escapes_with_dotdot(self, tmp_path):
        escape = tmp_path / ".." / ".." / "etc" / "passwd"
        ok, err = _check_path_within_base(escape, tmp_path)
        assert ok is False
        assert "escapes workspace" in err

    def test_path_absolute_outside(self, tmp_path):
        ok, err = _check_path_within_base(Path("/etc/passwd"), tmp_path)
        assert ok is False


# ---------------------------------------------------------------------------
# FileWriteMarkdown tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileWriteMarkdown:
    @pytest.mark.asyncio
    async def test_write_content(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileWriteMarkdown()
        result = await tool.execute(
            {"output_path": "hello.md", "content": "# Hello\n\nWorld"},
            ctx,
        )
        assert result.success is True
        assert len(result.artifacts) == 1

        # Verify file content
        written = Path(result.artifacts[0])
        assert written.read_text(encoding="utf-8") == "# Hello\n\nWorld"

    @pytest.mark.asyncio
    async def test_write_creates_subdirs(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileWriteMarkdown()
        result = await tool.execute(
            {"output_path": "sub/dir/nested.md", "content": "nested"},
            ctx,
        )
        assert result.success is True
        assert Path(result.artifacts[0]).is_file()

    @pytest.mark.asyncio
    async def test_workspace_escape_rejected(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileWriteMarkdown()
        result = await tool.execute(
            {"output_path": "../../../etc/passwd", "content": "evil"},
            ctx,
        )
        assert result.success is False
        assert "escapes workspace" in result.error

    @pytest.mark.asyncio
    async def test_default_output_path(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileWriteMarkdown()
        result = await tool.execute({"content": "default"}, ctx)
        assert result.success is True
        assert result.artifacts[0].endswith("output.md")

    @pytest.mark.asyncio
    async def test_empty_content(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileWriteMarkdown()
        result = await tool.execute({"output_path": "empty.md", "content": ""}, ctx)
        assert result.success is True


# ---------------------------------------------------------------------------
# FileRead tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileRead:
    @pytest.mark.asyncio
    async def test_read_content(self, tmp_path):
        # Create a file in workspace
        (tmp_path / "data.txt").write_text("hello world", encoding="utf-8")

        ctx = _make_context(str(tmp_path))
        tool = FileRead()
        result = await tool.execute({"path": "data.txt"}, ctx)
        assert result.success is True
        assert result.output == "hello world"

    @pytest.mark.asyncio
    async def test_read_missing_path(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileRead()
        result = await tool.execute({}, ctx)
        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileRead()
        result = await tool.execute({"path": "nonexistent.txt"}, ctx)
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_workspace_escape_rejected(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileRead()
        result = await tool.execute({"path": "../../../etc/passwd"}, ctx)
        assert result.success is False
        assert "escapes workspace" in result.error


# ---------------------------------------------------------------------------
# FileList tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileList:
    @pytest.mark.asyncio
    async def test_list_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "c.txt").write_text("c")

        ctx = _make_context(str(tmp_path))
        tool = FileList()
        result = await tool.execute({"path": "."}, ctx)
        assert result.success is True
        # Only top-level files
        assert "a.txt" in result.output
        assert "b.txt" in result.output
        assert "subdir" not in result.output  # dirs excluded

    @pytest.mark.asyncio
    async def test_list_with_pattern(self, tmp_path):
        (tmp_path / "readme.md").write_text("md")
        (tmp_path / "report.md").write_text("md")
        (tmp_path / "data.txt").write_text("txt")

        ctx = _make_context(str(tmp_path))
        tool = FileList()
        result = await tool.execute({"path": ".", "pattern": "*.md"}, ctx)
        assert result.success is True
        assert len(result.output) == 2
        assert "readme.md" in result.output
        assert "report.md" in result.output

    @pytest.mark.asyncio
    async def test_list_nonexistent_dir(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileList()
        result = await tool.execute({"path": "nonexistent"}, ctx)
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_list_workspace_escape_rejected(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileList()
        result = await tool.execute({"path": "../../../etc"}, ctx)
        assert result.success is False
        assert "escapes workspace" in result.error

    @pytest.mark.asyncio
    async def test_list_subdirectory(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "file1.txt").write_text("1")
        (sub / "file2.txt").write_text("2")

        ctx = _make_context(str(tmp_path))
        tool = FileList()
        result = await tool.execute({"path": "subdir"}, ctx)
        assert result.success is True
        assert len(result.output) == 2


# ---------------------------------------------------------------------------
# FileWriteDocx tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFileWriteDocx:
    @pytest.mark.asyncio
    async def test_docx_missing_library(self):
        """If python-docx is not installed, should return error gracefully."""
        try:
            import docx  # noqa: F401
            pytest.skip("python-docx is installed, cannot test missing-library path")
        except ImportError:
            pass

        tool = FileWriteDocx()
        ctx = _make_context("/tmp")

        result = await tool.execute(
            {"output_path": "test.docx", "title": "Test", "paragraphs": ["Hello"]},
            ctx,
        )
        assert result.success is False
        assert "python-docx not installed" in result.error

    @pytest.mark.asyncio
    async def test_docx_workspace_escape(self, tmp_path):
        ctx = _make_context(str(tmp_path))
        tool = FileWriteDocx()
        result = await tool.execute(
            {"output_path": "../../../etc/passwd", "title": "T", "paragraphs": []},
            ctx,
        )
        assert result.success is False
        assert "escapes workspace" in result.error
