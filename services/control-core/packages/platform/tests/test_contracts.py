"""Tests for PlatformAdapter contracts (P0.2/P3.10B).

Verifies:
- All 10 sub-interfaces are abstract (cannot be instantiated directly)
- StubPlatformAdapter reports zero capabilities
- StubPlatformAdapter raises CapabilityUnavailable on every sub-interface
- CapabilityReport serializes correctly
- Error codes are stable and match ErrorCode enum
"""

from __future__ import annotations

import pytest

from packages.platform.shared.contracts import (
    AutoStart,
    LocalIpc,
    PermissionBroker,
    PlatformAdapter,
    ProcessSandbox,
    SandboxProfile,
    ScreenCapture,
    SecretRef,
    SecretStore,
    SessionMonitor,
    StubPlatformAdapter,
    Updater,
    WindowProvider,
)
from packages.platform.shared.errors import (
    CapabilityUnavailable,
    PlatformError,
    SandboxUnavailable,
    StaleUIState,
)
from packages.platform.shared.terminal import TerminalSessionProvider
from packages.protocol.schemas.enums import Capability, ErrorCode

# ---------------------------------------------------------------------------
# 10 sub-interfaces must be abstract
# ---------------------------------------------------------------------------

ABSTRACT_INTERFACES = [
    SecretStore,
    LocalIpc,
    SessionMonitor,
    ProcessSandbox,
    TerminalSessionProvider,
    WindowProvider,
    ScreenCapture,
    PermissionBroker,
    AutoStart,
    Updater,
]


@pytest.mark.parametrize("iface", ABSTRACT_INTERFACES)
def test_interface_is_abstract(iface) -> None:  # type: ignore[no-untyped-def]
    """Each sub-interface cannot be instantiated directly."""
    with pytest.raises(TypeError, match="abstract"):
        iface()  # type: ignore[call-arg]


def test_platform_adapter_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        PlatformAdapter()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# StubPlatformAdapter
# ---------------------------------------------------------------------------

class TestStubPlatformAdapter:
    def test_reports_zero_capabilities(self) -> None:
        adapter = StubPlatformAdapter()
        report = adapter.get_capabilities()
        assert report.capabilities == frozenset()
        # Every capability is listed as unsupported with a reason
        assert set(report.unsupported_reasons.keys()) == set(Capability)

    def test_platform_name_is_lowercased_system(self) -> None:
        adapter = StubPlatformAdapter()
        name = adapter.platform_name()
        assert name in ("windows", "linux", "darwin", "")

    @pytest.mark.parametrize(
        "method,cap_name",
        [
            ("secret_store", "secret_store"),
            ("local_ipc", "local_ipc"),
            ("session_monitor", "session_monitor"),
            ("process_sandbox", "process_sandbox"),
            ("terminal_sessions", "terminal_session"),
            ("window_provider", "window_provider"),
            ("screen_capture", "screen_capture"),
            ("permission_broker", "permission_broker"),
            ("auto_start", "auto_start"),
            ("updater", "updater"),
        ],
    )
    def test_every_subinterface_raises_capability_unavailable(
        self, method: str, cap_name: str
    ) -> None:
        adapter = StubPlatformAdapter()
        fn = getattr(adapter, method)
        with pytest.raises(CapabilityUnavailable, match=cap_name):
            fn()


# ---------------------------------------------------------------------------
# Error types and codes
# ---------------------------------------------------------------------------

class TestPlatformErrors:
    def test_capability_unavailable_has_stable_code(self) -> None:
        err = CapabilityUnavailable("secret_store", "stub")
        assert err.code == ErrorCode.CAPABILITY_UNAVAILABLE

    def test_sandbox_unavailable_code(self) -> None:
        err = SandboxUnavailable("no Job Object")
        assert err.code == ErrorCode.SANDBOX_UNAVAILABLE

    def test_stale_ui_state_code(self) -> None:
        err = StaleUIState("window focus lost")
        assert err.code == ErrorCode.STALE_UI_STATE

    def test_platform_error_is_base(self) -> None:
        assert issubclass(CapabilityUnavailable, PlatformError)
        assert issubclass(SandboxUnavailable, PlatformError)
        assert issubclass(StaleUIState, PlatformError)

    def test_capability_unavailable_message_includes_reason(self) -> None:
        err = CapabilityUnavailable("screen_capture", "no portal")
        assert "screen_capture" in str(err)
        assert "no portal" in str(err)


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------

class TestValueTypes:
    def test_secret_ref_defaults_to_secret(self) -> None:
        ref = SecretRef(key_id="k1", label="api_key")
        # SECRET is the most sensitive classification
        assert ref.classification.value == "secret"

    def test_sandbox_profile_defaults_are_conservative(self) -> None:
        p = SandboxProfile()
        assert p.privileged is False
        assert "ALL" in p.capabilities_drop
        assert p.cpu_limit_cores <= 1.0
        assert p.memory_limit_mb <= 512


# ---------------------------------------------------------------------------
# Capability discovery semantics
# ---------------------------------------------------------------------------

class TestCapabilityReport:
    def test_empty_capabilities_uses_frozenset(self) -> None:
        adapter = StubPlatformAdapter()
        report = adapter.get_capabilities()
        assert isinstance(report.capabilities, frozenset)
        assert len(report.capabilities) == 0

    def test_unsupported_reasons_cover_all_capabilities(self) -> None:
        """UI must be able to show why every capability is missing."""
        report = StubPlatformAdapter().get_capabilities()
        for cap in Capability:
            assert cap in report.unsupported_reasons
            assert isinstance(report.unsupported_reasons[cap], str)
            assert len(report.unsupported_reasons[cap]) > 0
