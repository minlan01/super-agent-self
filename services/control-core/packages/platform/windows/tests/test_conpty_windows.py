"""Windows acceptance tests for the real P3.10B ConPTY lifecycle."""

from __future__ import annotations

import asyncio
import sys

import pytest

from packages.platform.shared.errors import PermissionDenied, SandboxUnavailable
from packages.platform.shared.terminal import (
    TerminalMessageType,
    TerminalOpenSpec,
    TerminalSession,
    TerminalSessionState,
    TerminalSignal,
)
from packages.platform.windows.conpty import WindowsConPTYManager

if sys.platform != "win32":
    pytest.skip("real ConPTY tests require Windows", allow_module_level=True)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_conpty_utf8_resize_and_cleanup(tmp_path) -> None:
    workspace = tmp_path / "P310B-zhongwen"
    workspace.mkdir()
    manager = WindowsConPTYManager(disconnect_grace_sec=2)
    owner = "principal:p310b-test"
    workspace_id = "workspace:p310b-test"
    session = await manager.open(
        TerminalOpenSpec(
            executable=manager.default_shell_executable(),
            args=("/d", "/q", "/k"),
            cwd=str(workspace),
            cols=80,
            rows=24,
            timeout_sec=20,
            output_size_limit_mb=2,
            memory_limit_mb=256,
            pids_limit=5,
        ),
        owner_principal_id=owner,
        workspace_id=workspace_id,
        workspace_root=str(workspace),
    )

    try:
        resized = await manager.resize(
            session.session_id,
            100,
            30,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        assert (resized.cols, resized.rows) == (100, 30)

        with pytest.raises(PermissionDenied, match="scope mismatch"):
            await manager.read(
                session.session_id,
                owner_principal_id="principal:attacker",
                workspace_id=workspace_id,
            )

        disconnected = await manager.disconnect(
            session.session_id,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        assert disconnected.state is TerminalSessionState.DISCONNECTED
        attached = await manager.attach(
            session.session_id,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        assert attached.state is TerminalSessionState.RUNNING

        await manager.write(
            session.session_id,
            "echo P310B_UTF8_中文\r\n".encode(),
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        await manager.write(
            session.session_id,
            b"pause\r\n",
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        await asyncio.sleep(0.5)
        signalled = await manager.signal(
            session.session_id,
            TerminalSignal.CTRL_C,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        assert signalled.state is TerminalSessionState.SIGNALLED
        await asyncio.sleep(0.25)
        await manager.write(
            session.session_id,
            b"echo P310B_CTRL_C_OK\r\n",
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        await manager.write(
            session.session_id,
            b"exit\r\n",
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )

        sequence = 0
        output = bytearray()
        saw_resize = False
        final_state = TerminalSessionState.RUNNING
        for _attempt in range(40):
            result = await manager.read(
                session.session_id,
                owner_principal_id=owner,
                workspace_id=workspace_id,
                after_sequence=sequence,
                timeout_sec=0.5,
            )
            sequence = result.next_sequence
            final_state = result.session.state
            for message in result.messages:
                if message.message_type is TerminalMessageType.OUTPUT:
                    output.extend(message.payload)
                if message.message_type is TerminalMessageType.RESIZE:
                    saw_resize = True
            if final_state in {
                TerminalSessionState.EXITED,
                TerminalSessionState.CLOSED,
                TerminalSessionState.ERROR,
                TerminalSessionState.TIMEOUT,
                TerminalSessionState.OUTPUT_LIMIT,
            }:
                break
            await asyncio.sleep(0.05)

        assert final_state is TerminalSessionState.EXITED
        assert saw_resize is True
        decoded = output.decode("utf-8", errors="replace")
        assert "P310B_UTF8_中文" in decoded
        assert "P310B_CTRL_C_OK" in decoded
        assert "0x2350" not in decoded
    finally:
        await manager.close(
            session.session_id,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_conpty_timeout_kills_the_job(tmp_path) -> None:
    workspace = tmp_path / "timeout-workspace"
    workspace.mkdir()
    manager = WindowsConPTYManager(disconnect_grace_sec=2)
    owner = "principal:p310b-timeout"
    workspace_id = "workspace:p310b-timeout"
    session = await manager.open(
        TerminalOpenSpec(
            executable=manager.default_shell_executable(),
            args=("/d", "/q", "/k"),
            cwd=str(workspace),
            timeout_sec=1,
            output_size_limit_mb=1,
            memory_limit_mb=256,
            pids_limit=5,
        ),
        owner_principal_id=owner,
        workspace_id=workspace_id,
        workspace_root=str(workspace),
    )
    try:
        final_state = TerminalSessionState.RUNNING
        sequence = 0
        for _attempt in range(20):
            result = await manager.read(
                session.session_id,
                owner_principal_id=owner,
                workspace_id=workspace_id,
                after_sequence=sequence,
                timeout_sec=0.25,
            )
            sequence = result.next_sequence
            final_state = result.session.state
            if final_state is TerminalSessionState.TIMEOUT:
                break
        assert final_state is TerminalSessionState.TIMEOUT
    finally:
        await manager.close(
            session.session_id,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_conpty_output_limit_terminates_session(tmp_path) -> None:
    workspace = tmp_path / "output-limit-workspace"
    workspace.mkdir()
    (workspace / "large-output.txt").write_bytes(b"X" * (2 * 1024 * 1024))
    manager = WindowsConPTYManager(disconnect_grace_sec=2)
    owner = "principal:p310b-output"
    workspace_id = "workspace:p310b-output"
    session = await manager.open(
        TerminalOpenSpec(
            executable=manager.default_shell_executable(),
            args=("/d", "/q", "/k"),
            cwd=str(workspace),
            timeout_sec=20,
            output_size_limit_mb=1,
            memory_limit_mb=256,
            pids_limit=5,
        ),
        owner_principal_id=owner,
        workspace_id=workspace_id,
        workspace_root=str(workspace),
    )
    try:
        await manager.write(
            session.session_id,
            b"type large-output.txt\r\n",
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        final_state = TerminalSessionState.RUNNING
        sequence = 0
        for _attempt in range(100):
            result = await manager.read(
                session.session_id,
                owner_principal_id=owner,
                workspace_id=workspace_id,
                after_sequence=sequence,
                max_bytes=1024 * 1024,
                timeout_sec=0.25,
            )
            sequence = result.next_sequence
            final_state = result.session.state
            if final_state is TerminalSessionState.OUTPUT_LIMIT:
                assert result.session.output_truncated is True
                break
            await asyncio.sleep(0.05)
        assert final_state is TerminalSessionState.OUTPUT_LIMIT
    finally:
        await manager.close(
            session.session_id,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_conpty_heartbeat_and_eof(tmp_path) -> None:
    workspace = tmp_path / "heartbeat-eof-workspace"
    workspace.mkdir()
    manager = WindowsConPTYManager(disconnect_grace_sec=2)
    owner = "principal:p310b-heartbeat"
    workspace_id = "workspace:p310b-heartbeat"
    session = await manager.open(
        TerminalOpenSpec(
            executable=manager.default_shell_executable(),
            args=("/d", "/q", "/k"),
            cwd=str(workspace),
            timeout_sec=20,
            output_size_limit_mb=1,
            memory_limit_mb=256,
            pids_limit=5,
        ),
        owner_principal_id=owner,
        workspace_id=workspace_id,
        workspace_root=str(workspace),
    )
    try:
        heartbeat = await manager.heartbeat(
            session.session_id,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        assert heartbeat.state is TerminalSessionState.RUNNING
        signalled = await manager.signal(
            session.session_id,
            TerminalSignal.EOF,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        assert signalled.state is TerminalSessionState.SIGNALLED

        sequence = 0
        message_types: set[TerminalMessageType] = set()
        signal_payloads: set[bytes] = set()
        final_state = TerminalSessionState.SIGNALLED
        for _attempt in range(40):
            result = await manager.read(
                session.session_id,
                owner_principal_id=owner,
                workspace_id=workspace_id,
                after_sequence=sequence,
                timeout_sec=0.5,
            )
            sequence = result.next_sequence
            final_state = result.session.state
            for message in result.messages:
                message_types.add(message.message_type)
                if message.message_type is TerminalMessageType.SIGNAL:
                    signal_payloads.add(message.payload)
            if final_state is TerminalSessionState.EXITED:
                break

        assert TerminalMessageType.HEARTBEAT in message_types
        assert TerminalMessageType.SIGNAL in message_types
        assert TerminalSignal.EOF.value.encode() in signal_payloads
        assert final_state is TerminalSessionState.EXITED
    finally:
        await manager.close(
            session.session_id,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_conpty_disconnect_grace_reclaims_session(tmp_path) -> None:
    workspace = tmp_path / "disconnect-grace-workspace"
    workspace.mkdir()
    manager = WindowsConPTYManager(disconnect_grace_sec=0.25)
    owner = "principal:p310b-disconnect"
    workspace_id = "workspace:p310b-disconnect"
    session = await manager.open(
        TerminalOpenSpec(
            executable=manager.default_shell_executable(),
            args=("/d", "/q", "/k"),
            cwd=str(workspace),
            timeout_sec=20,
            output_size_limit_mb=1,
            memory_limit_mb=256,
            pids_limit=5,
        ),
        owner_principal_id=owner,
        workspace_id=workspace_id,
        workspace_root=str(workspace),
    )
    try:
        disconnected = await manager.disconnect(
            session.session_id,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )
        assert disconnected.state is TerminalSessionState.DISCONNECTED

        final_state = TerminalSessionState.DISCONNECTED
        saw_expiry = False
        sequence = 0
        for _attempt in range(40):
            result = await manager.read(
                session.session_id,
                owner_principal_id=owner,
                workspace_id=workspace_id,
                after_sequence=sequence,
                timeout_sec=0.25,
            )
            sequence = result.next_sequence
            final_state = result.session.state
            saw_expiry = saw_expiry or any(
                message.message_type is TerminalMessageType.ERROR
                and b"disconnect grace period expired" in message.payload
                for message in result.messages
            )
            if final_state is TerminalSessionState.CLOSED:
                break

        assert saw_expiry is True
        assert final_state is TerminalSessionState.CLOSED
    finally:
        await manager.close(
            session.session_id,
            owner_principal_id=owner,
            workspace_id=workspace_id,
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_conpty_active_session_limit(tmp_path) -> None:
    first_workspace = tmp_path / "limit-workspace-1"
    second_workspace = tmp_path / "limit-workspace-2"
    first_workspace.mkdir()
    second_workspace.mkdir()
    manager = WindowsConPTYManager(
        disconnect_grace_sec=2,
        max_active_sessions=1,
        max_retained_sessions=1,
    )
    owner = "principal:p310b-limit"
    first_session = await manager.open(
        TerminalOpenSpec(
            executable=manager.default_shell_executable(),
            args=("/d", "/q", "/k"),
            cwd=str(first_workspace),
            timeout_sec=20,
            output_size_limit_mb=1,
            memory_limit_mb=256,
            pids_limit=5,
        ),
        owner_principal_id=owner,
        workspace_id="workspace:p310b-limit-1",
        workspace_root=str(first_workspace),
    )
    try:
        with pytest.raises(SandboxUnavailable, match="active-session limit"):
            await manager.open(
                TerminalOpenSpec(
                    executable=manager.default_shell_executable(),
                    args=("/d", "/q", "/k"),
                    cwd=str(second_workspace),
                    timeout_sec=20,
                    output_size_limit_mb=1,
                    memory_limit_mb=256,
                    pids_limit=5,
                ),
                owner_principal_id=owner,
                workspace_id="workspace:p310b-limit-2",
                workspace_root=str(second_workspace),
            )
    finally:
        await manager.close(
            first_session.session_id,
            owner_principal_id=owner,
            workspace_id="workspace:p310b-limit-1",
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_conpty_active_session_limit_is_atomic(tmp_path) -> None:
    workspaces = [tmp_path / f"atomic-limit-workspace-{index}" for index in range(2)]
    for workspace in workspaces:
        workspace.mkdir()
    manager = WindowsConPTYManager(
        disconnect_grace_sec=2,
        max_active_sessions=1,
        max_retained_sessions=1,
    )
    owner = "principal:p310b-atomic-limit"

    async def open_session(index: int) -> TerminalSession | Exception:
        try:
            return await manager.open(
                TerminalOpenSpec(
                    executable=manager.default_shell_executable(),
                    args=("/d", "/q", "/k"),
                    cwd=str(workspaces[index]),
                    timeout_sec=20,
                    output_size_limit_mb=1,
                    memory_limit_mb=256,
                    pids_limit=5,
                ),
                owner_principal_id=owner,
                workspace_id=f"workspace:p310b-atomic-limit-{index}",
                workspace_root=str(workspaces[index]),
            )
        except Exception as exc:  # Return both outcomes for one atomic assertion.
            return exc

    results = await asyncio.gather(open_session(0), open_session(1))
    sessions = [result for result in results if isinstance(result, TerminalSession)]
    failures = [result for result in results if isinstance(result, Exception)]
    try:
        assert len(sessions) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], SandboxUnavailable)
        assert "active-session limit" in str(failures[0])
    finally:
        for session in sessions:
            await manager.close(
                session.session_id,
                owner_principal_id=owner,
                workspace_id=session.workspace_id,
            )
