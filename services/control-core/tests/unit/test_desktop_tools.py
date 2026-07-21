"""Tests for Desktop tools — Click, Type, Screenshot."""

from unittest.mock import MagicMock, patch

import pytest

from packages.executor.tools.desktop_tools import DesktopClick, DesktopScreenshot, DesktopType


def _inject_mock_pyautogui(mock_pg=None):
    """Inject a mock pyautogui into sys.modules so local `import pyautogui` succeeds."""
    if mock_pg is None:
        mock_pg = MagicMock()
    mock_pg.FAILSAFE = True
    mock_pg.PAUSE = 0.5
    return mock_pg


# ── DesktopClick ──────────────────────────────────────────────────────────────


class TestDesktopClick:
    def test_name(self):
        assert DesktopClick().name == "desktop.click"

    @pytest.mark.asyncio
    async def test_missing_coordinates(self):
        tool = DesktopClick()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({}, MagicMock())
        assert result.success is False
        assert "coordinates" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_y_coordinate(self):
        tool = DesktopClick()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"x": 100}, MagicMock())
        assert result.success is False

    @pytest.mark.asyncio
    async def test_missing_x_coordinate(self):
        tool = DesktopClick()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"y": 200}, MagicMock())
        assert result.success is False

    @pytest.mark.asyncio
    async def test_pyautogui_not_installed(self):
        tool = DesktopClick()
        with patch.dict("sys.modules", {"pyautogui": None}):
            result = await tool.execute({"x": 100, "y": 200}, MagicMock())
            assert result.success is False
            assert "pyautogui" in result.error

    @pytest.mark.asyncio
    async def test_click_success(self):
        tool = DesktopClick()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"x": 100, "y": 200}, MagicMock())
        assert result.success is True
        assert result.output["action"] == "click"
        assert result.output["x"] == 100
        assert result.output["y"] == 200

    @pytest.mark.asyncio
    async def test_click_with_options(self):
        tool = DesktopClick()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute(
                {"x": 50, "y": 60, "button": "right", "clicks": 2},
                MagicMock(),
            )
        assert result.success is True
        mock_pg.click.assert_called_once_with(x=50, y=60, button="right", clicks=2)

    @pytest.mark.asyncio
    async def test_click_exception_handled(self):
        tool = DesktopClick()
        mock_pg = _inject_mock_pyautogui()
        mock_pg.click.side_effect = Exception("Screen not found")
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"x": 0, "y": 0}, MagicMock())
        assert result.success is False
        assert "Screen not found" in result.error


# ── DesktopType ───────────────────────────────────────────────────────────────


class TestDesktopType:
    def test_name(self):
        assert DesktopType().name == "desktop.type"

    @pytest.mark.asyncio
    async def test_empty_text_rejected(self):
        tool = DesktopType()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"text": ""}, MagicMock())
        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_text_key_rejected(self):
        tool = DesktopType()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({}, MagicMock())
        assert result.success is False

    @pytest.mark.asyncio
    async def test_text_too_long(self):
        tool = DesktopType()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"text": "a" * 501}, MagicMock())
        assert result.success is False
        assert "too long" in result.error.lower()

    @pytest.mark.asyncio
    async def test_text_at_max_length_ok(self):
        tool = DesktopType()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"text": "a" * 500}, MagicMock())
        assert result.success is True

    @pytest.mark.asyncio
    async def test_dangerous_ctrl_blocked(self):
        tool = DesktopType()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"text": "ctrl"}, MagicMock())
        assert result.success is False
        assert "Blocked" in result.error

    @pytest.mark.asyncio
    async def test_dangerous_alt_blocked(self):
        tool = DesktopType()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"text": "alt"}, MagicMock())
        assert result.success is False

    @pytest.mark.asyncio
    async def test_dangerous_delete_blocked(self):
        tool = DesktopType()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"text": "delete"}, MagicMock())
        assert result.success is False

    @pytest.mark.asyncio
    async def test_longer_text_with_ctrl_allowed(self):
        """Text longer than 20 chars containing 'ctrl' is allowed (safety only blocks short combos)."""
        tool = DesktopType()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"text": "I want to control the output"}, MagicMock())
        assert result.success is True

    @pytest.mark.asyncio
    async def test_type_success(self):
        tool = DesktopType()
        mock_pg = _inject_mock_pyautogui()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            result = await tool.execute({"text": "Hello World"}, MagicMock())
        assert result.success is True
        assert result.output["action"] == "type"
        assert result.output["chars"] == 11


# ── DesktopScreenshot ─────────────────────────────────────────────────────────


class TestDesktopScreenshot:
    def test_name(self):
        assert DesktopScreenshot().name == "desktop.screenshot"

    @pytest.mark.asyncio
    async def test_pyautogui_not_installed(self):
        tool = DesktopScreenshot()
        with patch.dict("sys.modules", {"pyautogui": None}):
            result = await tool.execute({}, MagicMock(workspace_root="/tmp"))
            assert result.success is False

    @pytest.mark.asyncio
    async def test_screenshot_success(self, tmp_path):
        tool = DesktopScreenshot()
        mock_pg = _inject_mock_pyautogui()
        mock_img = MagicMock()
        mock_pg.screenshot.return_value = mock_img

        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            context = MagicMock(workspace_root=str(tmp_path))
            result = await tool.execute({}, context)

        assert result.success is True
        assert len(result.artifacts) == 1
        mock_img.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_screenshot_creates_directory(self, tmp_path):
        tool = DesktopScreenshot()
        mock_pg = _inject_mock_pyautogui()
        mock_img = MagicMock()
        mock_pg.screenshot.return_value = mock_img

        ws = tmp_path / "workspace"
        ws.mkdir()
        with patch.dict("sys.modules", {"pyautogui": mock_pg}):
            context = MagicMock(workspace_root=str(ws))
            result = await tool.execute({}, context)

        assert result.success is True
        assert (ws / "screenshots").exists()
