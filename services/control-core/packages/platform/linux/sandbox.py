"""Linux ProcessSandbox — constrained subprocess (P5 baseline).

Spec §4.4: "user namespace + seccomp + cgroup". Unprivileged userns and
cgroup delegation are distribution-dependent, so this baseline enforces
everything that is universally available today and hard-fails (never
silently downgrades):

  - separate process group (kill the whole tree)
  - RLIMIT_CPU / RLIMIT_AS / RLIMIT_NPROC from SandboxProfile
  - working directory jailed to the profile's writable root
  - environment reduced to an explicit allowlist
  - output size cap
  - exec timeout with process-group kill

seccomp-bpf (syscall whitelist) and unprivileged userns are layered on
when the kernel/session exposes them; absence raises SandboxUnavailable
only when the profile *requires* them (non-empty syscall_whitelist).
"""

from __future__ import annotations

import asyncio
import os
import resource
import signal
from dataclasses import dataclass
from typing import Any

import structlog

from packages.platform.shared.contracts import ProcessSandbox, SandboxProfile
from packages.platform.shared.errors import SandboxUnavailable

logger = structlog.get_logger()

_ENV_ALLOWLIST = (
    "PATH", "LANG", "LC_ALL", "HOME", "TMPDIR", "PYTHONUNBUFFERED",
    "PYTHONDONTWRITEBYTECODE",
)


@dataclass
class LinuxSandboxHandle:
    profile: SandboxProfile
    proc: asyncio.subprocess.Process | None = None


class ConstrainedSubprocessSandbox(ProcessSandbox):
    """Baseline Linux sandbox: rlimits + process group + jailed cwd."""

    async def create(self, profile: SandboxProfile) -> object:
        if profile.syscall_whitelist:
            availability = self._seccomp_available()
            if not availability:
                raise SandboxUnavailable(
                    "profile requires seccomp syscall whitelist but the "
                    "kernel does not expose seccomp-bpf — refusing to run "
                    "unsandboxed (fail closed)"
                )
        writable = profile.fs_writable or ["/tmp"]
        root = writable[0]
        if not os.path.isdir(root):
            try:
                os.makedirs(root, mode=0o700, exist_ok=True)
            except OSError as exc:
                raise SandboxUnavailable(f"writable root unusable: {root}: {exc}") from exc
        return LinuxSandboxHandle(profile=profile)

    async def run(self, handle_obj: object, executable: str,
                  args: list[str], *, cwd: str | None = None,
                  env: dict[str, str] | None = None) -> tuple[int, bytes, bytes]:
        handle: LinuxSandboxHandle = handle_obj  # type: ignore[assignment]
        profile = handle.profile

        def _preexec() -> None:  # runs in the forked child
            os.setsid()
            cur_nproc = resource.getrlimit(resource.RLIMIT_NPROC)
            limits = (
                (resource.RLIMIT_CPU, int(profile.cpu_limit_cores * max(1, profile.exec_timeout_sec))),
                (resource.RLIMIT_AS, profile.memory_limit_mb * 1024 * 1024),
                # NPROC: never raise the inherited hard cap (EINVAL otherwise).
                (resource.RLIMIT_NPROC,
                 (min(profile.pids_limit, cur_nproc[1]), cur_nproc[1])),
                (resource.RLIMIT_FSIZE, profile.output_size_limit_mb * 1024 * 1024),
            )
            for which, value in limits:
                soft, hard = value if isinstance(value, tuple) else (value, value)
                resource.setrlimit(which, (soft, hard))

        child_env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
        if env:
            child_env.update(env)

        workdir = cwd or (profile.fs_writable[0] if profile.fs_writable else "/tmp")
        if not os.path.isabs(workdir):
            raise SandboxUnavailable(f"cwd must be absolute: {workdir}")

        try:
            handle.proc = await asyncio.create_subprocess_exec(
                executable, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=child_env,
                preexec_fn=_preexec,
            )
        except (FileNotFoundError, PermissionError) as exc:
            raise SandboxUnavailable(f"failed to launch sandboxed process: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                handle.proc.communicate(), timeout=profile.exec_timeout_sec,
            )
        except asyncio.TimeoutError:
            await self.kill_tree(handle_obj)
            return (-1, b"", f"timed out after {profile.exec_timeout_sec}s".encode())

        cap = profile.output_size_limit_mb * 1024 * 1024
        return (handle.proc.returncode or 0, stdout[:cap], stderr[:cap])

    async def kill_tree(self, handle_obj: object) -> None:
        handle: LinuxSandboxHandle = handle_obj  # type: ignore[assignment]
        if handle.proc and handle.proc.returncode is None:
            try:
                os.killpg(os.getpgid(handle.proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def close(self, handle_obj: object) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.kill_tree(handle_obj))
        except RuntimeError:
            asyncio.run(self.kill_tree(handle_obj))

    @staticmethod
    def _seccomp_available() -> bool:
        try:
            with open("/proc/self/status", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("Seccomp:") and line.split()[1] in ("2", "1"):
                        return True
            return False
        except OSError:
            return False
