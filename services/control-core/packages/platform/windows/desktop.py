"""P3.11: UI Automation desktop input + P3.12: Windows Graphics Capture.

Defines the contracts for WindowProvider (stale-gated UIA) and
ScreenCapture (WGC with confidential artifacts).

Both contracts implement the shared abstract interfaces from contracts.py.
Actual Win32 implementations require uiautomation library and Windows
Graphics Capture API — capability reports must show unavailable until
fully implemented.

Security invariants (P3.11):
- list_windows returns stable window_id, HWND/PID, title, bounds, DPI, ui_digest
- bind_window generates pre-operation snapshot
- Default path uses UIA control identification (AutomationId, ControlType)
- Pre-side-effect atomic validation: HWND/PID/foreground/lock/DPI/digest
- StaleUIState returned when any validation fails — no side effect sent
- Coordinate click: default disabled, explicit approval required

Security invariants (P3.12):
- ScreenCapture.grab() returns typed Screenshot
- Default CONFIDENTIAL classification
- File save only in task workspace, returns typed artifact metadata
- No arbitrary output paths
"""

from __future__ import annotations

import hashlib
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from packages.platform.shared.errors import CapabilityUnavailable

DESKTOP_INPUT_VERSION = "1.0"
SCREEN_CAPTURE_VERSION = "1.0"


