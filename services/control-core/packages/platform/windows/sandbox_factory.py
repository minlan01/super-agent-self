"""Task-scoped Windows AppContainer process sandbox factory."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from packages.platform.shared.contracts import SandboxProfile
from packages.platform.shared.errors import SandboxUnavailable

from .isolation import create_default_isolation
from .process_sandbox import WindowsProcessSandbox, WindowsSandboxHandle


class WindowsProcessSandboxFactory:
    """Create and dispose one isolation boundary per tool execution."""

    @staticmethod
    def _stage_trusted_executable(
        runtime_root: str,
        executable: str,
    ) -> str:
        source = Path(executable).resolve(strict=True)
        destination = Path(runtime_root) / source.name
        shutil.copy2(source, destination)
        return str(destination)

    @staticmethod
    def windows_shell_executable() -> str:
        system_root = os.environ.get("SYSTEMROOT")
        if not system_root:
            raise SandboxUnavailable("SYSTEMROOT is unavailable")
        shell = Path(system_root) / "System32" / "cmd.exe"
        if not shell.is_file():
            raise SandboxUnavailable(f"Windows command shell is unavailable: {shell}")
        return str(shell)

    @classmethod
    async def execute(
        cls,
        *,
        workspace_root: str,
        executable: str,
        args: Sequence[str],
        cwd: str,
        env: Mapping[str, str] | None,
        timeout_sec: float,
        profile: SandboxProfile | None = None,
        stage_executable: bool = False,
    ) -> tuple[int, bytes, bytes]:
        if sys.platform != "win32":
            raise SandboxUnavailable("Windows sandbox factory requires Windows")
        workspace = str(Path(workspace_root).resolve(strict=True))
        effective_executable = executable
        runtime_root: str | None = None
        broker = None
        sandbox = None
        handle: WindowsSandboxHandle | None = None
        try:
            if stage_executable:
                runtime_root = tempfile.mkdtemp(prefix="zcode-p39-runtime-")
            broker = create_default_isolation(
                workspace,
                runtime_roots=(runtime_root,) if runtime_root else (),
            )
            sandbox = WindowsProcessSandbox(broker)
            broker.initialize()
            if runtime_root is not None:
                effective_executable = cls._stage_trusted_executable(
                    runtime_root,
                    executable,
                )
            handle = await sandbox.create(
                profile
                or SandboxProfile(
                    exec_timeout_sec=max(1, int(timeout_sec)),
                    output_size_limit_mb=10,
                )
            )
            result = await sandbox.run(
                handle,
                effective_executable,
                tuple(args),
                cwd=cwd,
                env=dict(env or {}),
                timeout_sec=timeout_sec,
            )
            if b"[TIMEOUT KILLED]" in result[1] or b"[TIMEOUT KILLED]" in result[2]:
                raise TimeoutError(f"process timed out after {timeout_sec}s")
            return result
        finally:
            try:
                if handle is not None and sandbox is not None:
                    await sandbox.kill_tree(handle)
            finally:
                try:
                    if broker is not None:
                        broker.close()
                finally:
                    if runtime_root is not None:
                        shutil.rmtree(runtime_root, ignore_errors=True)


__all__ = ["WindowsProcessSandboxFactory"]
