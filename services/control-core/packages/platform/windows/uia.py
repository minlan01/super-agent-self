"""Native Windows UI Automation provider with fail-closed stale-state gates."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import threading
from contextlib import nullcontext
from typing import Any

from packages.platform.shared.contracts import WindowInfo, WindowProvider
from packages.platform.shared.errors import CapabilityUnavailable

from .desktop import (
    CoordinateClickResult,
    DesktopActionResult,
    DesktopInputNotAvailable,
    StaleReason,
    StaleUIState,
    UIAElement,
    WindowSnapshot,
    validate_not_stale,
)

_WINDOW_ID_PREFIX = "win32:"
_MAX_TREE_DEPTH = 5
_MAX_TREE_NODES = 512


class _NativeUIABackend:
    """Small wrapper around uiautomation and user32 for testable native access."""

    @staticmethod
    def _automation():  # type: ignore[no-untyped-def]
        import uiautomation

        return uiautomation

    def thread_context(self):  # type: ignore[no-untyped-def]
        return self._automation().UIAutomationInitializerInThread()

    def probe(self) -> bool:
        root = self._automation().GetRootControl()
        return root is not None

    def top_level_windows(self) -> list[Any]:
        return list(self._automation().GetRootControl().GetChildren())

    def control_from_hwnd(self, hwnd: int) -> Any | None:
        return self._automation().ControlFromHandle(hwnd)

    @staticmethod
    def get_foreground_hwnd() -> int:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow())

    @staticmethod
    def is_session_locked() -> bool:
        from .session_monitor import WindowsSessionMonitor

        return WindowsSessionMonitor._is_session_locked()

    @staticmethod
    def get_dpi(hwnd: int) -> int:
        import ctypes

        user32 = ctypes.windll.user32
        get_dpi = getattr(user32, "GetDpiForWindow", None)
        if get_dpi is None:
            return 96
        dpi = int(get_dpi(hwnd))
        return dpi if dpi > 0 else 96

    @staticmethod
    def get_monitor_identity(hwnd: int) -> tuple[str, int]:
        import ctypes

        user32 = ctypes.windll.user32
        monitor = int(user32.MonitorFromWindow(hwnd, 2))  # MONITOR_DEFAULTTONEAREST
        metrics = (
            int(user32.GetSystemMetrics(80)),  # SM_CMONITORS
            int(user32.GetSystemMetrics(76)),  # SM_XVIRTUALSCREEN
            int(user32.GetSystemMetrics(77)),  # SM_YVIRTUALSCREEN
            int(user32.GetSystemMetrics(78)),  # SM_CXVIRTUALSCREEN
            int(user32.GetSystemMetrics(79)),  # SM_CYVIRTUALSCREEN
        )
        digest = hashlib.sha256(repr(metrics).encode("ascii")).hexdigest()
        return f"monitor:{monitor:016x}", int(digest[:8], 16)

    def coordinate_click(self, x: int, y: int) -> None:
        self._automation().Click(x, y)


class WindowsUIAWindowProvider(WindowProvider):
    """Enumerate, bind, validate, and act on windows through UI Automation."""

    def __init__(
        self,
        *,
        backend: Any | None = None,
        max_tree_depth: int = _MAX_TREE_DEPTH,
        max_tree_nodes: int = _MAX_TREE_NODES,
    ) -> None:
        if max_tree_depth < 1 or max_tree_nodes < 1:
            raise ValueError("UIA tree limits must be positive")
        self._backend = backend or _NativeUIABackend()
        self._max_tree_depth = max_tree_depth
        self._max_tree_nodes = max_tree_nodes
        self._bindings: dict[str, WindowSnapshot] = {}
        self._lock = threading.RLock()

    @staticmethod
    def is_supported() -> bool:
        if sys.platform != "win32":
            return False
        try:
            return bool(_NativeUIABackend().probe())
        except Exception:
            return False

    def _thread_context(self):  # type: ignore[no-untyped-def]
        factory = getattr(self._backend, "thread_context", None)
        return factory() if factory is not None else nullcontext()

    @staticmethod
    def _window_id(hwnd: int) -> str:
        return f"{_WINDOW_ID_PREFIX}{hwnd:016x}"

    @staticmethod
    def hwnd_for_window_id(window_id: str) -> int:
        if not isinstance(window_id, str) or not window_id.startswith(_WINDOW_ID_PREFIX):
            raise ValueError("window_id must use the win32:<hwnd> format")
        try:
            hwnd = int(window_id[len(_WINDOW_ID_PREFIX):], 16)
        except ValueError as exc:
            raise ValueError("window_id contains an invalid HWND") from exc
        if hwnd <= 0:
            raise ValueError("window_id contains an invalid HWND")
        return hwnd

    @staticmethod
    def _safe_property(control: Any, name: str, default: Any) -> Any:
        try:
            value = getattr(control, name)
            return default if value is None else value
        except Exception:
            return default

    @classmethod
    def _bounds(cls, control: Any) -> tuple[int, int, int, int]:
        rect = cls._safe_property(control, "BoundingRectangle", None)
        if rect is None:
            return (0, 0, 0, 0)
        if isinstance(rect, (tuple, list)) and len(rect) == 4:
            return tuple(int(value) for value in rect)  # type: ignore[return-value]
        try:
            return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
        except Exception:
            return (0, 0, 0, 0)

    @staticmethod
    def _normalized_control_type(value: str) -> str:
        normalized = str(value or "").strip().casefold()
        return normalized[:-7] if normalized.endswith("control") else normalized

    def _control_record(self, control: Any, depth: int) -> tuple[Any, ...]:
        return (
            depth,
            str(self._safe_property(control, "AutomationId", "")),
            str(self._safe_property(control, "ControlTypeName", "")),
            str(self._safe_property(control, "Name", "")),
            str(self._safe_property(control, "ClassName", "")),
            bool(self._safe_property(control, "IsEnabled", False)),
            bool(self._safe_property(control, "IsOffscreen", True)),
            self._bounds(control),
        )

    def _walk_controls(self, root: Any) -> list[tuple[Any, int]]:
        queue: list[tuple[Any, int]] = [(root, 0)]
        controls: list[tuple[Any, int]] = []
        while queue and len(controls) < self._max_tree_nodes:
            control, depth = queue.pop(0)
            controls.append((control, depth))
            if depth >= self._max_tree_depth:
                continue
            try:
                children = list(control.GetChildren())
            except Exception as exc:
                raise DesktopInputNotAvailable(
                    f"UIA tree enumeration failed: {type(exc).__name__}"
                ) from exc
            queue.extend((child, depth + 1) for child in children)
        if queue:
            controls.append(("__truncated__", self._max_tree_depth + 1))
        return controls

    def _tree_digest(self, root: Any, *, hwnd: int, pid: int) -> str:
        records: list[Any] = [("window", hwnd, pid)]
        for control, depth in self._walk_controls(root):
            if control == "__truncated__":
                records.append(("truncated", depth))
            else:
                records.append(self._control_record(control, depth))
        payload = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()

    def _resolve_window(self, window_id: str) -> tuple[Any, int]:
        hwnd = self.hwnd_for_window_id(window_id)
        control = self._backend.control_from_hwnd(hwnd)
        if control is None:
            raise StaleUIState(
                StaleReason.HWND_CHANGED,
                self._bindings.get(window_id, WindowSnapshot(
                    window_id=window_id,
                    hwnd=hwnd,
                    pid=0,
                    title="",
                    bounds=(0, 0, 0, 0),
                    monitor_id="",
                    dpi=96,
                    ui_digest="",
                    is_foreground=False,
                    is_locked=True,
                    topology_version=0,
                )).ui_digest,
                "",
                "window no longer exists",
            )
        return control, hwnd

    def _snapshot(self, control: Any, hwnd: int) -> WindowSnapshot:
        pid = int(self._safe_property(control, "ProcessId", 0))
        if pid <= 0:
            raise DesktopInputNotAvailable("UIA window has no valid process identity")
        title = str(self._safe_property(control, "Name", ""))
        bounds = self._bounds(control)
        monitor_id, topology_version = self._backend.get_monitor_identity(hwnd)
        dpi = int(self._backend.get_dpi(hwnd))
        digest = self._tree_digest(control, hwnd=hwnd, pid=pid)
        foreground = int(self._backend.get_foreground_hwnd())
        locked = bool(self._backend.is_session_locked())
        return WindowSnapshot(
            window_id=self._window_id(hwnd),
            hwnd=hwnd,
            pid=pid,
            title=title,
            bounds=bounds,
            monitor_id=str(monitor_id),
            dpi=dpi,
            ui_digest=digest,
            is_foreground=foreground == hwnd,
            is_locked=locked,
            topology_version=int(topology_version),
        )

    @staticmethod
    def _window_info(snapshot: WindowSnapshot) -> WindowInfo:
        return WindowInfo(
            window_id=snapshot.window_id,
            title=snapshot.title,
            pid=snapshot.pid,
            ui_digest=snapshot.ui_digest,
        )

    def _list_windows_sync(self) -> list[WindowInfo]:
        with self._thread_context(), self._lock:
            windows: list[WindowInfo] = []
            for control in self._backend.top_level_windows():
                hwnd = int(self._safe_property(control, "NativeWindowHandle", 0))
                if hwnd <= 0:
                    continue
                bounds = self._bounds(control)
                if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                    continue
                try:
                    windows.append(self._window_info(self._snapshot(control, hwnd)))
                except Exception:
                    continue
            return windows

    async def list_windows(self) -> list[WindowInfo]:
        return await asyncio.to_thread(self._list_windows_sync)

    def _bind_window_sync(self, window_id: str) -> WindowInfo:
        with self._thread_context(), self._lock:
            control, hwnd = self._resolve_window(window_id)
            snapshot = self._snapshot(control, hwnd)
            self._bindings[window_id] = snapshot
            return self._window_info(snapshot)

    async def bind_window(self, window_id: str) -> WindowInfo:
        return await asyncio.to_thread(self._bind_window_sync, window_id)

    def _verify_ui_state_sync(self, window_id: str, expected_digest: str) -> bool:
        with self._thread_context(), self._lock:
            try:
                control, hwnd = self._resolve_window(window_id)
                return self._snapshot(control, hwnd).ui_digest == expected_digest
            except Exception:
                return False

    async def verify_ui_state(self, window_id: str, expected_digest: str) -> bool:
        return await asyncio.to_thread(
            self._verify_ui_state_sync,
            window_id,
            expected_digest,
        )

    def _validate_effect_state(
        self,
        window_id: str,
        expected_digest: str,
        control: Any,
        hwnd: int,
    ) -> WindowSnapshot:
        baseline = self._bindings.get(window_id)
        if baseline is None:
            raise StaleUIState(
                StaleReason.UNKNOWN_FOCUS,
                expected_digest,
                "",
                "window is not bound; call bind_window first",
            )
        if baseline.ui_digest != expected_digest:
            raise StaleUIState(
                StaleReason.DIGEST_MISMATCH,
                expected_digest,
                baseline.ui_digest,
                "expected digest does not match the bound snapshot",
            )
        current = self._snapshot(control, hwnd)
        validate_not_stale(
            baseline,
            current_hwnd=current.hwnd,
            current_pid=current.pid,
            current_foreground_hwnd=int(self._backend.get_foreground_hwnd()),
            is_locked=current.is_locked,
            current_dpi=current.dpi,
            current_topology_version=current.topology_version,
            current_digest=current.ui_digest,
        )
        return current

    def _matches_selector(
        self,
        control: Any,
        *,
        automation_id: str | None,
        control_type: str | None,
        name: str | None,
        class_name: str | None,
    ) -> bool:
        if automation_id is not None and str(
            self._safe_property(control, "AutomationId", "")
        ) != automation_id:
            return False
        if control_type is not None and self._normalized_control_type(
            str(self._safe_property(control, "ControlTypeName", ""))
        ) != self._normalized_control_type(control_type):
            return False
        if name is not None and str(self._safe_property(control, "Name", "")) != name:
            return False
        if class_name is not None and str(
            self._safe_property(control, "ClassName", "")
        ) != class_name:
            return False
        return True

    def _find_element(
        self,
        root: Any,
        *,
        automation_id: str | None,
        control_type: str | None,
        name: str | None,
        class_name: str | None,
    ) -> Any:
        if not any((automation_id, control_type, name, class_name)):
            raise ValueError("at least one semantic UIA selector is required")
        for control, _ in self._walk_controls(root):
            if control == "__truncated__":
                continue
            if self._matches_selector(
                control,
                automation_id=automation_id,
                control_type=control_type,
                name=name,
                class_name=class_name,
            ):
                return control
        raise LookupError("UIA element not found")

    def _element_info(self, control: Any) -> UIAElement:
        return UIAElement(
            automation_id=str(self._safe_property(control, "AutomationId", "")),
            control_type=str(self._safe_property(control, "ControlTypeName", "")),
            name=str(self._safe_property(control, "Name", "")),
            class_name=str(self._safe_property(control, "ClassName", "")),
            is_enabled=bool(self._safe_property(control, "IsEnabled", False)),
            is_offscreen=bool(self._safe_property(control, "IsOffscreen", True)),
            bounding_rectangle=self._bounds(control),
        )

    def _post_digest(self, window_id: str) -> tuple[str, str | None]:
        try:
            control, hwnd = self._resolve_window(window_id)
            return self._snapshot(control, hwnd).ui_digest, None
        except Exception as exc:
            return "", f"UNKNOWN_OUTCOME: post-action UI state unavailable: {type(exc).__name__}"

    def _invoke_sync(
        self,
        window_id: str,
        expected_digest: str,
        selectors: dict[str, str | None],
    ) -> DesktopActionResult:
        with self._thread_context(), self._lock:
            window, hwnd = self._resolve_window(window_id)
            target = self._find_element(window, **selectors)
            current = self._validate_effect_state(window_id, expected_digest, window, hwnd)
            if not bool(self._safe_property(target, "IsEnabled", False)):
                raise PermissionError("UIA target is disabled")
            if bool(self._safe_property(target, "IsOffscreen", True)):
                raise PermissionError("UIA target is offscreen")
            pattern_factory = getattr(target, "GetInvokePattern", None)
            if pattern_factory is None:
                raise CapabilityUnavailable("window_provider", "UIA InvokePattern unavailable")
            pattern_factory().Invoke()
            post_digest, error = self._post_digest(window_id)
            return DesktopActionResult(
                success=True,
                window_id=window_id,
                action="invoke",
                target_element=self._element_info(target),
                pre_digest=current.ui_digest,
                post_digest=post_digest,
                error=error,
            )

    async def invoke(
        self,
        window_id: str,
        expected_digest: str,
        *,
        automation_id: str | None = None,
        control_type: str | None = None,
        name: str | None = None,
        class_name: str | None = None,
    ) -> DesktopActionResult:
        selectors = {
            "automation_id": automation_id,
            "control_type": control_type,
            "name": name,
            "class_name": class_name,
        }
        return await asyncio.to_thread(
            self._invoke_sync,
            window_id,
            expected_digest,
            selectors,
        )

    def _set_text_sync(
        self,
        window_id: str,
        expected_digest: str,
        text: str,
        selectors: dict[str, str | None],
    ) -> DesktopActionResult:
        with self._thread_context(), self._lock:
            window, hwnd = self._resolve_window(window_id)
            target = self._find_element(window, **selectors)
            current = self._validate_effect_state(window_id, expected_digest, window, hwnd)
            if not bool(self._safe_property(target, "IsEnabled", False)):
                raise PermissionError("UIA target is disabled")
            if bool(self._safe_property(target, "IsOffscreen", True)):
                raise PermissionError("UIA target is offscreen")
            pattern_factory = getattr(target, "GetValuePattern", None)
            if pattern_factory is None:
                raise CapabilityUnavailable("window_provider", "UIA ValuePattern unavailable")
            pattern_factory().SetValue(text)
            post_digest, error = self._post_digest(window_id)
            return DesktopActionResult(
                success=True,
                window_id=window_id,
                action="set_value",
                target_element=self._element_info(target),
                pre_digest=current.ui_digest,
                post_digest=post_digest,
                error=error,
            )

    async def set_text(
        self,
        window_id: str,
        expected_digest: str,
        text: str,
        *,
        automation_id: str | None = None,
        control_type: str | None = None,
        name: str | None = None,
        class_name: str | None = None,
    ) -> DesktopActionResult:
        selectors = {
            "automation_id": automation_id,
            "control_type": control_type,
            "name": name,
            "class_name": class_name,
        }
        return await asyncio.to_thread(
            self._set_text_sync,
            window_id,
            expected_digest,
            text,
            selectors,
        )

    def _coordinate_click_sync(
        self,
        window_id: str,
        expected_digest: str,
        x: int,
        y: int,
        approved: bool,
    ) -> CoordinateClickResult:
        if not approved:
            raise PermissionError("coordinate fallback requires explicit approval")
        with self._thread_context(), self._lock:
            window, hwnd = self._resolve_window(window_id)
            current = self._validate_effect_state(window_id, expected_digest, window, hwnd)
            left, top, right, bottom = current.bounds
            if x < left or x >= right or y < top or y >= bottom:
                raise ValueError("coordinate is outside the bound window")
            self._backend.coordinate_click(x, y)
            post_digest, error = self._post_digest(window_id)
            logical = (
                round((x - left) * 96 / current.dpi),
                round((y - top) * 96 / current.dpi),
            )
            return CoordinateClickResult(
                success=True,
                window_id=window_id,
                physical_coords=(x, y),
                logical_coords=logical,
                dpi=current.dpi,
                monitor_id=current.monitor_id,
                pre_digest=current.ui_digest,
                post_digest=post_digest,
                error=error,
            )

    async def coordinate_click(
        self,
        window_id: str,
        expected_digest: str,
        *,
        x: int,
        y: int,
        approved: bool = False,
    ) -> CoordinateClickResult:
        return await asyncio.to_thread(
            self._coordinate_click_sync,
            window_id,
            expected_digest,
            x,
            y,
            approved,
        )


__all__ = ["WindowsUIAWindowProvider"]
