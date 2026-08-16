"""PlatformAdapter contracts — 9 abstract interfaces (spec §4.4).

Each interface is a runtime-checkable Protocol (or ABC) that platform-specific
implementations (platform/windows, platform/linux, platform/macos) must satisfy.

Design rules (spec §2.3 + §4.5):
1. Business state machine lives ONLY in services/control-core; platform/* MUST
   NOT hold authoritative task state.
2. `if platform == windows` is allowed ONLY inside platform/*. CI import-linter
   (P0.4) enforces this boundary.
3. Unsupported capabilities raise CapabilityUnavailable — never silent fallback.
4. Every method that performs a side effect returns a typed result; no opaque
   dicts.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import IO

from packages.platform.shared.errors import (
    CapabilityUnavailable,
)
from packages.platform.shared.terminal import TerminalSessionProvider
from packages.protocol.schemas.enums import Capability, Classification
from packages.protocol.schemas.v1 import CapabilityReport

# ---------------------------------------------------------------------------
# Shared value types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecretRef:
    """Opaque reference to a secret in the platform store. Plaintext never
    crosses the platform boundary into business logic."""
    key_id: str
    label: str
    classification: Classification = Classification.SECRET


@dataclass(frozen=True)
class WindowInfo:
    window_id: str
    title: str
    pid: int
    ui_digest: str
    """Stable hash of the window's current UI tree; changes invalidate Grants."""


@dataclass(frozen=True)
class Screenshot:
    data: bytes
    mime_type: str
    width: int
    height: int
    taken_at: datetime
    classification: Classification = Classification.CONFIDENTIAL


@dataclass(frozen=True)
class ScreenshotArtifact:
    """Workspace-relative metadata for persisted screenshot bytes."""

    artifact_id: str
    relative_path: str
    mime_type: str
    width: int
    height: int
    sha256: str
    classification: Classification
    size_bytes: int
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SessionState:
    """Current interactive session state (spec §4.2)."""
    is_locked: bool
    is_user_active: bool
    user_sid: str | None = None
    os_session_id: str | None = None


@dataclass(frozen=True)
class SandboxProfile:
    """Resource/isolation profile for a Sandbox Runner (spec §4.2 + v3 §4A)."""
    fs_roots: list[str] = field(default_factory=list)
    fs_writable: list[str] = field(default_factory=list)
    network_egress_allowlist: list[str] = field(default_factory=list)
    cpu_limit_cores: float = 0.5
    memory_limit_mb: int = 256
    pids_limit: int = 10
    exec_timeout_sec: int = 30
    output_size_limit_mb: int = 10
    syscall_whitelist: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    uid_gid: tuple[int, int] = (1000, 1000)
    capabilities_drop: list[str] = field(default_factory=lambda: ["ALL"])
    privileged: bool = False


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    sha256: str
    signature: str
    download_url: str
    min_previous_version: str | None = None
    """Lowest version this update can be applied to (anti-downgrade)."""


@dataclass(frozen=True)
class IpcEndpoint:
    """Address of a local IPC endpoint (Named Pipe / UDS / XPC)."""
    transport: str   # "named_pipe" | "uds" | "xpc"
    address: str     # r"\\.\pipe\zcode-sidecar" or "/run/zcode/sidecar.sock"
    peer_sid: str | None = None  # Windows SID or Unix uid


# ---------------------------------------------------------------------------
# 1. SecretStore
# ---------------------------------------------------------------------------

class SecretStore(ABC):
    """OS-native secret storage. Spec §4.4 + §11.

    Windows: Credential Manager / DPAPI
    Linux:   Secret Service (libsecret/gnome-keyring)
    macOS:   Keychain
    """

    @abstractmethod
    async def store(self, ref: SecretRef, plaintext: bytes) -> None:
        """Store a secret. Fail closed on any error (never persist plaintext)."""

    @abstractmethod
    async def load(self, ref: SecretRef) -> bytes:
        """Retrieve plaintext. Caller is responsible for not logging it."""

    @abstractmethod
    async def delete(self, ref: SecretRef) -> bool:
        """Delete a secret. Returns True if it existed."""

    @abstractmethod
    async def list_refs(self) -> list[SecretRef]:
        """List all stored secret refs (without plaintext)."""

    @abstractmethod
    async def rotate(self, ref: SecretRef, new_plaintext: bytes) -> None:
        """Atomic rotate: delete old + store new. Used for key rotation."""


# ---------------------------------------------------------------------------
# 2. LocalIpc
# ---------------------------------------------------------------------------

