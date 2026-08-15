"""Contract-shape tests that run on every host.

Windows API tests remain environment-gated; these checks ensure the native
modules can be imported and cannot silently drift from the P0.2 contracts.
"""

from __future__ import annotations

import sys

import pytest

from packages.platform.shared.contracts import (
    IpcEndpoint,
    LocalIpc,
    PlatformAdapter,
    ProcessSandbox,
    SandboxProfile,
    SecretRef,
    SecretStore,
    SessionMonitor,
    SessionState,
)
from packages.platform.shared.terminal import TerminalSessionProvider
from packages.platform.windows._errors import UnsupportedPlatformError
from packages.platform.windows.adapter import WindowsPlatformAdapter
from packages.platform.windows.conpty import WindowsConPTYManager
from packages.platform.windows.local_ipc import WindowsNamedPipeIpc
from packages.platform.windows.process_sandbox import WindowsProcessSandbox
from packages.platform.windows.secret_store import WindowsCredentialStore
from packages.platform.windows.session_monitor import WindowsSessionMonitor
from packages.protocol.schemas.enums import Capability, ErrorCode


def test_native_classes_implement_real_abstract_contracts() -> None:
    assert issubclass(WindowsNamedPipeIpc, LocalIpc)
    assert issubclass(WindowsCredentialStore, SecretStore)
    assert issubclass(WindowsSessionMonitor, SessionMonitor)
    assert issubclass(WindowsProcessSandbox, ProcessSandbox)
    assert issubclass(WindowsConPTYManager, TerminalSessionProvider)
    assert issubclass(WindowsPlatformAdapter, PlatformAdapter)


def test_real_value_types_are_used_without_extra_fields() -> None:
    ref = SecretRef(key_id="key-1", label="API key")
    assert ref.classification.value == "secret"
    state = SessionState(
        is_locked=False,
        is_user_active=True,
        user_sid="S-1-5-21",
        os_session_id="1",
    )
    assert state.os_session_id == "1"
    profile = SandboxProfile(env_vars={"P1_TEST": "yes"})
    assert profile.env_vars["P1_TEST"] == "yes"
    assert profile.privileged is False


def test_endpoint_is_named_pipe_contract() -> None:
    endpoint = IpcEndpoint(
        transport="named_pipe",
        address=r"\\.\pipe\zcode-control-core",
        peer_sid="S-1-5-21-test",
    )
    ipc = WindowsNamedPipeIpc(expected_sid=endpoint.peer_sid)
    assert endpoint.address == ipc.pipe_name
    assert ipc.expected_sid == endpoint.peer_sid


def test_non_windows_capability_report_is_explicit() -> None:
    adapter = WindowsPlatformAdapter()
    report = adapter.get_capabilities()
    assert report.platform == "windows"
    if sys.platform != "win32":
        assert report.capabilities == frozenset()
        assert set(report.unsupported_reasons) == set(Capability)
        assert all(report.unsupported_reasons.values())


def test_process_sandbox_capability_requires_task_scoped_factory() -> None:
    adapter = WindowsPlatformAdapter()

    report = adapter.get_capabilities()

    assert Capability.PROCESS_SANDBOX not in report.capabilities
    assert "task-scoped WindowsIsolationBroker" in report.unsupported_reasons[
        Capability.PROCESS_SANDBOX
    ]


def test_terminal_capability_matches_real_conpty_support() -> None:
    adapter = WindowsPlatformAdapter()
    report = adapter.get_capabilities()

    if WindowsConPTYManager.is_supported():
        assert Capability.TERMINAL_SESSION in report.capabilities
        assert Capability.TERMINAL_SESSION not in report.unsupported_reasons
        assert isinstance(adapter.terminal_sessions(), TerminalSessionProvider)
    else:
        assert Capability.TERMINAL_SESSION not in report.capabilities
        assert report.unsupported_reasons[Capability.TERMINAL_SESSION]


@pytest.mark.parametrize(
    "factory",
    [
        lambda: WindowsNamedPipeIpc(),
        lambda: WindowsCredentialStore(),
        lambda: WindowsSessionMonitor(),
        lambda: WindowsProcessSandbox(),
    ],
)
def test_windows_only_operations_fail_closed_off_windows(
    factory,
) -> None:  # type: ignore[no-untyped-def]
    if sys.platform == "win32":
        pytest.skip("host-dependent Windows API behavior")
    instance = factory()
    assert instance.is_supported() is False


def test_session_zero_hook_is_pure_and_conservative() -> None:
    monitor = WindowsSessionMonitor()
    assert monitor._is_session_zero(0) is True
    assert monitor._is_session_zero("0") is True
    assert monitor._is_session_zero("1") is False
    assert monitor._is_session_zero(None) is False


def test_windows_unsupported_error_uses_capability_code() -> None:
    error = UnsupportedPlatformError("requires Windows")
    assert error.code == ErrorCode.CAPABILITY_UNAVAILABLE


def test_session_does_not_report_service_sid_as_interactive_user(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    monitor = WindowsSessionMonitor()
    monkeypatch.setattr(monitor, "_get_console_session_id", lambda: 1)
    monkeypatch.setattr(monitor, "_get_current_process_session_id", lambda: 0)
    monkeypatch.setattr(monitor, "_is_session_locked", lambda: False)
    monkeypatch.setattr(monitor, "_query_connect_state", lambda _session: 0)
    monkeypatch.setattr(monitor, "_get_user_sid_for_session", lambda _session: None)
    monkeypatch.setattr(monitor, "_get_current_sid", lambda: "S-1-5-18")

    state = monitor._safe_state()
    assert state.is_user_active is False
    assert state.user_sid is None
