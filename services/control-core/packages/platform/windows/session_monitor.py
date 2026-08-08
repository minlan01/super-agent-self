"""Windows interactive-session monitor (P1.7).

The monitor reports the physical console session, checks the input desktop,
and treats unknown state as locked/inactive.  A bounded poller is used instead
of requiring a hidden message-only window, so the same adapter works in the
control-core worker and in an interactive desktop process.
"""

from __future__ import annotations

import asyncio
import ctypes
import inspect
import logging
import os
import sys
import threading
from collections.abc import Callable

from packages.platform.shared.contracts import SessionMonitor, SessionState

from ._errors import SessionUnavailable, UnsupportedPlatformError

logger = logging.getLogger(__name__)

WM_WTSSESSION_CHANGE = 0x0319
WTS_CONSOLE_CONNECT = 0x1
WTS_CONSOLE_DISCONNECT = 0x2
WTS_REMOTE_CONNECT = 0x3
WTS_REMOTE_DISCONNECT = 0x4
WTS_SESSION_LOGON = 0x5
WTS_SESSION_LOGOFF = 0x6
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
WTS_SESSION_REMOTE_CONTROL = 0x9

WTS_CURRENT_SERVER_HANDLE = ctypes.c_void_p(0)
WTS_INFO_CLASS_CONNECT_STATE = 8
WTS_ACTIVE = 0
WTS_CONNECTED = 1
UOI_NAME = 2
DESKTOP_READOBJECTS = 0x0001
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_HANDLE = 6
ERROR_NO_TOKEN = 1008
INVALID_SESSION_ID = 0xFFFFFFFF


