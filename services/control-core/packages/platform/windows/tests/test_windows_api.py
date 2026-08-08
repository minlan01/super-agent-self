"""Windows API acceptance tests for the P1 platform implementations.

These tests are intentionally skipped on non-Windows hosts.  They exercise the
real Credential Manager, Named Pipe, WTS/user32, and Job Object APIs rather than
mocking the security boundary.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import sys
import time
import uuid
from ctypes import wintypes
from typing import Any

import pytest

if sys.platform != "win32":
    pytest.skip("Windows API acceptance tests require Windows", allow_module_level=True)

import win32con
import win32file
import win32pipe
import win32security

from packages.platform.shared.contracts import IpcEndpoint, SandboxProfile, SecretRef
from packages.platform.shared.errors import IpcAuthError, SandboxUnavailable, SecretAccessError
from packages.platform.windows.local_ipc import (
    MAX_MESSAGE_SIZE,
    WindowsNamedPipeIpc,
    _decode_frame,
    _encode_frame,
)
from packages.platform.windows.process_sandbox import (
    _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION,
    _JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE,
    JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
    JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION,
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
    JOB_OBJECT_LIMIT_JOB_MEMORY,
    WindowsProcessSandbox,
)
from packages.platform.windows.secret_store import WindowsCredentialStore
from packages.platform.windows.session_monitor import WindowsSessionMonitor
from packages.protocol.schemas.enums import SCHEMA_VERSION


def _close_pipe(handle: Any) -> None:
    try:
        win32file.CloseHandle(handle)
    except Exception:
        pass


def _read_pipe(handle: Any) -> dict[str, Any]:
    _status, data = win32file.ReadFile(handle, MAX_MESSAGE_SIZE + 1024)
    return _decode_frame(data)


def _write_pipe(handle: Any, value: dict[str, Any]) -> None:
    win32file.WriteFile(handle, _encode_frame(value))


def _round_trip(handle: Any, value: dict[str, Any]) -> dict[str, Any]:
    _write_pipe(handle, value)
    return _read_pipe(handle)


async def _open_pipe(name: str) -> Any:
    """Open a Named Pipe without blocking the event loop while retrying."""

    deadline = time.monotonic() + 5.0
    while True:
        try:
            handle = await asyncio.to_thread(
                win32file.CreateFile,
                name,
                win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                0,
                None,
                win32con.OPEN_EXISTING,
                0,
                None,
            )
            win32pipe.SetNamedPipeHandleState(
                handle, win32pipe.PIPE_READMODE_MESSAGE, None, None
            )
            return handle
        except Exception:
            if time.monotonic() >= deadline:
                raise
            await asyncio.sleep(0.05)


async def _stop_server(ipc: WindowsNamedPipeIpc, task: asyncio.Task[Any]) -> None:
    await ipc.close()
    if not task.done():
        try:
            await asyncio.wait_for(task, 3.0)
        except TimeoutError:
            task.cancel()
        except asyncio.CancelledError:
            pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_credential_manager_binary_round_trip_and_rotation() -> None:
    store = WindowsCredentialStore(persist=1)
    ref = SecretRef(
        key_id=f"p1-real-{uuid.uuid4().hex}",
        label="P1 Windows API test",
    )
    payload = bytes(range(256))
    try:
        await store.store(ref, payload)
        assert await store.load(ref) == payload
        listed = await store.list_refs()
        assert any(item.key_id == ref.key_id for item in listed)
        await store.rotate(ref, b"rotated-p1-value")
        assert await store.load(ref) == b"rotated-p1-value"
    finally:
        assert await store.delete(ref) is True
        assert await store.delete(ref) is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_credential_manager_api_initialization_fails_closed(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    store = WindowsCredentialStore()

    def fail_api() -> Any:
        raise OSError("simulated advapi32 load failure")

    monkeypatch.setattr(WindowsCredentialStore, "_api", staticmethod(fail_api))
    ref = SecretRef(key_id=f"p1-init-{uuid.uuid4().hex}", label="P1 init")
    with pytest.raises(SecretAccessError, match="initialization"):
        await store.store(ref, b"value")
    with pytest.raises(SecretAccessError, match="initialization"):
        await store.list_refs()


@pytest.mark.integration
def test_named_pipe_security_descriptor_has_only_current_sid() -> None:
    pipe_name = rf"\\.\pipe\p1-acl-{uuid.uuid4().hex}"
    ipc = WindowsNamedPipeIpc(pipe_name)
    handle = win32pipe.CreateNamedPipe(
        pipe_name,
        win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
        1,
        64 * 1024,
        64 * 1024,
        1000,
        ipc._build_security_attributes_raw(),
    )
    try:
        security = win32security.GetNamedSecurityInfo(
            pipe_name,
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        dacl = security.GetSecurityDescriptorDacl()
        assert dacl is not None
        assert dacl.GetAceCount() == 1
        current_sid = WindowsNamedPipeIpc._current_user_sid()
        ace_sid = win32security.ConvertSidToStringSid(dacl.GetAce(0)[2])
        assert ace_sid.casefold() == current_sid.casefold()
    finally:
        _close_pipe(handle)


@pytest.mark.integration
def test_named_pipe_dacl_rejects_non_current_expected_sid() -> None:
    current_sid = WindowsNamedPipeIpc._current_user_sid()
    other_sid = "S-1-5-18" if current_sid.casefold() != "s-1-5-18" else "S-1-5-19"
    ipc = WindowsNamedPipeIpc(
        rf"\\.\pipe\p1-acl-reject-{uuid.uuid4().hex}",
        expected_sid=other_sid,
    )
    with pytest.raises(IpcAuthError, match="current process SID"):
        ipc._build_security_attributes_raw()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_named_pipe_handshake_replay_size_and_rate_limit() -> None:
    pipe_name = rf"\\.\pipe\p1-test-{uuid.uuid4().hex}"
    ipc = WindowsNamedPipeIpc(pipe_name, rate_limit_per_sec=3)
    endpoint = IpcEndpoint(transport="named_pipe", address=pipe_name)
    server = asyncio.create_task(
        ipc.serve(endpoint, lambda request: {"echo": request.get("payload")})
    )
    handle = None
    try:
        handle = await _open_pipe(pipe_name)
        handshake = _round_trip(
            handle,
            {"protocol_version": SCHEMA_VERSION, "nonce": ipc.nonce},
        )
        assert handshake["ok"] is True
        assert _round_trip(
            handle,
            {"nonce": ipc.nonce, "seq": 1, "payload": "ok"},
        )["echo"] == "ok"
        assert _round_trip(
            handle,
            {"nonce": ipc.nonce, "seq": 1, "payload": "replay"},
        )["ok"] is False
        _close_pipe(handle)
        handle = None

        await asyncio.sleep(0.1)
        handle = await _open_pipe(pipe_name)
        assert _round_trip(
            handle,
            {"protocol_version": SCHEMA_VERSION, "nonce": "wrong"},
        )["ok"] is False
        _close_pipe(handle)
        handle = None

        await asyncio.sleep(0.1)
        handle = await _open_pipe(pipe_name)
        assert _round_trip(
            handle,
            {"protocol_version": SCHEMA_VERSION, "nonce": ipc.nonce},
        )["ok"] is True
        oversized = json.dumps(
            {"nonce": ipc.nonce, "seq": 1, "data": "x" * MAX_MESSAGE_SIZE},
            separators=(",", ":"),
        ).encode("utf-8")
        assert len(oversized) > MAX_MESSAGE_SIZE
        win32file.WriteFile(handle, oversized)
        assert _read_pipe(handle)["ok"] is False
        _close_pipe(handle)
        handle = None

        await asyncio.sleep(0.1)
        handle = await _open_pipe(pipe_name)
        _round_trip(
            handle,
            {"protocol_version": SCHEMA_VERSION, "nonce": ipc.nonce},
        )
        replies = [
            _round_trip(handle, {"nonce": ipc.nonce, "seq": seq, "payload": seq})
            for seq in range(1, 5)
        ]
        assert [reply["ok"] for reply in replies[:3]] == [True, True, True]
        assert replies[3]["ok"] is False
    finally:
        if handle is not None:
            _close_pipe(handle)
        await _stop_server(ipc, server)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_named_pipe_close_cancels_active_read() -> None:
    pipe_name = rf"\\.\pipe\p1-close-{uuid.uuid4().hex}"
    ipc = WindowsNamedPipeIpc(pipe_name)
    server = asyncio.create_task(
        ipc.serve(IpcEndpoint("named_pipe", pipe_name), lambda request: {})
    )
    handle = await _open_pipe(pipe_name)
    try:
        assert _round_trip(
            handle,
            {"protocol_version": SCHEMA_VERSION, "nonce": ipc.nonce},
        )["ok"] is True
        await asyncio.wait_for(ipc.close(), 3.0)
        await asyncio.wait_for(server, 3.0)
        assert not ipc._connection_handles
    finally:
        _close_pipe(handle)
        if not server.done():
            await _stop_server(ipc, server)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_named_pipe_async_handler_runs_on_server_event_loop() -> None:
    pipe_name = rf"\\.\pipe\p1-async-{uuid.uuid4().hex}"
    ipc = WindowsNamedPipeIpc(pipe_name)
    event_loop = asyncio.get_running_loop()

    async def handler(request: dict[str, Any]) -> dict[str, Any]:
        assert asyncio.get_running_loop() is event_loop
        await asyncio.sleep(0)
        return {"echo": request.get("payload")}

    server = asyncio.create_task(
        ipc.serve(IpcEndpoint("named_pipe", pipe_name), handler)
    )
    handle = await _open_pipe(pipe_name)
    try:
        handshake = await asyncio.to_thread(
            _round_trip,
            handle,
            {"protocol_version": SCHEMA_VERSION, "nonce": ipc.nonce},
        )
        assert handshake["ok"] is True
        response = await asyncio.to_thread(
            _round_trip,
            handle,
            {"nonce": ipc.nonce, "seq": 1, "payload": "async-ok"},
        )
        assert response["echo"] == "async-ok"
    finally:
        _close_pipe(handle)
        await _stop_server(ipc, server)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_state_and_callback_are_safe() -> None:
    monitor = WindowsSessionMonitor(poll_interval_sec=0.1)
    callbacks: list[Any] = []
    try:
        state = await monitor.current_state()
        assert isinstance(state.is_locked, bool)
        assert isinstance(state.is_user_active, bool)
        assert state.os_session_id is not None
        assert state.os_session_id != "0"
        assert isinstance(monitor._is_session_locked(), bool)
        await monitor.watch(callbacks.append)
        await asyncio.sleep(0.25)
        assert callbacks
    finally:
        monitor.stop()


def _pid_is_running(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _query_job_limits(sandbox: WindowsProcessSandbox, handle: Any) -> Any:
    """Read the native Job Object limits so tests verify applied policy."""

    kernel32 = sandbox._kernel32()
    query = kernel32.QueryInformationJobObject
    query.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query.restype = wintypes.BOOL
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    returned = wintypes.DWORD()
    if not query(
        wintypes.HANDLE(handle.job_handle),
        JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
        ctypes.byref(returned),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return info


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_object_timeout_tree_and_output_limits() -> None:
    sandbox = WindowsProcessSandbox()
    profile = SandboxProfile(
        memory_limit_mb=256,
        pids_limit=8,
        exec_timeout_sec=1,
        output_size_limit_mb=1,
    )
    handle = await sandbox.create(profile)
    try:
        code = (
            "import subprocess,sys,time; "
            "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "print(c.pid, flush=True); time.sleep(60)"
        )
        started = time.monotonic()
        rc, output, _error = await sandbox.run(
            handle,
            sys.executable,
            ["-c", code],
            cwd=os.getcwd(),
            env={},
            timeout_sec=1,
        )
        assert rc != 0
        assert time.monotonic() - started < 5.0
        assert b"[TIMEOUT KILLED]" in output
        child_pid = int(output.splitlines()[0].split()[0])
        await asyncio.sleep(0.5)
        assert not _pid_is_running(child_pid)

        rc, output, _error = await sandbox.run(
            handle,
            sys.executable,
            ["-c", "import sys; print(repr(sys.argv[1]))", "; literal"],
            cwd=os.getcwd(),
            env={},
            timeout_sec=3,
        )
        assert rc == 0
        assert b"'; literal'" in output

        rc, output, _error = await sandbox.run(
            handle,
            sys.executable,
            ["-c", "print('x' * (2 * 1024 * 1024))"],
            cwd=os.getcwd(),
            env={},
            timeout_sec=3,
        )
        assert rc == 0
        assert b"[TRUNCATED]" in output
    finally:
        await sandbox.kill_tree(handle)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_object_applies_memory_and_process_limits() -> None:
    """Verify native limits are configured and affect child creation."""

    sandbox = WindowsProcessSandbox()
    profile = SandboxProfile(
        memory_limit_mb=64,
        pids_limit=2,
        cpu_limit_cores=0.5,
        exec_timeout_sec=10,
        output_size_limit_mb=1,
    )
    handle = await sandbox.create(profile)
    try:
        info = _query_job_limits(sandbox, handle)
        flags = int(info.BasicLimitInformation.LimitFlags)
        assert flags & JOB_OBJECT_LIMIT_JOB_MEMORY
        assert flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        assert int(info.BasicLimitInformation.ActiveProcessLimit) == profile.pids_limit
        assert int(info.JobMemoryLimit) == profile.memory_limit_mb * 1024 * 1024

        kernel32 = sandbox._kernel32()
        query = kernel32.QueryInformationJobObject
        cpu_info = _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        returned = wintypes.DWORD()
        assert query(
            wintypes.HANDLE(handle.job_handle),
            JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION,
            ctypes.byref(cpu_info),
            ctypes.sizeof(cpu_info),
            ctypes.byref(returned),
        )
        assert int(cpu_info.ControlFlags) & JOB_OBJECT_CPU_RATE_CONTROL_ENABLE
        assert int(cpu_info.ControlFlags) & JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
        assert 0 < int(cpu_info.CpuRate) <= 10_000

        # The root process plus one child fit in the two-process Job. A second
        # concurrent child must be rejected by JOB_OBJECT_LIMIT_ACTIVE_PROCESS.
        code = (
            "import subprocess,sys; children=[]; "
            "\nfor i in range(3):\n"
            "    try:\n"
            "        children.append(subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(5)']))\n"
            "        print(f'spawned-{i}', flush=True)\n"
            "    except OSError:\n"
            "        print(f'failed-{i}', flush=True)\n"
            "[child.terminate() for child in children]"
        )
        rc, output, _error = await sandbox.run(
            handle,
            sys.executable,
            ["-c", code],
            cwd=os.getcwd(),
            env={},
            timeout_sec=5,
        )
        assert rc == 0
        assert b"failed-" in output

        # Touch committed pages beyond the Job memory budget. The process must
        # be terminated before it can report successful allocation.
        rc, output, _error = await sandbox.run(
            handle,
            sys.executable,
            [
                "-c",
                "data=bytearray(128 * 1024 * 1024); "
                "[data.__setitem__(i, 1) for i in range(0, len(data), 4096)]; "
                "print('allocated', flush=True)",
            ],
            cwd=os.getcwd(),
            env={},
            timeout_sec=5,
        )
        assert rc != 0
        assert b"allocated" not in output
    finally:
        await sandbox.kill_tree(handle)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_object_cancellation_kills_running_child() -> None:
    sandbox = WindowsProcessSandbox()
    handle = await sandbox.create(
        SandboxProfile(exec_timeout_sec=30, output_size_limit_mb=1)
    )
    task = asyncio.create_task(
        sandbox.run(
            handle,
            sys.executable,
            ["-c", "import time; print('started', flush=True); time.sleep(60)"],
            cwd=os.getcwd(),
            env={},
            timeout_sec=30,
        )
    )
    try:
        for _ in range(50):
            if handle.pid:
                break
            await asyncio.sleep(0.02)
        pid = handle.pid
        assert pid is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.25)
        assert not _pid_is_running(pid)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        await sandbox.kill_tree(handle)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_object_rejects_concurrent_run_on_same_handle() -> None:
    sandbox = WindowsProcessSandbox()
    handle = await sandbox.create(
        SandboxProfile(exec_timeout_sec=30, output_size_limit_mb=1)
    )
    first = asyncio.create_task(
        sandbox.run(
            handle,
            sys.executable,
            ["-c", "import time; time.sleep(60)"],
            cwd=os.getcwd(),
            env={},
            timeout_sec=30,
        )
    )
    try:
        for _ in range(50):
            if handle.pid:
                break
            await asyncio.sleep(0.02)
        with pytest.raises(SandboxUnavailable, match="already executing"):
            await sandbox.run(
                handle,
                sys.executable,
                ["-c", "print('second')"],
                cwd=os.getcwd(),
                env={},
                timeout_sec=5,
            )
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await sandbox.kill_tree(handle)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_job_object_rejects_unenforceable_egress_allowlist() -> None:
    sandbox = WindowsProcessSandbox()
    profile = SandboxProfile(network_egress_allowlist=["https://example.invalid"])
    with pytest.raises(SandboxUnavailable, match="network_egress_allowlist"):
        await sandbox.create(profile)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"fs_writable": [os.getcwd()]}, "fs_writable"),
        ({"privileged": True}, "privileged"),
        ({"pids_limit": -1}, "pids_limit"),
        ({"pids_limit": 1.5}, "pids_limit"),
        ({"memory_limit_mb": -1}, "memory_limit_mb"),
        ({"output_size_limit_mb": -1}, "output_size_limit_mb"),
    ],
)
async def test_job_object_rejects_unenforceable_or_invalid_profiles(
    changes: dict[str, object], expected: str
) -> None:
    sandbox = WindowsProcessSandbox()
    profile_values: dict[str, object] = dict(changes)
    profile = SandboxProfile(**profile_values)  # type: ignore[arg-type]
    with pytest.raises(SandboxUnavailable, match=expected):
        await sandbox.create(profile)
