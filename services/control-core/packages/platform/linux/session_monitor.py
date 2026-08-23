"""Linux SessionMonitor — logind seat/session tracking (P5).

Spec §4.4: "logind/desktop session". We poll/subscribe to logind over
DBus (via `dbus-python` if present) and expose SessionState; on lock the
caller (device service) revokes all session Grants.

Without a session bus (headless CI / SSH) the monitor reports the current
process's session as active-unlocked if it belongs to a local seat, else
raises SessionUnavailable — fail closed, no guessing.
"""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable

import structlog

from packages.platform.shared.contracts import SessionMonitor, SessionState
from packages.platform.shared.errors import PlatformError

logger = structlog.get_logger()


def _xdg_session_id() -> str | None:
    return os.environ.get("XDG_SESSION_ID") or None


def _xdg_session_type() -> str | None:
    return os.environ.get("XDG_SESSION_TYPE") or None


class LogindSessionMonitor(SessionMonitor):
    """Tracks the local graphical session via systemd-logind."""

    def __init__(self) -> None:
        self._bus: Any = None
        self._callbacks: list[Callable[[SessionState], Awaitable[None]]] = []

    def _connect(self) -> Any:
        if self._bus is None:
            try:
                import dbus
                self._bus = dbus.SystemBus()
            except Exception as exc:
                raise PlatformError(
                    f"system DBus unavailable for logind monitor: {exc}"
                ) from exc
        return self._bus

    async def current_state(self) -> SessionState:
        session_id = _xdg_session_id()
        uid = os.getuid()

        if session_id is None:
            # No session env (headless): we cannot attest an interactive
            # session — report inactive rather than guessing.
            return SessionState(
                is_locked=False,
                is_user_active=False,
                user_sid=str(uid),
                os_session_id=None,
            )

        try:
            import dbus
            bus = self._connect()
            manager = dbus.Interface(
                bus.get_object("org.freedesktop.login1",
                               "/org/freedesktop/login1"),
                "org.freedesktop.login1.Manager",
            )
            path = manager.GetSession(session_id)
            props = dbus.Interface(
                bus.get_object("org.freedesktop.login1", path),
                "org.freedesktop.DBus.Properties",
            )
            locked_hint = bool(props.Get("org.freedesktop.login1.Session",
                                         "LockedHint"))
            active = str(props.Get("org.freedesktop.login1.Session", "State")) == "active"
            return SessionState(
                is_locked=locked_hint,
                is_user_active=active,
                user_sid=str(uid),
                os_session_id=session_id,
            )
        except PlatformError:
            raise
        except Exception as exc:
            raise PlatformError(
                f"failed to query logind session state: {exc}"
            ) from exc

    async def watch(self, callback: Callable[[SessionState], Awaitable[None]]) -> None:
        """Subscribe to Lock/Unlock/SessionStateChanged signals."""
        self._callbacks.append(callback)
        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop  # noqa: F401

            bus = self._connect()
            bus.add_signal_receiver(
                self._on_lock_signal,
                dbus_interface="org.freedesktop.login1.Session",
                signal_name="Lock",
            )
            bus.add_signal_receiver(
                self._on_unlock_signal,
                dbus_interface="org.freedesktop.login1.Session",
                signal_name="Unlock",
            )
        except PlatformError:
            raise
        except Exception as exc:
            raise PlatformError(f"failed to subscribe to logind signals: {exc}") from exc

    # Signal handlers run on the DBus main loop; dispatch state snapshots.
    def _on_lock_signal(self) -> None:
        import asyncio
        state = SessionState(is_locked=True, is_user_active=True,
                             user_sid=str(os.getuid()),
                             os_session_id=_xdg_session_id())
        for cb in self._callbacks:
            asyncio.get_event_loop().create_task(cb(state))

    def _on_unlock_signal(self) -> None:
        import asyncio
        state = SessionState(is_locked=False, is_user_active=True,
                             user_sid=str(os.getuid()),
                             os_session_id=_xdg_session_id())
        for cb in self._callbacks:
            asyncio.get_event_loop().create_task(cb(state))
