"""Behavior tests for the native Windows UI Automation provider."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from packages.platform.shared.contracts import WindowInfo, WindowProvider
from packages.platform.shared.errors import StaleUIState
from packages.platform.windows.desktop import StaleReason
from packages.platform.windows.uia import WindowsUIAWindowProvider


@dataclass
class _Rect:
    left: int
    top: int
    right: int
    bottom: int


class _InvokePattern:
    def __init__(self, control: _Control) -> None:
        self.control = control

    def Invoke(self) -> None:  # noqa: N802 - mirrors the native UIA API
        self.control.invoke_count += 1


class _ValuePattern:
    def __init__(self, control: _Control) -> None:
        self.control = control

    def SetValue(self, value: str) -> None:  # noqa: N802 - mirrors the native UIA API
        self.control.value = value


@dataclass
class _Control:
    Name: str
    NativeWindowHandle: int = 0
    ProcessId: int = 0
    ControlTypeName: str = "PaneControl"
    AutomationId: str = ""
    ClassName: str = ""
    IsEnabled: bool = True
    IsOffscreen: bool = False
    BoundingRectangle: _Rect = field(default_factory=lambda: _Rect(0, 0, 100, 100))
    children: list[_Control] = field(default_factory=list)
    invoke_count: int = 0
    value: str = ""

    def GetChildren(self) -> list[_Control]:  # noqa: N802 - mirrors the native UIA API
        return list(self.children)

    def GetInvokePattern(self) -> _InvokePattern:  # noqa: N802 - native UIA API
        return _InvokePattern(self)

    def GetValuePattern(self) -> _ValuePattern:  # noqa: N802 - native UIA API
        return _ValuePattern(self)


class _Backend:
    def __init__(self, window: _Control) -> None:
        self.window = window
        self.foreground_hwnd = window.NativeWindowHandle
        self.locked = False
        self.dpi = 144
        self.monitor_id = "monitor-1"
        self.topology_version = 7
        self.coordinate_clicks: list[tuple[int, int]] = []

    def probe(self) -> bool:
        return True

    def top_level_windows(self) -> list[_Control]:
        return [self.window]

    def control_from_hwnd(self, hwnd: int) -> _Control | None:
        return self.window if hwnd == self.window.NativeWindowHandle else None

    def get_foreground_hwnd(self) -> int:
        return self.foreground_hwnd

    def is_session_locked(self) -> bool:
        return self.locked

    def get_dpi(self, hwnd: int) -> int:
        return self.dpi

    def get_monitor_identity(self, hwnd: int) -> tuple[str, int]:
        return self.monitor_id, self.topology_version

    def coordinate_click(self, x: int, y: int) -> None:
        self.coordinate_clicks.append((x, y))


@pytest.fixture
def provider_and_controls() -> tuple[WindowsUIAWindowProvider, _Backend, _Control, _Control]:
    button = _Control(
        Name="Save",
        ControlTypeName="ButtonControl",
        AutomationId="save-button",
        ClassName="Button",
        BoundingRectangle=_Rect(10, 20, 80, 50),
    )
    edit = _Control(
        Name="Title",
        ControlTypeName="EditControl",
        AutomationId="title-input",
        ClassName="Edit",
        BoundingRectangle=_Rect(10, 60, 200, 90),
    )
    window = _Control(
        Name="Editor",
        NativeWindowHandle=0x1234,
        ProcessId=4242,
        ControlTypeName="WindowControl",
        ClassName="EditorWindow",
        BoundingRectangle=_Rect(0, 0, 800, 600),
        children=[button, edit],
    )
    backend = _Backend(window)
    return WindowsUIAWindowProvider(backend=backend), backend, button, edit


@pytest.mark.asyncio
async def test_list_and_bind_return_shared_window_info(provider_and_controls) -> None:
    provider, _, _, _ = provider_and_controls

    windows = await provider.list_windows()
    bound = await provider.bind_window(windows[0].window_id)

    assert isinstance(provider, WindowProvider)
    assert windows == [bound]
    assert isinstance(bound, WindowInfo)
    assert bound.window_id == "win32:0000000000001234"
    assert bound.pid == 4242
    assert len(bound.ui_digest) == 64


@pytest.mark.asyncio
async def test_verify_ui_state_detects_tree_change(provider_and_controls) -> None:
    provider, _, button, _ = provider_and_controls
    bound = await provider.bind_window("win32:0000000000001234")

    assert await provider.verify_ui_state(bound.window_id, bound.ui_digest) is True
    button.Name = "Save As"
    assert await provider.verify_ui_state(bound.window_id, bound.ui_digest) is False


@pytest.mark.asyncio
async def test_invoke_uses_uia_pattern_and_returns_post_digest(provider_and_controls) -> None:
    provider, _, button, _ = provider_and_controls
    bound = await provider.bind_window("win32:0000000000001234")

    result = await provider.invoke(
        bound.window_id,
        bound.ui_digest,
        automation_id="save-button",
        control_type="Button",
    )

    assert result.success is True
    assert result.pre_digest == bound.ui_digest
    assert result.post_digest
    assert result.target_element is not None
    assert result.target_element.automation_id == "save-button"
    assert button.invoke_count == 1


@pytest.mark.asyncio
async def test_stale_foreground_fails_before_side_effect(provider_and_controls) -> None:
    provider, backend, button, _ = provider_and_controls
    bound = await provider.bind_window("win32:0000000000001234")
    backend.foreground_hwnd = 0x9999

    with pytest.raises(StaleUIState) as exc_info:
        await provider.invoke(
            bound.window_id,
            bound.ui_digest,
            automation_id="save-button",
        )

    assert getattr(exc_info.value, "reason") == StaleReason.FOREGROUND_CHANGED
    assert button.invoke_count == 0


@pytest.mark.asyncio
async def test_set_text_uses_value_pattern(provider_and_controls) -> None:
    provider, _, _, edit = provider_and_controls
    bound = await provider.bind_window("win32:0000000000001234")

    result = await provider.set_text(
        bound.window_id,
        bound.ui_digest,
        "Quarterly report",
        automation_id="title-input",
        control_type="Edit",
    )

    assert result.success is True
    assert edit.value == "Quarterly report"


@pytest.mark.asyncio
async def test_coordinate_click_requires_explicit_approval(provider_and_controls) -> None:
    provider, backend, _, _ = provider_and_controls
    bound = await provider.bind_window("win32:0000000000001234")

    with pytest.raises(PermissionError, match="explicit approval"):
        await provider.coordinate_click(
            bound.window_id,
            bound.ui_digest,
            x=25,
            y=35,
            approved=False,
        )
    assert backend.coordinate_clicks == []

    result = await provider.coordinate_click(
        bound.window_id,
        bound.ui_digest,
        x=25,
        y=35,
        approved=True,
    )
    assert result.success is True
    assert backend.coordinate_clicks == [(25, 35)]
