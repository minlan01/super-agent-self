"""P3.10B: Versioned ConPTY (Console Pseudo Terminal) session contract.

Defines the versioned TerminalSession contract for real ConPTY sessions.
Uses CreatePseudoConsole or equivalent. ConPTY child processes must belong
to a Job Object.

NOT YET IMPLEMENTED: capability report must show unavailable.
This file defines the contract only — implementation requires
CreatePseudoConsole Win32 API and is tracked as P3.10B.

Security invariants:
- Session owner and workspace scope cannot be client-tampered
- ConPTY child must be assigned to Job Object
- Chinese/UTF-8 input/output must work
- resize, Ctrl-C, EOF, disconnect/reconnect must be verified
- Output limits enforced
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from packages.platform.shared.errors import CapabilityUnavailable

TERMINAL_SESSION_VERSION = "1.0"


class SessionState(str, Enum):
    """Lifecycle states for a ConPTY session."""

    CREATED = "created"
    RUNNING = "running"
    RESIZED = "resized"
    SIGNALLED = "signalled"
    CLOSED = "closed"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(slots=True)
class TerminalSession:
    """Versioned ConPTY session descriptor.

    All fields except state and exit_code are immutable after creation.
    The session is bound to a specific owner (principal_id) and workspace
    scope — clients cannot modify these.
    """

    session_id: str
    owner_principal_id: str
    workspace_id: str
    executable: str
    args: tuple[str, ...]
    created_at: float = field(default_factory=time.time)
    state: SessionState = SessionState.CREATED
    exit_code: int | None = None
    resource_limits: dict[str, Any] = field(default_factory=dict)
    protocol_version: str = TERMINAL_SESSION_VERSION


@dataclass(slots=True, frozen=True)
class TerminalMessage:
    """A message in the ConPTY protocol.

    Message types: input, output, resize, signal, close, error, heartbeat.
    """

    msg_type: str  # "input" | "output" | "resize" | "signal" | "close" | "error" | "heartbeat"
    payload: bytes
    timestamp: float = field(default_factory=time.time)
    sequence: int = 0


@dataclass(slots=True, frozen=True)
class ResizeRequest:
    """Terminal resize request."""

    cols: int
    rows: int

    def __post_init__(self) -> None:
        if self.cols < 1 or self.cols > 500:
            raise ValueError(f"cols must be 1-500, got {self.cols}")
        if self.rows < 1 or self.rows > 200:
            raise ValueError(f"rows must be 1-200, got {self.rows}")


class ConPTYNotImplemented(CapabilityUnavailable):
    """ConPTY capability is not yet implemented.

    This error is raised by the platform adapter when ConPTY is requested
    but CreatePseudoConsole is not available or not yet wired.
    """

    def __init__(self, reason: str = "ConPTY not implemented") -> None:
        super().__init__("conpty_session", reason)


def is_conpty_available() -> bool:
    """Check if ConPTY is available on this platform.

    ConPTY requires Windows 10 1809+ (build 17763+).
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # CreatePseudoConsole was added in Windows 10 1809
        return hasattr(kernel32, "CreatePseudoConsole")
    except Exception:
        return False


__all__ = [
    "TERMINAL_SESSION_VERSION",
    "SessionState",
    "TerminalSession",
    "TerminalMessage",
    "ResizeRequest",
    "ConPTYNotImplemented",
    "is_conpty_available",
]
