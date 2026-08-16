"""Windows Graphics Capture behavior and lifecycle tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from packages.platform.shared.contracts import ScreenCapture, Screenshot, WindowInfo
from packages.platform.shared.errors import CapabilityUnavailable
from packages.platform.windows.capture_wgc import WindowsGraphicsCapture
from packages.protocol.schemas.enums import Classification


class _WindowProvider:
    async def list_windows(self) -> list[WindowInfo]:
        return []

    async def bind_window(self, window_id: str) -> WindowInfo:
        return WindowInfo(window_id=window_id, title="Editor", pid=1, ui_digest="digest")

    async def verify_ui_state(self, window_id: str, expected_digest: str) -> bool:
        return True

    def hwnd_for_window_id(self, window_id: str) -> int:
        assert window_id == "win32:0000000000001234"
        return 0x1234


class _InternalControl:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _CaptureControl:
    def __init__(self) -> None:
        self.stopped = False
        self.waited = False

    def stop(self) -> None:
        self.stopped = True

    def wait(self) -> None:
        self.waited = True


class _Capture:
    instances: list[_Capture] = []

    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        self.handlers = {}
        self.control = _CaptureControl()
        self.internal_control = _InternalControl()
        self.__class__.instances.append(self)

    def event(self, handler):  # type: ignore[no-untyped-def]
        self.handlers[handler.__name__] = handler
        return handler

    def start_free_threaded(self) -> _CaptureControl:
        frame = SimpleNamespace(width=640, height=480, frame_buffer=b"frame")
        self.handlers["on_frame_arrived"](frame, self.internal_control)
        return self.control


@pytest.fixture(autouse=True)
def _clear_instances() -> None:
    _Capture.instances.clear()


@pytest.mark.asyncio
async def test_grab_returns_shared_confidential_screenshot_and_closes_session() -> None:
    capture = WindowsGraphicsCapture(
        window_provider=_WindowProvider(),
        capture_factory=_Capture,
        frame_encoder=lambda frame, classification: b"PNG-CONFIDENTIAL",
    )

    result = await capture.grab(window_id="win32:0000000000001234")

    assert isinstance(capture, ScreenCapture)
    assert isinstance(result, Screenshot)
    assert result.data == b"PNG-CONFIDENTIAL"
    assert result.mime_type == "image/png"
    assert result.width == 640
    assert result.height == 480
    assert isinstance(result.taken_at, datetime)
    assert result.classification == Classification.CONFIDENTIAL
    instance = _Capture.instances[0]
    assert instance.kwargs["window_hwnd"] == 0x1234
    assert instance.internal_control.stopped is True
    assert instance.control.stopped is True
    assert instance.control.waited is True


@pytest.mark.asyncio
async def test_constructor_or_permission_failure_fails_closed() -> None:
    def denied_factory(**kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError("screen capture denied")

    capture = WindowsGraphicsCapture(
        window_provider=_WindowProvider(),
        capture_factory=denied_factory,
        frame_encoder=lambda frame, classification: b"unused",
    )

    with pytest.raises(CapabilityUnavailable, match="denied"):
        await capture.grab()


def test_confidential_encoder_adds_visible_watermark() -> None:
    pytest.importorskip("PIL")
    numpy = pytest.importorskip("numpy")
    frame = SimpleNamespace(
        width=80,
        height=40,
        frame_buffer=numpy.zeros((40, 80, 4), dtype=numpy.uint8),
    )

    encoded = WindowsGraphicsCapture._encode_png(frame, Classification.CONFIDENTIAL)

    assert encoded.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(encoded) > 100
