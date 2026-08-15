"""Shared typed contract for interactive terminal sessions."""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

TERMINAL_PROTOCOL_VERSION = "1.0"


class TerminalSessionState(StrEnum):
    """Observable lifecycle states for an interactive terminal."""

    CREATED = "created"
    RUNNING = "running"
    RESIZED = "resized"
    SIGNALLED = "signalled"
    DISCONNECTED = "disconnected"
    EXITED = "exited"
    CLOSED = "closed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    OUTPUT_LIMIT = "output_limit"
    ERROR = "error"


class TerminalMessageType(StrEnum):
    """Versioned terminal protocol message types."""

    INPUT = "input"
    OUTPUT = "output"
    RESIZE = "resize"
    SIGNAL = "signal"
    CLOSE = "close"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class TerminalSignal(StrEnum):
    """Signals supported by the portable terminal contract."""

    CTRL_C = "ctrl_c"
    EOF = "eof"
    TERMINATE = "terminate"


@dataclass(slots=True, frozen=True)
class TerminalOpenSpec:
    """Validated, platform-neutral request for a new terminal session."""

    executable: str
    args: tuple[str, ...]
    cwd: str
    env: tuple[tuple[str, str], ...] = ()
    cols: int = 80
    rows: int = 24
    timeout_sec: float = 300.0
    output_size_limit_mb: int = 10
    cpu_limit_cores: float = 0.5
    memory_limit_mb: int = 256
    pids_limit: int = 10
    protocol_version: str = TERMINAL_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not self.executable:
            raise ValueError("executable must be non-empty")
        if any(not isinstance(value, str) for value in self.args):
            raise TypeError("all terminal arguments must be strings")
        if any(not key or "=" in key for key, _value in self.env):
            raise ValueError("terminal environment keys must be non-empty and exclude '='")
        if isinstance(self.cols, bool) or not isinstance(self.cols, int):
            raise TypeError("cols must be an integer")
        if isinstance(self.rows, bool) or not isinstance(self.rows, int):
            raise TypeError("rows must be an integer")
        if not 1 <= self.cols <= 500:
            raise ValueError(f"cols must be 1-500, got {self.cols}")
        if not 1 <= self.rows <= 200:
            raise ValueError(f"rows must be 1-200, got {self.rows}")
        if (
            isinstance(self.timeout_sec, bool)
            or not isinstance(self.timeout_sec, (int, float))
            or self.timeout_sec <= 0
            or not math.isfinite(float(self.timeout_sec))
        ):
            raise ValueError("timeout_sec must be positive")
        if (
            isinstance(self.output_size_limit_mb, bool)
            or not isinstance(self.output_size_limit_mb, int)
            or self.output_size_limit_mb <= 0
        ):
            raise ValueError("output_size_limit_mb must be positive")
        if (
            isinstance(self.cpu_limit_cores, bool)
            or not isinstance(self.cpu_limit_cores, (int, float))
            or self.cpu_limit_cores <= 0
            or not math.isfinite(float(self.cpu_limit_cores))
        ):
            raise ValueError("cpu_limit_cores must be positive")
        if (
            isinstance(self.memory_limit_mb, bool)
            or not isinstance(self.memory_limit_mb, int)
            or self.memory_limit_mb <= 0
        ):
            raise ValueError("memory_limit_mb must be positive")
        if (
            isinstance(self.pids_limit, bool)
            or not isinstance(self.pids_limit, int)
            or self.pids_limit <= 0
        ):
            raise ValueError("pids_limit must be positive")
        if self.protocol_version != TERMINAL_PROTOCOL_VERSION:
            raise ValueError(
                f"unsupported terminal protocol version: {self.protocol_version}"
            )

    @property
    def env_dict(self) -> dict[str, str]:
        return dict(self.env)


@dataclass(slots=True, frozen=True)
class TerminalSession:
    """Immutable snapshot of a server-bound terminal session."""

    session_id: str
    owner_principal_id: str
    workspace_id: str
    executable: str
    args: tuple[str, ...]
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    state: TerminalSessionState = TerminalSessionState.CREATED
    exit_code: int | None = None
    cols: int = 80
    rows: int = 24
    output_truncated: bool = False
    resource_limits: Mapping[str, int | float | str] = field(default_factory=dict)
    protocol_version: str = TERMINAL_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not self.session_id or not self.owner_principal_id or not self.workspace_id:
            raise ValueError("terminal session identity and scope must be non-empty")
        if self.protocol_version != TERMINAL_PROTOCOL_VERSION:
            raise ValueError(
                f"unsupported terminal protocol version: {self.protocol_version}"
            )
        object.__setattr__(
            self,
            "resource_limits",
            MappingProxyType(dict(self.resource_limits)),
        )


@dataclass(slots=True, frozen=True)
class TerminalMessage:
    """A sequenced message in the terminal session protocol."""

    message_type: TerminalMessageType
    payload: bytes
    sequence: int
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.message_type, TerminalMessageType):
            raise TypeError("message_type must be a TerminalMessageType")
        if not isinstance(self.payload, bytes):
            raise TypeError("terminal message payload must be bytes")
        if self.sequence < 1:
            raise ValueError("terminal message sequence must be positive")


@dataclass(slots=True, frozen=True)
class TerminalReadResult:
    """Typed result for resumable terminal output reads."""

    session: TerminalSession
    messages: tuple[TerminalMessage, ...]
    next_sequence: int


class TerminalSessionProvider(ABC):
    """Portable lifecycle contract implemented by native terminal backends."""

    @abstractmethod
    async def open(
        self,
        spec: TerminalOpenSpec,
        *,
        owner_principal_id: str,
        workspace_id: str,
        workspace_root: str,
    ) -> TerminalSession: ...

    @abstractmethod
    async def write(
        self,
        session_id: str,
        data: bytes,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession: ...

    @abstractmethod
    async def read(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
        after_sequence: int = 0,
        max_bytes: int = 64 * 1024,
        timeout_sec: float = 1.0,
    ) -> TerminalReadResult: ...

    @abstractmethod
    async def resize(
        self,
        session_id: str,
        cols: int,
        rows: int,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession: ...

    @abstractmethod
    async def signal(
        self,
        session_id: str,
        signal: TerminalSignal,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession: ...

    @abstractmethod
    async def attach(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession: ...

    @abstractmethod
    async def disconnect(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession: ...

    @abstractmethod
    async def close(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession: ...


__all__ = [
    "TERMINAL_PROTOCOL_VERSION",
    "TerminalMessage",
    "TerminalMessageType",
    "TerminalOpenSpec",
    "TerminalReadResult",
    "TerminalSession",
    "TerminalSessionProvider",
    "TerminalSessionState",
    "TerminalSignal",
]
