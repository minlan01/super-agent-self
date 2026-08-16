"""Single-frame Windows Graphics Capture implementation with strict cleanup."""

from __future__ import annotations

import asyncio
import io
import platform
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from packages.platform.shared.contracts import ScreenCapture, Screenshot
from packages.protocol.schemas.enums import Classification

from .desktop import ScreenCaptureNotAvailable
from .uia import WindowsUIAWindowProvider

_DEFAULT_CAPTURE_TIMEOUT_SEC = 5.0


class WindowsGraphicsCapture(ScreenCapture):
    """Capture one monitor or HWND frame through the Windows Graphics Capture API."""

    def __init__(
        self,
        *,
        window_provider: WindowsUIAWindowProvider | Any | None = None,
        capture_factory: Callable[..., Any] | None = None,
        frame_encoder: Callable[[Any, Classification], bytes] | None = None,
        timeout_sec: float = _DEFAULT_CAPTURE_TIMEOUT_SEC,
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("capture timeout must be positive")
        self._window_provider = window_provider
        self._capture_factory = capture_factory
        self._frame_encoder = frame_encoder or self._encode_png
        self._timeout_sec = timeout_sec
        self._lock = threading.Lock()

    @staticmethod
    def is_supported() -> bool:
        if sys.platform != "win32":
            return False
        try:
            build = int(platform.version().split(".")[2])
            if build < 18362:
                return False
            from windows_capture import WindowsCapture

            return WindowsCapture is not None
        except Exception:
            return False

    @staticmethod
    def _native_factory() -> Callable[..., Any]:
        from windows_capture import WindowsCapture

        return WindowsCapture

    @staticmethod
    def _encode_png(frame: Any, classification: Classification) -> bytes:
        import numpy
        from PIL import Image, ImageDraw, ImageFont

        bgra = numpy.asarray(frame.frame_buffer)
        if bgra.ndim != 3 or bgra.shape[2] != 4:
            raise ValueError("WGC frame is not BGRA/RGBA")
        rgba = bgra[:, :, [2, 1, 0, 3]].copy()
        image = Image.fromarray(rgba)
        if classification == Classification.CONFIDENTIAL:
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            font = ImageFont.load_default()
            label = "CONFIDENTIAL - ZCODE"
            text_box = draw.textbbox((0, 0), label, font=font)
            text_width = text_box[2] - text_box[0]
            text_height = text_box[3] - text_box[1]
            padding = 4
            x = max(0, image.width - text_width - padding * 2)
            y = max(0, image.height - text_height - padding * 2)
            draw.rectangle(
                (x, y, image.width, image.height),
                fill=(128, 0, 0, 190),
            )
            draw.text(
                (x + padding, y + padding),
                label,
                fill=(255, 255, 255, 255),
                font=font,
            )
            image = Image.alpha_composite(image, overlay)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=False)
        return output.getvalue()

    def _resolve_hwnd(self, window_id: str | None) -> int | None:
        if window_id is None:
            return None
        if self._window_provider is None:
            raise ScreenCaptureNotAvailable("window capture requires a WindowProvider")
        return int(self._window_provider.hwnd_for_window_id(window_id))

    def _grab_sync(self, window_id: str | None) -> Screenshot:
        hwnd = self._resolve_hwnd(window_id)
        factory = self._capture_factory or self._native_factory()
        classification = Classification.CONFIDENTIAL
        frame_ready = threading.Event()
        capture_closed = threading.Event()
        result: dict[str, Any] = {}
        callback_error: list[BaseException] = []
        control: Any | None = None

        kwargs: dict[str, Any] = {
            "cursor_capture": False,
            "draw_border": False,
            "monitor_index": None,
        }
        if hwnd is not None:
            kwargs["window_hwnd"] = hwnd

        try:
            capture = factory(**kwargs)

            @capture.event
            def on_frame_arrived(frame: Any, capture_control: Any) -> None:
                try:
                    result["data"] = self._frame_encoder(frame, classification)
                    result["width"] = int(frame.width)
                    result["height"] = int(frame.height)
                except BaseException as exc:
                    callback_error.append(exc)
                finally:
                    capture_control.stop()
                    frame_ready.set()

            @capture.event
            def on_closed() -> None:
                capture_closed.set()
                frame_ready.set()

            control = capture.start_free_threaded()
            if not frame_ready.wait(self._timeout_sec):
                raise TimeoutError("WGC did not deliver a frame before timeout")
            if callback_error:
                raise callback_error[0]
            if "data" not in result:
                reason = "capture target closed" if capture_closed.is_set() else "no frame returned"
                raise RuntimeError(reason)
            return Screenshot(
                data=result["data"],
                mime_type="image/png",
                width=result["width"],
                height=result["height"],
                taken_at=datetime.now(UTC),
                classification=classification,
            )
        except ScreenCaptureNotAvailable:
            raise
        except BaseException as exc:
            raise ScreenCaptureNotAvailable(
                f"Windows Graphics Capture failed closed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if control is not None:
                try:
                    control.stop()
                finally:
                    control.wait()

    async def grab(self, *, window_id: str | None = None) -> Screenshot:
        if self._capture_factory is None and not self.is_supported():
            raise ScreenCaptureNotAvailable("Windows Graphics Capture dependency unavailable")
        if not self._lock.acquire(blocking=False):
            raise ScreenCaptureNotAvailable("another capture session is already active")
        try:
            return await asyncio.to_thread(self._grab_sync, window_id)
        finally:
            self._lock.release()


__all__ = ["WindowsGraphicsCapture"]
