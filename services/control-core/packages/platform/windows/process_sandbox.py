"""Windows Job Object process sandbox (P1.8, ADR-008).

Each execution receives a private Job Object with kill-on-close, active-process
and memory limits. The child is launched with ``shell=False`` and is assigned
using a real process HANDLE obtained from ``OpenProcess``; a PID is never passed
to ``AssignProcessToJobObject``. stdout/stderr are drained concurrently and
bounded before being returned to the caller.

Job Objects do not provide a filesystem or network firewall. Unsupported
filesystem, syscall, identity, capability, and egress policy fields are
rejected explicitly instead of pretending that a Job Object enforces them.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import math
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from ctypes import wintypes
from typing import Mapping, Sequence

from packages.platform.shared.contracts import ProcessSandbox, SandboxProfile
from packages.platform.shared.errors import SandboxUnavailable

from ._errors import UnsupportedPlatformError

logger = logging.getLogger(__name__)

JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION = 15
JOB_OBJECT_LIMIT_WORKING_SET = 0x00000001
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
CREATE_SUSPENDED = 0x00000004
TH32CS_SNAPTHREAD = 0x00000004
THREAD_SUSPEND_RESUME = 0x0002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("ControlFlags", ctypes.c_uint32),
        ("CpuRate", ctypes.c_uint32),
    ]


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


def _handle_value(handle: object) -> int:
    if isinstance(handle, int):
        return handle
    value = getattr(handle, "value", None)
    return int(value or 0)


def _win_error(operation: str) -> SandboxUnavailable:
    code = ctypes.get_last_error()
    return SandboxUnavailable(f"{operation} failed (winerror={code})")


@dataclass(slots=True)
class WindowsSandboxHandle:
    """Owned Job Object handle and execution metadata."""

    job_handle: int
    profile: SandboxProfile
    pid: int | None = None
    started_at: float = field(default_factory=time.time)
    closed: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _run_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class WindowsProcessSandbox(ProcessSandbox):
    """Create and execute children inside Windows Job Objects."""

    @staticmethod
    def is_supported() -> bool:
        return sys.platform == "win32"

    def _require_windows(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Windows Job Objects require Windows")

    @staticmethod
    def _kernel32() -> ctypes.WinDLL:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle_type = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [handle_type, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = handle_type
        kernel32.SetInformationJobObject.argtypes = [
            handle_type,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [handle_type, handle_type]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [handle_type, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [handle_type]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = handle_type
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = handle_type
        kernel32.Thread32First.argtypes = [handle_type, ctypes.POINTER(_THREADENTRY32)]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [handle_type, ctypes.POINTER(_THREADENTRY32)]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = handle_type
        kernel32.ResumeThread.argtypes = [handle_type]
        kernel32.ResumeThread.restype = wintypes.DWORD
        return kernel32

    @staticmethod
    def _validate_profile(profile: SandboxProfile) -> None:
        """Reject policy fields that a Job Object cannot actually enforce."""

        unsupported: list[str] = []
        if profile.fs_roots:
            unsupported.append("fs_roots")
        if profile.fs_writable:
            unsupported.append("fs_writable")
        if profile.syscall_whitelist:
            unsupported.append("syscall_whitelist")
        if profile.uid_gid != (1000, 1000):
            unsupported.append("uid_gid")
        if profile.capabilities_drop != ["ALL"]:
            unsupported.append("capabilities_drop")
        if profile.privileged:
            unsupported.append("privileged")
        if profile.network_egress_allowlist:
            unsupported.append("network_egress_allowlist")
        if unsupported:
            fields = ", ".join(unsupported)
            raise SandboxUnavailable(
                f"Job Objects cannot enforce profile fields: {fields}; "
                "configure a Windows isolation broker"
            )

        if (
            isinstance(profile.cpu_limit_cores, bool)
            or not isinstance(profile.cpu_limit_cores, (int, float))
            or profile.cpu_limit_cores <= 0
            or not math.isfinite(float(profile.cpu_limit_cores))
        ):
            raise SandboxUnavailable("cpu_limit_cores must be a positive number")
        for name in (
            "memory_limit_mb",
            "pids_limit",
            "exec_timeout_sec",
            "output_size_limit_mb",
        ):
            value = getattr(profile, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SandboxUnavailable(f"{name} must be a positive integer")
        if profile.memory_limit_mb > (ctypes.c_size_t(-1).value // (1024 * 1024)):
            raise SandboxUnavailable("memory_limit_mb is too large for a Job Object")
        if profile.pids_limit > 0xFFFFFFFF:
            raise SandboxUnavailable("pids_limit is too large for a Job Object")

    def _create_job_object(self, profile: SandboxProfile) -> int:
        self._require_windows()
        self._validate_profile(profile)
        kernel32 = self._kernel32()
        raw_handle = kernel32.CreateJobObjectW(None, None)
        job_handle = _handle_value(raw_handle)
        if not job_handle:
            raise _win_error("CreateJobObjectW")

        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        if profile.pids_limit > 0:
            flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        if profile.memory_limit_mb > 0:
            flags |= JOB_OBJECT_LIMIT_JOB_MEMORY
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = flags
        info.BasicLimitInformation.ActiveProcessLimit = profile.pids_limit
        info.JobMemoryLimit = profile.memory_limit_mb * 1024 * 1024
        ok = kernel32.SetInformationJobObject(
            wintypes.HANDLE(job_handle),
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(wintypes.HANDLE(job_handle))
            raise _win_error("SetInformationJobObject(extended limits)")

        if profile.cpu_limit_cores > 0:
            # Job Objects express a hard cap as a percentage of the host's
            # aggregate CPU capacity, so convert the profile's core budget.
            logical_cpus = max(1, os.cpu_count() or 1)
            cpu_rate = min(
                10_000,
                max(1, int(profile.cpu_limit_cores * 10_000 / logical_cpus)),
            )
            cpu = _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(
                ControlFlags=(
                    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE
                    | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
                ),
                CpuRate=cpu_rate,
            )
            ok = kernel32.SetInformationJobObject(
                wintypes.HANDLE(job_handle),
                JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION,
                ctypes.byref(cpu),
                ctypes.sizeof(cpu),
            )
            if not ok:
                kernel32.CloseHandle(wintypes.HANDLE(job_handle))
                raise _win_error("SetInformationJobObject(CPU limit)")
        return job_handle

    async def create(self, profile: SandboxProfile) -> WindowsSandboxHandle:
        if not isinstance(profile, SandboxProfile):
            raise TypeError("profile must be a SandboxProfile")
        return WindowsSandboxHandle(
            job_handle=self._create_job_object(profile),
            profile=profile,
            started_at=time.time(),
        )

    def _open_process_for_assignment(self, pid: int) -> int:
        kernel32 = self._kernel32()
        access = (
            PROCESS_SET_QUOTA
            | PROCESS_TERMINATE
            | PROCESS_QUERY_LIMITED_INFORMATION
            | SYNCHRONIZE
        )
        raw = kernel32.OpenProcess(access, False, pid)
        handle = _handle_value(raw)
        if not handle:
            raise _win_error("OpenProcess")
        return handle

    def _assign_process(
        self, sandbox: WindowsSandboxHandle, process: subprocess.Popen[bytes]
    ) -> None:
        kernel32 = self._kernel32()
        process_handle = self._open_process_for_assignment(int(process.pid))
        try:
            if not kernel32.AssignProcessToJobObject(
                wintypes.HANDLE(sandbox.job_handle),
                wintypes.HANDLE(process_handle),
            ):
                raise _win_error("AssignProcessToJobObject")
        finally:
            kernel32.CloseHandle(wintypes.HANDLE(process_handle))

    def _resume_process(self, pid: int) -> None:
        """Resume a suspended Popen child after it has entered the Job.

        Popen closes the primary thread handle, so locate that thread through
        the Toolhelp snapshot while the process is still suspended. The
        process cannot execute user code or create descendants before the Job
        assignment completes.
        """

        kernel32 = self._kernel32()
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        snapshot_value = _handle_value(snapshot)
        if not snapshot_value or snapshot_value == INVALID_HANDLE_VALUE:
            raise _win_error("CreateToolhelp32Snapshot")
        try:
            entry = _THREADENTRY32(dwSize=ctypes.sizeof(_THREADENTRY32))
            found = False
            ok = kernel32.Thread32First(wintypes.HANDLE(snapshot_value), ctypes.byref(entry))
            while ok:
                if int(entry.th32OwnerProcessID) == pid:
                    thread = kernel32.OpenThread(
                        THREAD_SUSPEND_RESUME,
                        False,
                        entry.th32ThreadID,
                    )
                    thread_value = _handle_value(thread)
                    if thread_value:
                        try:
                            if kernel32.ResumeThread(wintypes.HANDLE(thread_value)) == 0xFFFFFFFF:
                                raise _win_error("ResumeThread")
                            found = True
                        finally:
                            kernel32.CloseHandle(wintypes.HANDLE(thread_value))
                        break
                ok = kernel32.Thread32Next(wintypes.HANDLE(snapshot_value), ctypes.byref(entry))
            if not found:
                raise SandboxUnavailable("could not locate suspended child thread")
        finally:
            kernel32.CloseHandle(wintypes.HANDLE(snapshot_value))

    @staticmethod
    def _collect_stream(
        stream: object, limit: int, result: list[bytes], marker: list[bool]
    ) -> None:
        captured = bytearray()
        truncated = False
        try:
            while True:
                chunk = stream.read(64 * 1024)  # type: ignore[attr-defined]
                if not chunk:
                    break
                remaining = limit - len(captured)
                if remaining > 0:
                    captured.extend(bytes(chunk[:remaining]))
                if len(chunk) > max(remaining, 0):
                    truncated = True
        except Exception:
            logger.debug("Child output reader stopped", exc_info=True)
        result.append(bytes(captured))
        marker.append(truncated)

    @staticmethod
    def _truncate(data: bytes, was_truncated: bool, limit: int) -> bytes:
        if len(data) > limit:
            data = data[:limit]
            was_truncated = True
        return data + (b"\n[TRUNCATED]" if was_truncated else b"")

    def _terminate_job(self, sandbox: WindowsSandboxHandle) -> None:
        if not sandbox.job_handle or sandbox.closed:
            return
        kernel32 = self._kernel32()
        if not kernel32.TerminateJobObject(wintypes.HANDLE(sandbox.job_handle), 1):
            code = ctypes.get_last_error()
            # ERROR_INVALID_HANDLE after a concurrent kill is idempotent.
            if code not in (6,):
                raise _win_error("TerminateJobObject")

    async def run(
        self,
        sandbox: WindowsSandboxHandle,
        executable: str,
        args: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str],
        timeout_sec: float,
    ) -> tuple[int, bytes, bytes]:
        self._require_windows()
        if not isinstance(sandbox, WindowsSandboxHandle):
            raise SandboxUnavailable("invalid sandbox handle")
        if not sandbox._run_lock.acquire(blocking=False):
            raise SandboxUnavailable("sandbox is already executing a process")
        try:
            return await self._run_claimed(
                sandbox,
                executable,
                args,
                cwd=cwd,
                env=env,
                timeout_sec=timeout_sec,
            )
        finally:
            sandbox._run_lock.release()

    async def _run_claimed(
        self,
        sandbox: WindowsSandboxHandle,
        executable: str,
        args: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str],
        timeout_sec: float,
    ) -> tuple[int, bytes, bytes]:
        self._require_windows()
        if (
            not isinstance(sandbox, WindowsSandboxHandle)
            or sandbox.closed
            or not sandbox.job_handle
        ):
            raise SandboxUnavailable("sandbox handle is closed")
        if not executable or not isinstance(executable, str):
            raise ValueError("executable must be a non-empty path")
        if any(not isinstance(value, str) for value in args):
            raise TypeError("all process arguments must be strings")
        if not os.path.isdir(cwd):
            raise FileNotFoundError(cwd)
        if (
            isinstance(timeout_sec, bool)
            or not isinstance(timeout_sec, (int, float))
            or timeout_sec <= 0
            or not math.isfinite(float(timeout_sec))
        ):
            raise ValueError("timeout_sec must be a finite positive number")
        profile_timeout = sandbox.profile.exec_timeout_sec
        effective_timeout = (
            min(float(timeout_sec), float(profile_timeout))
            if profile_timeout > 0
            else float(timeout_sec)
        )

        merged_env = os.environ.copy()
        merged_env.update({str(key): str(value) for key, value in sandbox.profile.env_vars.items()})
        merged_env.update({str(key): str(value) for key, value in env.items()})
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | CREATE_SUSPENDED
        try:
            process = subprocess.Popen(
                [executable, *list(args)],
                cwd=cwd,
                env=merged_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise SandboxUnavailable(f"process launch failed: {exc}") from exc

        sandbox.pid = int(process.pid)
        try:
            self._assign_process(sandbox, process)
            self._resume_process(int(process.pid))
        except Exception as exc:
            # Assignment failure must not leave an uncontained child alive.
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=5)
            except Exception:
                pass
            try:
                self._terminate_job(sandbox)
            except Exception:
                logger.debug("Could not terminate failed sandbox assignment", exc_info=True)
            try:
                self._kernel32().CloseHandle(wintypes.HANDLE(sandbox.job_handle))
            except Exception:
                logger.debug("Could not close failed sandbox Job Object", exc_info=True)
            sandbox.job_handle = 0
            sandbox.closed = True
            sandbox.pid = None
            raise SandboxUnavailable("could not assign child to Job Object") from exc

        limit = sandbox.profile.output_size_limit_mb * 1024 * 1024
        stdout_data: list[bytes] = []
        stderr_data: list[bytes] = []
        stdout_truncated: list[bool] = []
        stderr_truncated: list[bool] = []
        stdout_thread = threading.Thread(
            target=self._collect_stream,
            args=(process.stdout, limit, stdout_data, stdout_truncated),
            name="p1-sandbox-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._collect_stream,
            args=(process.stderr, limit, stderr_data, stderr_truncated),
            name="p1-sandbox-stderr",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        timed_out = False
        try:
            await asyncio.to_thread(process.wait, timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                self._terminate_job(sandbox)
            except Exception:
                logger.exception("Job termination failed after timeout")
                try:
                    process.kill()
                except Exception:
                    pass
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except Exception:
                pass
        except asyncio.CancelledError:
            # Cancellation is a security boundary: terminate the Job before
            # propagating cancellation so no child survives the caller task.
            try:
                self._terminate_job(sandbox)
            except Exception:
                logger.exception("Job termination failed after cancellation")
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except Exception:
                pass
            raise
        except Exception:
            try:
                self._terminate_job(sandbox)
            except Exception:
                logger.exception("Job termination failed after run error")
            try:
                await asyncio.to_thread(process.wait, timeout=5)
            except Exception:
                pass
            raise
        finally:
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            if sandbox.pid == process.pid:
                sandbox.pid = None

        out = self._truncate(
            stdout_data[0] if stdout_data else b"",
            bool(stdout_truncated and stdout_truncated[0]),
            limit,
        )
        err = self._truncate(
            stderr_data[0] if stderr_data else b"",
            bool(stderr_truncated and stderr_truncated[0]),
            limit,
        )
        if timed_out:
            out += b"\n[TIMEOUT KILLED]"
            err += b"\n[TIMEOUT KILLED]"
        return int(process.returncode if process.returncode is not None else 1), out, err

    async def kill_tree(self, sandbox: WindowsSandboxHandle) -> None:
        if not isinstance(sandbox, WindowsSandboxHandle):
            raise TypeError("sandbox must be a WindowsSandboxHandle")
        with sandbox._lock:
            if sandbox.closed:
                return
            try:
                self._terminate_job(sandbox)
            finally:
                if sandbox.job_handle and sys.platform == "win32":
                    try:
                        self._kernel32().CloseHandle(wintypes.HANDLE(sandbox.job_handle))
                    except Exception:
                        logger.debug("Job Object close failed", exc_info=True)
                sandbox.closed = True
                sandbox.job_handle = 0


    # Compatibility with the name used by the implementation manual.
    def _kill_job(self, sandbox: WindowsSandboxHandle) -> None:
        self._terminate_job(sandbox)


__all__ = ["WindowsProcessSandbox", "WindowsSandboxHandle"]
