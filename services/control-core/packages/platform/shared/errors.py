"""Platform-layer error types — shared across all PlatformAdapter implementations.

Per spec §4.4 + §5.2: unsupported capabilities return CAPABILITY_UNAVAILABLE
with a stable error code; silent fallback to high-privilege paths is forbidden.
"""

from __future__ import annotations

from packages.protocol.schemas.enums import ErrorCode


class PlatformError(Exception):
    """Base class for all platform-layer errors."""

    code: ErrorCode = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, *, code: ErrorCode | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class CapabilityUnavailable(PlatformError):
    """The platform does not support this capability. Never fall back silently.

    Spec §5.2: unsupported capabilities return CAPABILITY_UNAVAILABLE, not
    silent failure or fake-online behavior.
    """

    code = ErrorCode.CAPABILITY_UNAVAILABLE

    def __init__(self, capability: str, reason: str = "") -> None:
        msg = f"capability '{capability}' unavailable"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class SandboxUnavailable(PlatformError):
    """The process sandbox cannot be created. The main process MUST NOT
    fall back to running the tool in-process (spec §9.1 invariant)."""

    code = ErrorCode.SANDBOX_UNAVAILABLE


class StaleUIState(PlatformError):
    """Window focus or UI state changed between plan and action; abort click.

    Spec §6 risk model + P2 acceptance: desktop.input returns STALE_UI_STATE,
    never blind-clicks."""

    code = ErrorCode.STALE_UI_STATE


class IpcAuthError(PlatformError):
    """Local IPC peer identity verification failed (wrong SID / nonce / signature)."""

    code = ErrorCode.HTTP_FORBIDDEN


class SecretAccessError(PlatformError):
    """Secret store read/write failed. Fail closed (never return plaintext fallback)."""


class PermissionDenied(PlatformError):
    """The OS or user denied a permission (TCC, portal, UAC)."""


__all__ = [
    "PlatformError",
    "CapabilityUnavailable",
    "SandboxUnavailable",
    "StaleUIState",
    "IpcAuthError",
    "SecretAccessError",
    "PermissionDenied",
]
