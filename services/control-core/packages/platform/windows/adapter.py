"""Windows platform adapter aggregating the P1 native capabilities."""

from __future__ import annotations

import platform
import sys

from packages.platform.shared.contracts import (
    AutoStart,
    LocalIpc,
    PermissionBroker,
    PlatformAdapter,
    ProcessSandbox,
    ScreenCapture,
    SecretStore,
    SessionMonitor,
    Updater,
    WindowProvider,
)
from packages.platform.shared.errors import CapabilityUnavailable
from packages.protocol.schemas.enums import Capability
from packages.protocol.schemas.v1 import CapabilityReport


class WindowsPlatformAdapter(PlatformAdapter):
    """Lazily expose P1.5-P1.8 and report unavailable future capabilities."""

    def __init__(self) -> None:
        self._ipc: LocalIpc | None = None
        self._secret: SecretStore | None = None
        self._session: SessionMonitor | None = None
        self._sandbox: ProcessSandbox | None = None

    def platform_name(self) -> str:
        return "windows"

    def platform_version(self) -> str:
        return platform.version()

    @staticmethod
    def _windows_reason() -> str | None:
        return None if sys.platform == "win32" else "Windows-only capability on non-Windows host"

    def get_capabilities(self) -> CapabilityReport:
        from .local_ipc import WindowsNamedPipeIpc
        from .process_sandbox import WindowsProcessSandbox
        from .secret_store import WindowsCredentialStore
        from .session_monitor import WindowsSessionMonitor

        capabilities: set[Capability] = set()
        reasons: dict[Capability, str] = {}
        checks = (
            (
                Capability.LOCAL_IPC,
                WindowsNamedPipeIpc.is_supported,
                "pywin32 Named Pipe bindings unavailable",
            ),
            (
                Capability.SECRET_STORE,
                WindowsCredentialStore.is_supported,
                "Windows Credential Manager unavailable",
            ),
            (
                Capability.SESSION_MONITOR,
                WindowsSessionMonitor.is_supported,
                "Windows WTS APIs unavailable",
            ),
            (
                Capability.PROCESS_SANDBOX,
                WindowsProcessSandbox.is_supported,
                "Windows Job Object APIs unavailable",
            ),
        )
        for capability, check, missing_reason in checks:
            try:
                if check():
                    capabilities.add(capability)
                else:
                    reasons[capability] = self._windows_reason() or missing_reason
            except Exception as exc:
                reasons[capability] = f"initialization check failed: {type(exc).__name__}"

        for capability, reason in (
            (Capability.WINDOW_PROVIDER, "P2 scope"),
            (Capability.SCREEN_CAPTURE, "P2 scope"),
            (Capability.PERMISSION_BROKER, "P3 scope"),
            (Capability.AUTO_START, "P4 scope"),
            (Capability.UPDATER, "P4 scope"),
        ):
            reasons[capability] = reason
        return CapabilityReport(
            capabilities=frozenset(capabilities),
            platform=self.platform_name(),
            platform_version=self.platform_version(),
            unsupported_reasons=reasons,
        )

    @staticmethod
    def _require(capability: Capability, supported: bool, reason: str) -> None:
        if not supported:
            raise CapabilityUnavailable(capability.value, reason)

    def local_ipc(self) -> LocalIpc:
        from .local_ipc import WindowsNamedPipeIpc

        self._require(
            Capability.LOCAL_IPC,
            WindowsNamedPipeIpc.is_supported(),
            "requires Windows and pywin32",
        )
        if self._ipc is None:
            self._ipc = WindowsNamedPipeIpc()
        return self._ipc

    def secret_store(self) -> SecretStore:
        from .secret_store import WindowsCredentialStore

        self._require(
            Capability.SECRET_STORE,
            WindowsCredentialStore.is_supported(),
            "requires Windows Credential Manager",
        )
        if self._secret is None:
            self._secret = WindowsCredentialStore()
        return self._secret

    def session_monitor(self) -> SessionMonitor:
        from .session_monitor import WindowsSessionMonitor

        self._require(
            Capability.SESSION_MONITOR,
            WindowsSessionMonitor.is_supported(),
            "requires Windows WTS/user32 APIs",
        )
        if self._session is None:
            self._session = WindowsSessionMonitor()
        return self._session

    def process_sandbox(self) -> ProcessSandbox:
        from .process_sandbox import WindowsProcessSandbox

        self._require(
            Capability.PROCESS_SANDBOX,
            WindowsProcessSandbox.is_supported(),
            "requires Windows Job Object APIs",
        )
        if self._sandbox is None:
            self._sandbox = WindowsProcessSandbox()
        return self._sandbox

    def window_provider(self) -> WindowProvider:
        raise CapabilityUnavailable("window_provider", "P2 scope")

    def screen_capture(self) -> ScreenCapture:
        raise CapabilityUnavailable("screen_capture", "P2 scope")

    def permission_broker(self) -> PermissionBroker:
        raise CapabilityUnavailable("permission_broker", "P3 scope")

    def auto_start(self) -> AutoStart:
        raise CapabilityUnavailable("auto_start", "P4 scope")

    def updater(self) -> Updater:
        raise CapabilityUnavailable("updater", "P4 scope")


__all__ = ["WindowsPlatformAdapter"]
