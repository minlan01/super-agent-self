"""Windows adapter errors that are narrower than the shared P0 contract."""

from __future__ import annotations

from packages.platform.shared.errors import CapabilityUnavailable, PlatformError


class UnsupportedPlatformError(CapabilityUnavailable):
    """Raised when a Windows-only operation is requested elsewhere."""

    def __init__(self, message: str) -> None:
        super().__init__("windows_platform", message)


class IpcProtocolError(PlatformError):
    """Raised when an IPC frame violates the local wire contract."""


class IpcRateLimitError(IpcProtocolError):
    """Raised when a peer exceeds the per-connection request budget."""


class SessionUnavailable(PlatformError):
    """Raised when Windows session state cannot be inspected safely."""


__all__ = [
    "IpcProtocolError",
    "IpcRateLimitError",
    "SessionUnavailable",
    "UnsupportedPlatformError",
]
