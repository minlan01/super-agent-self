"""Tests for stale-gated desktop input and WGC screenshot tools."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.executor.tools.desktop_tools import DesktopClick, DesktopScreenshot, DesktopType
from packages.platform.shared.contracts import Screenshot
from packages.platform.windows.desktop import CoordinateClickResult, DesktopActionResult
from packages.protocol.schemas.enums import Classification


def _adapter(*, window_provider=None, screen_capture=None):  # type: ignore[no-untyped-def]
    adapter = MagicMock()
    adapter.window_provider.return_value = window_provider or MagicMock()
    adapter.screen_capture.return_value = screen_capture or MagicMock()
    return adapter


class TestDesktopClick:
    def test_name(self) -> None:
        assert DesktopClick().name == "desktop.click"

    @pytest.mark.asyncio
    async def test_requires_window_and_digest(self) -> None:
        result = await DesktopClick(adapter=_adapter()).execute({}, MagicMock())

        assert result.success is False
        assert "window_id" in result.error
        assert "expected_ui_digest" in result.error

    @pytest.mark.asyncio
    async def test_coordinate_click_is_disabled_without_explicit_approval(self) -> None:
        provider = MagicMock()
        provider.coordinate_click = AsyncMock()
        tool = DesktopClick(adapter=_adapter(window_provider=provider))

        result = await tool.execute(
            {
                "window_id": "win32:1",
                "expected_ui_digest": "digest",
                "x": 10,
                "y": 20,
            },
            MagicMock(),
        )

        assert result.success is False
        assert "explicit approval" in result.error
        provider.coordinate_click.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_semantic_uia_click(self) -> None:
        provider = MagicMock()
        provider.invoke = AsyncMock(
            return_value=DesktopActionResult(
                success=True,
                window_id="win32:1",
                action="invoke",
                pre_digest="digest",
                post_digest="new-digest",
            )
        )
        tool = DesktopClick(adapter=_adapter(window_provider=provider))

        result = await tool.execute(
            {
                "window_id": "win32:1",
                "expected_ui_digest": "digest",
                "automation_id": "save-button",
                "control_type": "Button",
            },
            MagicMock(),
        )

        assert result.success is True
        assert result.output["pre_digest"] == "digest"
        assert result.output["post_digest"] == "new-digest"
        provider.invoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_approved_coordinate_fallback(self) -> None:
        provider = MagicMock()
        provider.coordinate_click = AsyncMock(
            return_value=CoordinateClickResult(
                success=True,
                window_id="win32:1",
                pre_digest="digest",
                post_digest="new-digest",
                physical_coords=(10, 20),
                logical_coords=(10, 20),
                dpi=96,
                monitor_id="m1",
                error=None,
            )
        )
        tool = DesktopClick(adapter=_adapter(window_provider=provider))

        result = await tool.execute(
            {
                "window_id": "win32:1",
                "expected_ui_digest": "digest",
                "x": 10,
                "y": 20,
                "coordinate_fallback_approved": True,
            },
            MagicMock(),
        )

        assert result.success is True
        provider.coordinate_click.assert_awaited_once()


class TestDesktopType:
    def test_name(self) -> None:
        assert DesktopType().name == "desktop.type"

    @pytest.mark.asyncio
    async def test_requires_semantic_target(self) -> None:
        result = await DesktopType(adapter=_adapter()).execute(
            {"text": "hello", "window_id": "win32:1", "expected_ui_digest": "digest"},
            MagicMock(),
        )

        assert result.success is False
        assert "semantic UIA selector" in result.error

    @pytest.mark.asyncio
    async def test_text_too_long(self) -> None:
        result = await DesktopType(adapter=_adapter()).execute(
            {
                "text": "a" * 501,
                "window_id": "win32:1",
                "expected_ui_digest": "digest",
                "automation_id": "input",
            },
            MagicMock(),
        )

        assert result.success is False
        assert "too long" in result.error.lower()

    @pytest.mark.asyncio
    async def test_type_uses_uia_value_pattern(self) -> None:
        provider = MagicMock()
        provider.set_text = AsyncMock(
            return_value=DesktopActionResult(
                success=True,
                window_id="win32:1",
                action="set_value",
                pre_digest="digest",
                post_digest="new-digest",
            )
        )
        tool = DesktopType(adapter=_adapter(window_provider=provider))

        result = await tool.execute(
            {
                "text": "Hello World",
                "window_id": "win32:1",
                "expected_ui_digest": "digest",
                "automation_id": "input",
                "control_type": "Edit",
            },
            MagicMock(),
        )

        assert result.success is True
        assert result.output["chars"] == 11
        provider.set_text.assert_awaited_once()


class TestDesktopScreenshot:
    def test_name(self) -> None:
        assert DesktopScreenshot().name == "desktop.screenshot"

    @pytest.mark.asyncio
    async def test_screenshot_is_workspace_relative_and_confidential(self, tmp_path) -> None:
        capture = MagicMock()
        capture.grab = AsyncMock(
            return_value=Screenshot(
                data=b"\x89PNG\r\n\x1a\ncontent",
                mime_type="image/png",
                width=640,
                height=480,
                taken_at=datetime.now(UTC),
            )
        )
        tool = DesktopScreenshot(adapter=_adapter(screen_capture=capture))

        result = await tool.execute(
            {"window_id": "win32:1"},
            MagicMock(workspace_root=str(tmp_path)),
        )

        assert result.success is True
        assert len(result.artifacts) == 1
        assert not result.artifacts[0].startswith(str(tmp_path))
        assert result.output["artifact"]["classification"] == Classification.CONFIDENTIAL.value
        assert (tmp_path / result.artifacts[0]).read_bytes().startswith(b"\x89PNG")
        capture.grab.assert_awaited_once_with(window_id="win32:1")

    @pytest.mark.asyncio
    async def test_capture_failure_does_not_create_artifact(self, tmp_path) -> None:
        capture = MagicMock()
        capture.grab = AsyncMock(side_effect=PermissionError("capture denied"))
        tool = DesktopScreenshot(adapter=_adapter(screen_capture=capture))

        result = await tool.execute({}, MagicMock(workspace_root=str(tmp_path)))

        assert result.success is False
        assert result.artifacts == []
        assert not (tmp_path / "screenshots").exists()
