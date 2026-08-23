"""Tests for the Linux platform adapters (P5).

Run on Linux (skipped elsewhere). DBus/Secret Service pieces degrade to
import/availability assertions where the session services are absent —
their fail-closed behavior is what we verify, not the happy path.
"""

import asyncio
import os
import sys
import tempfile

import pytest

from packages.platform.shared.contracts import IpcEndpoint, SandboxProfile
from packages.platform.shared.errors import (
    PlatformError,
    SandboxUnavailable,
    SecretAccessError,
)

linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only")


@linux_only
class TestUnixSocketIpc:
    def _endpoint(self, tmp_path):
        # AF_UNIX sun_path is capped at ~108 bytes; pytest's tmp_path can
        # exceed that, so anchor short sockets under /tmp.
        import uuid
        return IpcEndpoint(transport="uds",
                           address=f"/tmp/zcode-test-{uuid.uuid4().hex[:8]}.sock")

    def test_peer_same_uid_roundtrip(self, tmp_path):
        from packages.platform.linux.ipc import UnixSocketIpc, encode_frame, decode_frame, uds_client

        async def scenario():
            ipc = UnixSocketIpc()
            got = []

            async def handler(msg):
                got.append(msg)
                return {"v": 1, "id": msg.get("id"), "ok": True, "data": {"echo": msg.get("method")}}

            endpoint = self._endpoint(tmp_path)
            await ipc.serve(endpoint, handler)
            try:
                reader, writer = await uds_client(endpoint.address)
                writer.write(encode_frame({"v": 1, "id": 7, "method": "hello", "params": {}}))
                await writer.drain()
                data = await asyncio.wait_for(reader.read(65536), timeout=5)
                msg, _ = decode_frame(data)
                assert msg["ok"] is True and msg["id"] == 7
                writer.close()
            finally:
                await ipc.stop()
            assert got and got[0]["method"] == "hello"

        asyncio.run(asyncio.wait_for(scenario(), timeout=10))

    def test_socket_mode_owner_only(self, tmp_path):
        from packages.platform.linux.ipc import UnixSocketIpc

        async def scenario():
            ipc = UnixSocketIpc()
            endpoint = self._endpoint(tmp_path)

            async def handler(msg):
                return {"ok": True}

            await ipc.serve(endpoint, handler)
            try:
                mode = os.stat(endpoint.address).st_mode
                assert (mode & 0o777) == 0o600, oct(mode & 0o777)
            finally:
                await ipc.stop()

        asyncio.run(asyncio.wait_for(scenario(), timeout=10))

    def test_stop_removes_socket(self, tmp_path):
        from packages.platform.linux.ipc import UnixSocketIpc

        async def scenario():
            ipc = UnixSocketIpc()
            endpoint = self._endpoint(tmp_path)

            async def handler(msg):
                return {"ok": True}

            await ipc.serve(endpoint, handler)
            await ipc.stop()
            assert not os.path.exists(endpoint.address)

        asyncio.run(asyncio.wait_for(scenario(), timeout=10))

    def test_wrong_transport_rejected(self):
        from packages.platform.linux.ipc import UnixSocketIpc

        async def scenario():
            ipc = UnixSocketIpc()
            endpoint = IpcEndpoint(transport="named_pipe", address=r"\\.\pipe\x")

            async def handler(msg):
                return {"ok": True}

            with pytest.raises(ValueError):
                await ipc.serve(endpoint, handler)

        asyncio.run(scenario())

    def test_oversize_frame_rejected(self):
        from packages.platform.linux.ipc import decode_frame
        import struct
        buf = struct.pack("<I", 2 << 20) + b"x" * 16
        with pytest.raises(ValueError):
            decode_frame(buf)


@linux_only
class TestSecretServiceStore:
    def test_missing_package_fails_closed(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def no_secretstorage(name, *a, **k):
            if name == "secretstorage":
                raise ImportError("no secretstorage")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", no_secretstorage)
        from packages.platform.linux.secrets_store import SecretServiceStore
        with pytest.raises(SecretAccessError):
            SecretServiceStore()


@linux_only
class TestLogindSessionMonitor:
    def test_headless_reports_inactive_not_guessing(self, monkeypatch):
        monkeypatch.delenv("XDG_SESSION_ID", raising=False)
        from packages.platform.linux.session_monitor import LogindSessionMonitor
        state = asyncio.run(LogindSessionMonitor().current_state())
        assert state.is_user_active is False
        assert state.os_session_id is None

    def test_no_dbus_raises_platform_error(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def no_dbus(name, *a, **k):
            if name == "dbus":
                raise ImportError("no dbus")
            return real_import(name, *a, **k)

        monkeypatch.setenv("XDG_SESSION_ID", "1")
        monkeypatch.setattr(builtins, "__import__", no_dbus)
        from packages.platform.linux.session_monitor import LogindSessionMonitor
        with pytest.raises(PlatformError):
            asyncio.run(LogindSessionMonitor().current_state())


@linux_only
class TestConstrainedSubprocessSandbox:
    def _run(self, profile, exe, args, cwd=None):
        from packages.platform.linux.sandbox import ConstrainedSubprocessSandbox
        return asyncio.run(self._scenario(profile, exe, args, cwd))

    async def _scenario(self, profile, exe, args, cwd):
        from packages.platform.linux.sandbox import ConstrainedSubprocessSandbox
        sandbox = ConstrainedSubprocessSandbox()
        handle = await sandbox.create(profile)
        return await sandbox.run(handle, exe, args, cwd=cwd)

    def test_simple_exec(self):
        rc, out, _ = self._run(SandboxProfile(), "/bin/echo", ["hello"])
        assert rc == 0 and b"hello" in out

    def test_timeout_kills_tree(self):
        rc, out, err = self._run(
            SandboxProfile(exec_timeout_sec=2), "/bin/sleep", ["30"],
        )
        assert rc == -1 and b"timed out" in err

    def test_memory_rlimit_enforced(self):
        rc, _, _ = self._run(
            SandboxProfile(memory_limit_mb=64, exec_timeout_sec=10),
            sys.executable, ["-c", "x = bytearray(256 * 1024 * 1024)"],
        )
        assert rc != 0

    def test_seccomp_required_fails_closed_when_unavailable(self, monkeypatch):
        from packages.platform.linux import sandbox as sandbox_mod
        monkeypatch.setattr(
            sandbox_mod.ConstrainedSubprocessSandbox, "_seccomp_available",
            staticmethod(lambda: False),
        )
        sandbox = sandbox_mod.ConstrainedSubprocessSandbox()
        with pytest.raises(SandboxUnavailable):
            asyncio.run(sandbox.create(SandboxProfile(syscall_whitelist=["read"])))

    def test_relative_cwd_rejected(self):
        from packages.platform.linux.sandbox import ConstrainedSubprocessSandbox
        sandbox = ConstrainedSubprocessSandbox()

        async def scenario():
            handle = await sandbox.create(SandboxProfile())
            with pytest.raises(SandboxUnavailable):
                await sandbox.run(handle, "/bin/echo", ["x"], cwd="relative/path")

        asyncio.run(scenario())