class Classification(str, Enum):
    """Screenshot data classification levels."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class StaleReason(str, Enum):
    """Reasons why a UI state was found stale."""

    HWND_CHANGED = "hwnd_changed"
    PID_CHANGED = "pid_changed"
    FOREGROUND_CHANGED = "foreground_changed"
    LOCKED = "locked"
    DPI_CHANGED = "dpi_changed"
    TOPOLOGY_CHANGED = "topology_changed"
    DIGEST_MISMATCH = "digest_mismatch"
    UNKNOWN_FOCUS = "unknown_focus"


@dataclass(slots=True, frozen=True)
class StaleUIState(Exception):
    """UI state changed before operation — no side effect was sent.

    The caller should NOT retry the operation. Instead, re-list windows
    and re-bind to obtain a fresh digest.
    """

    reason: StaleReason
    expected_digest: str
    actual_digest: str
    detail: str = ""

    def __str__(self) -> str:
        return f"StaleUIState({self.reason.value}): {self.detail}"


# Make StaleUIState properly raiseable
# (dataclass with Exception base works but needs __post_init__ to set Exception args)
def _make_stale_exception(reason: StaleReason, expected: str, actual: str, detail: str = "") -> Exception:
    """Create a StaleUIState exception."""
    exc = Exception(f"StaleUIState({reason.value}): expected={expected[:8]} actual={actual[:8]} {detail}")
    exc.reason = reason  # type: ignore[attr-defined]
    exc.expected_digest = expected  # type: ignore[attr-defined]
    exc.actual_digest = actual  # type: ignore[attr-defined]
    return exc


@dataclass(slots=True, frozen=True)
class WindowSnapshot:
    """Snapshot of a window at bind time.

    Used for stale validation before any side-effect operation.
    """

    window_id: str
    hwnd: int
    pid: int
    title: str
    bounds: tuple[int, int, int, int]  # left, top, right, bottom
    monitor_id: str
    dpi: int
    ui_digest: str  # hash of identifying properties
    is_foreground: bool
    is_locked: bool
    topology_version: int
    captured_at: float = field(default_factory=time.time)


@dataclass(slots=True, frozen=True)
class UIAElement:
    """A UI Automation element descriptor."""

    automation_id: str
    control_type: str  # Button, Edit, ComboBox, etc.
    name: str
    class_name: str
    is_enabled: bool
    is_offscreen: bool
    bounding_rectangle: tuple[int, int, int, int] | None


@dataclass(slots=True, frozen=True)
class DesktopActionResult:
    """Result of a desktop input operation via UIA.

    Includes post-operation digest (not required to match pre-operation).
    """

    success: bool
    window_id: str
    action: str  # "click", "type", "select", "invoke"
    target_element: UIAElement | None = None
    pre_digest: str = ""
    post_digest: str = ""
    error: str | None = None


@dataclass(slots=True, frozen=True)
class CoordinateClickResult:
    """Result of an explicitly-approved coordinate click."""

    success: bool
    window_id: str
    physical_coords: tuple[int, int]
    logical_coords: tuple[int, int]
    dpi: int
    monitor_id: str
    pre_digest: str = ""
    post_digest: str = ""
    error: str | None = None


@dataclass(slots=True, frozen=True)
class ScreenshotResult:
    """Typed screenshot result with classification.

    Default classification is CONFIDENTIAL. This classification must
    propagate through ToolResult, Receipt, API, storage ACL, retention.
    """

    data: bytes
    mime_type: str  # "image/png", "image/jpeg"
    width: int
    height: int
    taken_at: float
    classification: Classification = Classification.CONFIDENTIAL
    monitor_id: str | None = None
    dpi: int | None = None
    topology_version: int | None = None


@dataclass(slots=True, frozen=True)
class ScreenshotArtifact:
    """Metadata for a saved screenshot artifact.

    File save only happens in task workspace. No arbitrary output paths.
    """

    artifact_id: str
    relative_path: str  # relative to workspace root
    mime_type: str
    width: int
    height: int
    sha256: str
    classification: Classification
    size_bytes: int
    created_at: float = field(default_factory=time.time)


def compute_ui_digest(
    hwnd: int, pid: int, title: str, bounds: tuple[int, int, int, int],
) -> str:
    """Compute a stable UI digest for a window snapshot."""
    raw = f"{hwnd}|{pid}|{title}|{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def validate_not_stale(
    snapshot: WindowSnapshot,
    current_hwnd: int,
    current_pid: int,
    current_foreground_hwnd: int,
    is_locked: bool,
    current_dpi: int,
    current_topology_version: int,
    current_digest: str,
) -> None:
    """Validate that a window snapshot is not stale.

    Raises StaleUIState (as Exception) if any validation fails.
    """
    if snapshot.hwnd != current_hwnd:
        raise _make_stale_exception(
            StaleReason.HWND_CHANGED, snapshot.ui_digest, current_digest,
            f"hwnd {snapshot.hwnd} -> {current_hwnd}",
        )
    if snapshot.pid != current_pid:
        raise _make_stale_exception(
            StaleReason.PID_CHANGED, snapshot.ui_digest, current_digest,
            f"pid {snapshot.pid} -> {current_pid}",
        )
    if snapshot.hwnd != current_foreground_hwnd:
        raise _make_stale_exception(
            StaleReason.FOREGROUND_CHANGED, snapshot.ui_digest, current_digest,
            f"foreground changed",
        )
    if is_locked:
        raise _make_stale_exception(
            StaleReason.LOCKED, snapshot.ui_digest, current_digest,
            "screen is locked",
        )
    if snapshot.dpi != current_dpi:
        raise _make_stale_exception(
            StaleReason.DPI_CHANGED, snapshot.ui_digest, current_digest,
            f"dpi {snapshot.dpi} -> {current_dpi}",
        )
    if snapshot.topology_version != current_topology_version:
        raise _make_stale_exception(
            StaleReason.TOPOLOGY_CHANGED, snapshot.ui_digest, current_digest,
            f"topology {snapshot.topology_version} -> {current_topology_version}",
        )
    if snapshot.ui_digest != current_digest:
        raise _make_stale_exception(
            StaleReason.DIGEST_MISMATCH, snapshot.ui_digest, current_digest,
        )


class DesktopInputNotAvailable(CapabilityUnavailable):
    """Desktop input capability is not available."""

    def __init__(self, reason: str = "UIA not available") -> None:
        super().__init__("window_provider", reason)


class ScreenCaptureNotAvailable(CapabilityUnavailable):
    """Screen capture capability is not available."""

    def __init__(self, reason: str = "WGC not available") -> None:
        super().__init__("screen_capture", reason)


def is_uia_available() -> bool:
    """Check if UI Automation is available on this platform."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        uiautomation = ctypes.windll.uiautomation
        return True
    except Exception:
        return False


def is_wgc_available() -> bool:
    """Check if Windows Graphics Capture is available.

    WGC requires Windows 10 1903+ (build 18362+).
    """
    if sys.platform != "win32":
        return False
    try:
        import platform
        build = int(platform.version().split(".")[2])
        return build >= 18362
    except Exception:
        return False


__all__ = [
    "DESKTOP_INPUT_VERSION",
    "SCREEN_CAPTURE_VERSION",
    "Classification",
    "StaleReason",
    "WindowSnapshot",
    "UIAElement",
    "DesktopActionResult",
    "CoordinateClickResult",
    "ScreenshotResult",
    "ScreenshotArtifact",
    "DesktopInputNotAvailable",
    "ScreenCaptureNotAvailable",
    "compute_ui_digest",
    "validate_not_stale",
    "is_uia_available",
    "is_wgc_available",
]
