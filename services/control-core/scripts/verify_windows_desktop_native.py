"""Manual P3.11/P3.12 verification without persisting captured pixels."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import threading
from typing import Any

from packages.platform.windows.adapter import WindowsPlatformAdapter
from packages.protocol.schemas.enums import Capability, Classification


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captures", type=int, default=3)
    parser.add_argument("--window-title", default=None)
    return parser.parse_args()


async def _verify(captures: int, window_title: str | None) -> dict[str, Any]:
    if captures < 2:
        raise ValueError("--captures must be at least 2 for lifecycle verification")

    adapter = WindowsPlatformAdapter()
    report = adapter.get_capabilities()
    required = {Capability.WINDOW_PROVIDER, Capability.SCREEN_CAPTURE}
    missing = required - set(report.capabilities)
    if missing:
        reasons = {
            capability.value: report.unsupported_reasons.get(capability, "unknown")
            for capability in missing
        }
        raise RuntimeError(f"desktop capabilities unavailable: {reasons}")

    provider = adapter.window_provider()
    windows = await provider.list_windows()
    if not windows:
        raise RuntimeError("UIA returned no visible top-level windows")

    foreground_hwnd = int(ctypes.windll.user32.GetForegroundWindow())
    foreground_id = f"win32:{foreground_hwnd:016x}"
    target = next((item for item in windows if item.window_id == foreground_id), None)
    if window_title:
        target = next(
            (item for item in windows if window_title.casefold() in item.title.casefold()),
            None,
        )
    if target is None:
        target = windows[0]

    bound = await provider.bind_window(target.window_id)
    if not await provider.verify_ui_state(bound.window_id, bound.ui_digest):
        raise RuntimeError("UI digest changed immediately after bind")

    screen_capture = adapter.screen_capture()
    captured: list[dict[str, int]] = []
    threads_after_first: list[tuple[str, bool]] | None = None
    for index in range(captures):
        screenshot = await screen_capture.grab(window_id=bound.window_id)
        if screenshot.classification != Classification.CONFIDENTIAL:
            raise RuntimeError("screenshot classification is not confidential")
        if not screenshot.data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("capture did not return a PNG payload")
        captured.append(
            {
                "width": screenshot.width,
                "height": screenshot.height,
                "bytes": len(screenshot.data),
            }
        )
        if index == 0:
            threads_after_first = [(thread.name, thread.daemon) for thread in threading.enumerate()]

    threads_after_last = [(thread.name, thread.daemon) for thread in threading.enumerate()]
    if threads_after_first is None:
        raise RuntimeError("first capture thread snapshot was not recorded")
    if len(threads_after_last) != len(threads_after_first):
        raise RuntimeError("Python thread count grew after repeated WGC captures")
    if screen_capture._lock.locked():
        raise RuntimeError("capture lifecycle lock was not released")

    return {
        "status": "PASS",
        "platform": report.platform,
        "platform_version": report.platform_version,
        "window_count": len(windows),
        "bound_window": {
            "window_id": bound.window_id,
            "pid": bound.pid,
            "title": bound.title,
            "ui_digest": bound.ui_digest,
        },
        "captures": captured,
        "python_threads_after_first": threads_after_first,
        "python_threads_after_last": threads_after_last,
        "capture_lock_released": True,
        "pixels_persisted": False,
    }


def main() -> None:
    args = _parse_args()
    result = asyncio.run(_verify(args.captures, args.window_title))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