class LocalIpc(ABC):
    """Authenticated local IPC between Desktop Shell and Control Core.

    Spec §4.4 + §4.2:
    - Windows: Named Pipe + SID ACL
    - Linux:   UDS + mode/peer creds
    - macOS:   UDS/XPC + peer identity
    Every connection verifies peer identity, nonce, and protocol version.
    """

    @abstractmethod
    async def serve(self, endpoint: IpcEndpoint, handler) -> None:
        """Listen and dispatch incoming messages to `handler`."""

    @abstractmethod
    async def connect(self, endpoint: IpcEndpoint) -> object:
        """Open an authenticated client connection. Verifies peer SID/uid."""

    @abstractmethod
    def verify_peer(self, conn: object, expected_sid: str) -> bool:
        """Verify the peer's identity. Reject on mismatch."""


# ---------------------------------------------------------------------------
# 3. SessionMonitor
# ---------------------------------------------------------------------------

class SessionMonitor(ABC):
    """Monitors interactive session state changes (spec §4.2 + §4.4).

    Lock screen, user switch, logoff, Session 0 boundaries must revoke Grants.
    """

    @abstractmethod
    async def current_state(self) -> SessionState:
        """Snapshot the current session state."""

    @abstractmethod
    async def watch(self, callback) -> None:
        """Register a callback fired on session state changes."""


# ---------------------------------------------------------------------------
# 4. ProcessSandbox
# ---------------------------------------------------------------------------

class ProcessSandbox(ABC):
    """Isolated process execution for privileged tools (spec §4.2 + v3 §4A).

    Windows: Job Object (+ AppContainer feasibility TBD ADR-008)
    Linux:   user namespace + seccomp + cgroup
    macOS:   sandbox profile / restricted subprocess
    """

    @abstractmethod
    async def create(self, profile: SandboxProfile) -> object:
        """Create an empty sandbox with the given profile. Raises
        SandboxUnavailable if the sandbox cannot be created — caller MUST NOT
        fall back to in-process execution."""

    @abstractmethod
    async def run(
        self,
        sandbox: object,
        executable: str,
        args: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        timeout_sec: int,
    ) -> tuple[int, bytes, bytes]:
        """Execute a parameterized command. Returns (exit_code, stdout, stderr).
        The entire process tree dies when the sandbox is destroyed."""

    @abstractmethod
    async def kill_tree(self, sandbox: object) -> None:
        """Terminate the entire process tree."""


# ---------------------------------------------------------------------------
# 5. WindowProvider
# ---------------------------------------------------------------------------

class WindowProvider(ABC):
    """Enumerate and inspect windows (spec §4.4).

    Windows: UI Automation / Win32
    Linux:   Wayland portal preferred, X11 fallback
    macOS:   Accessibility API
    """

    @abstractmethod
    async def list_windows(self) -> list[WindowInfo]:
        """Enumerate currently open windows."""

    @abstractmethod
    async def bind_window(self, window_id: str) -> WindowInfo:
        """Bind to a specific window and compute its UI digest for stale checks."""

    @abstractmethod
    async def verify_ui_state(self, window_id: str, expected_digest: str) -> bool:
        """Return True if the window's UI digest still matches. Used by
        desktop.input to abort clicks on stale UI (spec P2 acceptance)."""


# ---------------------------------------------------------------------------
# 6. ScreenCapture
# ---------------------------------------------------------------------------

class ScreenCapture(ABC):
    """Capture screen content (spec §4.4).

    Windows: Windows Graphics Capture
    Linux:   PipeWire portal / desktop API
    macOS:   ScreenCaptureKit
    """

    @abstractmethod
    async def grab(self, *, window_id: str | None = None) -> Screenshot:
        """Capture the full screen or a specific window. Screenshots default
        to confidential classification (spec §11)."""


# ---------------------------------------------------------------------------
# 7. PermissionBroker
# ---------------------------------------------------------------------------

class PermissionBroker(ABC):
    """Mediates OS-level permission prompts (spec §4.4).

    Windows: UAC / application prompt
    Linux:   portal request
    macOS:   TCC permission flow
    """

    @abstractmethod
    async def request(self, capability: Capability, reason: str) -> bool:
        """Prompt the user for a permission. Returns True if granted."""

    @abstractmethod
    async def status(self, capability: Capability) -> str:
        """Return 'granted' | 'denied' | 'not_determined' | 'restricted'."""


# ---------------------------------------------------------------------------
# 8. AutoStart
# ---------------------------------------------------------------------------

class AutoStart(ABC):
    """Control OS-level auto-start registration (spec §4.4).

    Default: DISABLED. Desktop Agent must not auto-start without explicit consent.
    """

    @abstractmethod
    async def enable(self) -> None: ...

    @abstractmethod
    async def disable(self) -> None: ...

    @abstractmethod
    async def is_enabled(self) -> bool: ...


# ---------------------------------------------------------------------------
# 9. Updater
# ---------------------------------------------------------------------------