class WindowsSessionMonitor(SessionMonitor):
    """Snapshot and watch the current interactive Windows session."""

    def __init__(self, *, poll_interval_sec: float = 1.0) -> None:
        if poll_interval_sec <= 0:
            raise ValueError("poll_interval_sec must be positive")
        self.poll_interval_sec = poll_interval_sec
        self._callbacks: list[Callable[[SessionState], object]] = []
        self._callbacks_lock = threading.Lock()
        self._monitor_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_state: SessionState | None = None

    @staticmethod
    def is_supported() -> bool:
        return sys.platform == "win32"

    def _require_windows(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Windows session monitoring requires Windows")

    @staticmethod
    def _get_console_session_id() -> int | None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("WTS is only available on Windows")
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            fn = kernel32.WTSGetActiveConsoleSessionId
            fn.argtypes = []
            fn.restype = ctypes.c_ulong
            value = int(fn())
            return None if value == INVALID_SESSION_ID else value
        except (AttributeError, OSError) as exc:
            raise SessionUnavailable("WTSGetActiveConsoleSessionId unavailable") from exc

    @staticmethod
    def _get_current_process_session_id() -> int | None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Windows process sessions require Windows")
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            fn = kernel32.ProcessIdToSessionId
            fn.argtypes = [ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
            fn.restype = ctypes.c_int
            session = ctypes.c_ulong()
            if not fn(ctypes.c_ulong(os.getpid()), ctypes.byref(session)):
                raise ctypes.WinError(ctypes.get_last_error())
            return int(session.value)
        except (AttributeError, OSError) as exc:
            raise SessionUnavailable("ProcessIdToSessionId unavailable") from exc

    @staticmethod
    def _query_connect_state(session_id: int) -> int | None:
        """Query WTS_CONNECTSTATE_CLASS and always release WTS memory."""

        if sys.platform != "win32":
            raise UnsupportedPlatformError("WTS is only available on Windows")
        try:
            wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
            query = wtsapi32.WTSQuerySessionInformationW
            query.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_ulong),
            ]
            query.restype = ctypes.c_int
            free = wtsapi32.WTSFreeMemory
            free.argtypes = [ctypes.c_void_p]
            free.restype = None
            buffer = ctypes.c_void_p()
            count = ctypes.c_ulong()
            if not query(
                WTS_CURRENT_SERVER_HANDLE,
                ctypes.c_ulong(session_id),
                WTS_INFO_CLASS_CONNECT_STATE,
                ctypes.byref(buffer),
                ctypes.byref(count),
            ):
                return None
            try:
                return int(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int)).contents.value)
            finally:
                free(buffer)
        except (AttributeError, OSError) as exc:
            raise SessionUnavailable("WTS session state query unavailable") from exc

    @staticmethod
    def _is_session_zero(session_id: int | str | None) -> bool:
        try:
            return int(session_id) == 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _get_user_sid_for_session(session_id: int | None) -> str | None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Windows user tokens require Windows")
        if session_id is None or session_id == 0:
            return None
        try:
            import win32security
            import win32ts

            token = win32ts.WTSQueryUserToken(session_id)
            try:
                sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
                return win32security.ConvertSidToStringSid(sid)
            finally:
                close = getattr(token, "Close", None)
                if close:
                    close()
        except Exception:
            logger.debug("Could not resolve session user SID", exc_info=True)
            return None

    @staticmethod
    def _get_current_sid() -> str | None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Windows user tokens require Windows")
        try:
            import win32api
            import win32security

            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
            )
            try:
                sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
                return win32security.ConvertSidToStringSid(sid)
            finally:
                close = getattr(token, "Close", None)
                if close:
                    close()
        except Exception:
            logger.debug("Could not resolve current process SID", exc_info=True)
            return None

    @staticmethod
    def _is_session_locked() -> bool:
        """Inspect the input desktop; inability to inspect fails closed."""

        if sys.platform != "win32":
            raise UnsupportedPlatformError("Windows desktop inspection requires Windows")
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            open_input = user32.OpenInputDesktop
            open_input.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            open_input.restype = ctypes.c_void_p
            desktop = open_input(0, 0, DESKTOP_READOBJECTS)
            if not desktop:
                error = ctypes.get_last_error()
                if error in (ERROR_ACCESS_DENIED, ERROR_INVALID_HANDLE, ERROR_NO_TOKEN):
                    return True
                raise ctypes.WinError(error)
            try:
                get_info = user32.GetUserObjectInformationW
                get_info.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_int,
                    ctypes.c_void_p,
                    ctypes.c_uint,
                    ctypes.POINTER(ctypes.c_uint),
                ]
                get_info.restype = ctypes.c_int
                buffer = ctypes.create_unicode_buffer(256)
                needed = ctypes.c_uint()
                if not get_info(
                    desktop,
                    UOI_NAME,
                    ctypes.byref(buffer),
                    ctypes.sizeof(buffer),
                    ctypes.byref(needed),
                ):
                    return True
                return buffer.value.casefold() in {"winlogon", "screensaver", "secure desktop"}
            finally:
                close_desktop = getattr(user32, "CloseDesktop", None)
                if close_desktop:
                    close_desktop(desktop)
        except UnsupportedPlatformError:
            raise
        except Exception:
            logger.exception("Could not inspect the input desktop; failing closed")
            return True

    def _safe_state(self) -> SessionState:
        """Build only the fields in the shared frozen SessionState contract."""

        try:
            console_session = self._get_console_session_id()
            process_session = self._get_current_process_session_id()
            locked = self._is_session_locked()
            connect_state = (
                self._query_connect_state(console_session)
                if console_session is not None
                else None
            )
            connected = connect_state in (WTS_ACTIVE, WTS_CONNECTED)
            active = (
                console_session is not None
                and not self._is_session_zero(console_session)
                and process_session is not None
                and not self._is_session_zero(process_session)
                and connected
                and not locked
            )
            sid = self._get_user_sid_for_session(console_session)
            # A service in Session 0 must never report its own token as the
            # interactive user's identity.  Falling back to the process SID is
            # safe only when the process is actually in the console session.
            if sid is None and process_session == console_session and not self._is_session_zero(
                process_session
            ):
                sid = self._get_current_sid()
            return SessionState(
                is_locked=locked,
                is_user_active=active,
                user_sid=sid,
                os_session_id=(
                    str(console_session) if console_session is not None else None
                ),
            )
        except UnsupportedPlatformError:
            raise
        except Exception:
            logger.exception("Session snapshot failed; denying interactive actions")
            return SessionState(
                is_locked=True,
                is_user_active=False,
                user_sid=None,
                os_session_id=None,
            )

    async def current_state(self) -> SessionState:
        self._require_windows()
        return await asyncio.to_thread(self._safe_state)

    async def watch(self, callback: Callable[[SessionState], object]) -> None:
        """Register a callback and start the bounded polling loop."""

        self._require_windows()
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._callbacks_lock:
            self._callbacks.append(callback)
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._stop.clear()
            self._monitor_thread = threading.Thread(
                target=self._poll_loop,
                name="p1-session-monitor",
                daemon=True,
            )
            self._monitor_thread.start()

    def _emit(self, state: SessionState) -> None:
        with self._callbacks_lock:
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            try:
                if self._loop is not None and self._loop.is_running():
                    if inspect.iscoroutinefunction(callback):
                        asyncio.run_coroutine_threadsafe(callback(state), self._loop)
                    else:
                        self._loop.call_soon_threadsafe(callback, state)
                else:
                    result = callback(state)
                    if asyncio.iscoroutine(result):
                        asyncio.run(result)
            except Exception:
                logger.exception("Session callback failed")

    def _poll_loop(self) -> None:
        previous = self._last_state
        while not self._stop.wait(self.poll_interval_sec):
            try:
                state = self._safe_state()
            except Exception:
                logger.exception("Session poll failed")
                continue
            self._last_state = state
            if previous is None or (
                state.is_locked != previous.is_locked
                or state.is_user_active != previous.is_user_active
                or state.os_session_id != previous.os_session_id
                or state.user_sid != previous.user_sid
            ):
                logger.info(
                    "Session state changed: locked=%s active=%s session=%s",
                    state.is_locked,
                    state.is_user_active,
                    state.os_session_id,
                )
                self._emit(state)
            previous = state

    def stop(self) -> None:
        self._stop.set()
        thread = self._monitor_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.poll_interval_sec + 0.25))
        self._monitor_thread = None


__all__ = [
    "WM_WTSSESSION_CHANGE",
    "WTS_SESSION_LOCK",
    "WTS_SESSION_UNLOCK",
    "WindowsSessionMonitor",
]