class Updater(ABC):
    """Signed, anti-downgrade software updater (spec §4.4 + ADR-007).

    Windows: Authenticode + NSIS
    Linux:   repo / AppImage (ADR pending)
    macOS:   Developer ID + notarization
    """

    @abstractmethod
    async def check_for_update(self) -> UpdateManifest | None:
        """Return the latest update manifest, or None if up to date."""

    @abstractmethod
    async def download(self, manifest: UpdateManifest, dest: IO[bytes]) -> None:
        """Download and verify the signature + digest of the update package.
        Reject on any mismatch."""

    @abstractmethod
    async def apply(self, manifest: UpdateManifest) -> bool:
        """Apply the update atomically. Returns True if restart is required."""

    @abstractmethod
    async def rollback(self) -> bool:
        """Roll back to the previous (N-1) version."""


# ---------------------------------------------------------------------------
# PlatformAdapter — the composite interface
# ---------------------------------------------------------------------------

class PlatformAdapter(ABC):
    """The composite platform adapter. Implementations provide concrete
    instances of all 10 sub-interfaces plus capability discovery.

    Spec §4.5: `if platform == windows` lives ONLY inside concrete subclasses
    of PlatformAdapter. Business code takes a PlatformAdapter and queries
    capabilities — never branches on platform string.
    """

    @abstractmethod
    def platform_name(self) -> str:
        """Return 'windows' | 'linux' | 'macos'."""

    @abstractmethod
    def platform_version(self) -> str:
        """OS version string (e.g. '10.0.26200', '6.19', '15.2')."""

    @abstractmethod
    def get_capabilities(self) -> CapabilityReport:
        """Return the set of supported capabilities + reasons for unsupported.
        UI/API uses this for accurate state presentation — never fake-online."""

    # The 10 sub-interfaces. Concrete adapters return instances or raise
    # CapabilityUnavailable if the platform lacks the capability entirely.
    @abstractmethod
    def secret_store(self) -> SecretStore: ...

    @abstractmethod
    def local_ipc(self) -> LocalIpc: ...

    @abstractmethod
    def session_monitor(self) -> SessionMonitor: ...

    @abstractmethod
    def process_sandbox(self) -> ProcessSandbox: ...

    @abstractmethod
    def terminal_sessions(self) -> TerminalSessionProvider: ...

    @abstractmethod
    def window_provider(self) -> WindowProvider: ...

    @abstractmethod
    def screen_capture(self) -> ScreenCapture: ...

    @abstractmethod
    def permission_broker(self) -> PermissionBroker: ...

    @abstractmethod
    def auto_start(self) -> AutoStart: ...

    @abstractmethod
    def updater(self) -> Updater: ...


# ---------------------------------------------------------------------------
# Stub adapter (for development / Linux dev loop)
# ---------------------------------------------------------------------------

class StubPlatformAdapter(PlatformAdapter):
    """Minimal stub that reports no capabilities. Used for development on
    platforms where native adapters aren't implemented yet (P1-P6).

    Every method raises CapabilityUnavailable — explicitly, never silent.
    """

    def platform_name(self) -> str:
        import platform
        return platform.system().lower()

    def platform_version(self) -> str:
        import platform
        return platform.version()

    def get_capabilities(self) -> CapabilityReport:
        return CapabilityReport(
            capabilities=frozenset(),
            platform=self.platform_name(),
            platform_version=self.platform_version(),
            unsupported_reasons={
                cap: "stub adapter — no native implementation yet"
                for cap in Capability
            },
        )

    def _unavailable(self, name: str):
        raise CapabilityUnavailable(name, "stub adapter")

    def secret_store(self) -> SecretStore:
        self._unavailable("secret_store")

    def local_ipc(self) -> LocalIpc:
        self._unavailable("local_ipc")

    def session_monitor(self) -> SessionMonitor:
        self._unavailable("session_monitor")

    def process_sandbox(self) -> ProcessSandbox:
        self._unavailable("process_sandbox")

    def terminal_sessions(self) -> TerminalSessionProvider:
        self._unavailable("terminal_session")

    def window_provider(self) -> WindowProvider:
        self._unavailable("window_provider")

    def screen_capture(self) -> ScreenCapture:
        self._unavailable("screen_capture")

    def permission_broker(self) -> PermissionBroker:
        self._unavailable("permission_broker")

    def auto_start(self) -> AutoStart:
        self._unavailable("auto_start")

    def updater(self) -> Updater:
        self._unavailable("updater")


__all__ = [
    # value types
    "SecretRef",
    "WindowInfo",
    "Screenshot",
    "ScreenshotArtifact",
    "SessionState",
    "SandboxProfile",
    "UpdateManifest",
    "IpcEndpoint",
    # interfaces
    "SecretStore",
    "LocalIpc",
    "SessionMonitor",
    "ProcessSandbox",
    "TerminalSessionProvider",
    "WindowProvider",
    "ScreenCapture",
    "PermissionBroker",
    "AutoStart",
    "Updater",
    "PlatformAdapter",
    "StubPlatformAdapter",
]
