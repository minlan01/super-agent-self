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
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, BinaryIO

from packages.platform.shared.contracts import ProcessSandbox, SandboxProfile
from packages.platform.shared.errors import SandboxUnavailable

from ._errors import UnsupportedPlatformError

if TYPE_CHECKING:
    from .isolation import WindowsIsolationBroker

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
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_UNICODE_ENVIRONMENT = 0x00000400
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
HANDLE_FLAG_INHERIT = 0x00000001
TH32CS_SNAPTHREAD = 0x00000004
THREAD_SUSPEND_RESUME = 0x0002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF
INFINITE = 0xFFFFFFFF
STILL_ACTIVE = 259
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25
TOKEN_IS_APPCONTAINER = 29
TOKEN_APPCONTAINER_SID = 31
LOW_INTEGRITY_SID = "S-1-16-4096"


class _IO_COUNTERS(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(  # noqa: N801 - Win32 ABI name
    ctypes.Structure
):
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


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(  # noqa: N801 - Win32 ABI name
    ctypes.Structure
):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(  # noqa: N801 - Win32 ABI name
    ctypes.Structure
):
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


class _SECURITY_ATTRIBUTES(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _SID_AND_ATTRIBUTES(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [
        ("Sid", wintypes.LPVOID),
        ("Attributes", wintypes.DWORD),
    ]


class _SECURITY_CAPABILITIES(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [
        ("AppContainerSid", wintypes.LPVOID),
        ("Capabilities", ctypes.POINTER(_SID_AND_ATTRIBUTES)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", wintypes.LPVOID),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _handle_value(handle: object) -> int:
    if isinstance(handle, int):
        return handle
    value = getattr(handle, "value", None)
    if value is not None:
        return int(value or 0)
    try:
        return int(handle)
    except (TypeError, ValueError):
        return 0


def _win_error(operation: str) -> SandboxUnavailable:
    code = ctypes.get_last_error()
    return SandboxUnavailable(f"{operation} failed (winerror={code})")


class _RestrictedProcess:
    """Small Popen-compatible wrapper for a CreateProcessAsUserW child."""

    def __init__(
        self,
        *,
        process_handle: int,
        thread_handle: int,
        pid: int,
        stdout: BinaryIO,
        stderr: BinaryIO,
    ) -> None:
        self.native_process_handle = process_handle
        self._thread_handle = thread_handle
        self.pid = pid
        self.stdout = stdout
        self.stderr = stderr
        self.returncode: int | None = None

    @staticmethod
    def _kernel32() -> ctypes.WinDLL:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        return kernel32

    def _read_exit_code(self) -> int:
        code = wintypes.DWORD()
        if not self._kernel32().GetExitCodeProcess(
            wintypes.HANDLE(self.native_process_handle),
            ctypes.byref(code),
        ):
            raise _win_error("GetExitCodeProcess")
        return int(code.value)

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is not None:
            return self.returncode
        if timeout is None:
            timeout_ms = INFINITE
        else:
            timeout_ms = min(0xFFFFFFFE, max(0, math.ceil(timeout * 1000)))
        result = self._kernel32().WaitForSingleObject(
            wintypes.HANDLE(self.native_process_handle),
            timeout_ms,
        )
        if result == WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired([self.pid], timeout)
        if result == WAIT_FAILED:
            raise _win_error("WaitForSingleObject")
        if result != WAIT_OBJECT_0:
            raise SandboxUnavailable(f"unexpected process wait result: {result}")
        self.returncode = self._read_exit_code()
        return self.returncode

    def kill(self) -> None:
        if self.returncode is not None:
            return
        if self._read_exit_code() != STILL_ACTIVE:
            self.wait(timeout=0)
            return
        if not self._kernel32().TerminateProcess(
            wintypes.HANDLE(self.native_process_handle),
            1,
        ):
            if self._read_exit_code() == STILL_ACTIVE:
                raise _win_error("TerminateProcess")

    def resume(self) -> None:
        thread_handle = self._thread_handle
        self._thread_handle = 0
        try:
            if self._kernel32().ResumeThread(wintypes.HANDLE(thread_handle)) == 0xFFFFFFFF:
                raise _win_error("ResumeThread")
        finally:
            if thread_handle:
                self._kernel32().CloseHandle(wintypes.HANDLE(thread_handle))

    def close_native_handles(self) -> None:
        kernel32 = self._kernel32()
        if self._thread_handle:
            kernel32.CloseHandle(wintypes.HANDLE(self._thread_handle))
            self._thread_handle = 0
        if self.native_process_handle:
            kernel32.CloseHandle(wintypes.HANDLE(self.native_process_handle))
            self.native_process_handle = 0


@dataclass(slots=True)
class WindowsSandboxHandle:
    """Owned Job Object handle and execution metadata."""

    job_handle: int
    profile: SandboxProfile
    pid: int | None = None
    started_at: float = field(default_factory=time.time)
    closed: bool = False
    closing: bool = False
    broker_launch_acquired: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _run_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass(slots=True, frozen=True)
class _IsolationLaunchContext:
    token_handle: int
    appcontainer_sid_pointer: int
    appcontainer_sid: str


class WindowsProcessSandbox(ProcessSandbox):
    """Create and execute children inside Windows Job Objects."""

    def __init__(self, isolation_broker: WindowsIsolationBroker | None = None) -> None:
        self._isolation_broker = isolation_broker

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
    def _advapi32() -> ctypes.WinDLL:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.CreateProcessAsUserW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            ctypes.POINTER(_SECURITY_ATTRIBUTES),
            ctypes.POINTER(_SECURITY_ATTRIBUTES),
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(_STARTUPINFOW),
            ctypes.POINTER(_PROCESS_INFORMATION),
        ]
        advapi32.CreateProcessAsUserW.restype = wintypes.BOOL
        return advapi32

    @staticmethod
    def _extended_process_apis() -> ctypes.WinDLL:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreatePipe.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(_SECURITY_ATTRIBUTES),
            wintypes.DWORD,
        ]
        kernel32.CreatePipe.restype = wintypes.BOOL
        kernel32.SetHandleInformation.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        kernel32.SetHandleInformation.restype = wintypes.BOOL
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_SECURITY_ATTRIBUTES),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.InitializeProcThreadAttributeList.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        kernel32.UpdateProcThreadAttribute.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
        kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
        kernel32.DeleteProcThreadAttributeList.restype = None
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
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
        launch_acquired = False
        if self._isolation_broker is not None:
            self._isolation_launch_context(profile)
            self._isolation_broker.acquire_launch()
            launch_acquired = True
        try:
            return WindowsSandboxHandle(
                job_handle=self._create_job_object(profile),
                profile=profile,
                started_at=time.time(),
                broker_launch_acquired=launch_acquired,
            )
        except Exception:
            if launch_acquired and self._isolation_broker is not None:
                self._isolation_broker.release_launch()
            raise

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
        self,
        sandbox: WindowsSandboxHandle,
        process: subprocess.Popen[bytes] | _RestrictedProcess,
    ) -> None:
        kernel32 = self._kernel32()
        owned_process_handle = getattr(process, "native_process_handle", 0)
        process_handle = int(owned_process_handle) or self._open_process_for_assignment(
            int(process.pid)
        )
        try:
            if not kernel32.AssignProcessToJobObject(
                wintypes.HANDLE(sandbox.job_handle),
                wintypes.HANDLE(process_handle),
            ):
                raise _win_error("AssignProcessToJobObject")
        finally:
            if not owned_process_handle:
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

    def _isolation_launch_context(
        self,
        profile: SandboxProfile | None = None,
    ) -> _IsolationLaunchContext:
        broker = self._isolation_broker
        if broker is None:
            raise SandboxUnavailable("restricted process launch requires an isolation broker")
        boundary = broker.boundary
        token = broker.restricted_token
        token_handle = _handle_value(token) if token is not None else 0
        sid_pointer = broker.appcontainer_sid_pointer
        sid_text = broker.appcontainer_sid
        if (
            boundary is None
            or not boundary.initialization_verified
            or not broker.accepting_launches
            or not boundary.restricted_token_applied
            or not boundary.appcontainer_applied
            or not boundary.workspace_acl_applied
            or not token_handle
            or not sid_pointer
            or not sid_text
        ):
            raise SandboxUnavailable(
                "Windows isolation broker is not initialized with a complete "
                "AppContainer boundary"
            )
        if broker.config.egress_allowlist:
            raise SandboxUnavailable(
                "non-empty egress allowlist requires a WFP or proxy broker"
            )
        if profile is not None and profile.network_egress_allowlist:
            raise SandboxUnavailable(
                "non-empty sandbox egress allowlist requires a WFP or proxy broker"
            )
        return _IsolationLaunchContext(
            token_handle=token_handle,
            appcontainer_sid_pointer=sid_pointer,
            appcontainer_sid=sid_text,
        )

    @staticmethod
    def _environment_block(env: Mapping[str, str]) -> ctypes.Array[ctypes.c_wchar]:
        normalized: dict[str, str] = {}
        for key, value in env.items():
            key_text = str(key)
            value_text = str(value)
            if not key_text or "=" in key_text or "\x00" in key_text or "\x00" in value_text:
                raise ValueError(f"invalid environment variable name: {key_text!r}")
            normalized[key_text] = value_text
        entries = [
            f"{key}={value}"
            for key, value in sorted(normalized.items(), key=lambda item: item[0].upper())
        ]
        return ctypes.create_unicode_buffer("\x00".join(entries) + "\x00\x00")

    @staticmethod
    def _pipe_reader(handle: int) -> BinaryIO:
        import msvcrt

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        fd = msvcrt.open_osfhandle(handle, flags)
        try:
            return os.fdopen(fd, "rb", buffering=0)
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _create_inheritable_pipe(kernel32: ctypes.WinDLL) -> tuple[int, int]:
        security = _SECURITY_ATTRIBUTES(
            nLength=ctypes.sizeof(_SECURITY_ATTRIBUTES),
            lpSecurityDescriptor=None,
            bInheritHandle=True,
        )
        read_handle = wintypes.HANDLE()
        write_handle = wintypes.HANDLE()
        if not kernel32.CreatePipe(
            ctypes.byref(read_handle),
            ctypes.byref(write_handle),
            ctypes.byref(security),
            0,
        ):
            raise _win_error("CreatePipe")
        read_value = _handle_value(read_handle)
        write_value = _handle_value(write_handle)
        if not kernel32.SetHandleInformation(
            wintypes.HANDLE(read_value),
            HANDLE_FLAG_INHERIT,
            0,
        ):
            kernel32.CloseHandle(wintypes.HANDLE(read_value))
            kernel32.CloseHandle(wintypes.HANDLE(write_value))
            raise _win_error("SetHandleInformation")
        return read_value, write_value

    @staticmethod
    def _create_attribute_list(
        kernel32: ctypes.WinDLL,
        inherited_handles: Sequence[int],
        appcontainer_sid_pointer: int,
    ) -> tuple[
        ctypes.Array[ctypes.c_char],
        ctypes.Array[wintypes.HANDLE],
        _SECURITY_CAPABILITIES,
    ]:
        required = ctypes.c_size_t()
        ctypes.set_last_error(0)
        kernel32.InitializeProcThreadAttributeList(
            None,
            2,
            0,
            ctypes.byref(required),
        )
        if not required.value:
            raise _win_error("InitializeProcThreadAttributeList(size)")
        buffer = ctypes.create_string_buffer(required.value)
        if not kernel32.InitializeProcThreadAttributeList(
            ctypes.cast(buffer, wintypes.LPVOID),
            2,
            0,
            ctypes.byref(required),
        ):
            raise _win_error("InitializeProcThreadAttributeList")

        handle_array_type = wintypes.HANDLE * len(inherited_handles)
        handle_array = handle_array_type(
            *(wintypes.HANDLE(value) for value in inherited_handles)
        )
        if not kernel32.UpdateProcThreadAttribute(
            ctypes.cast(buffer, wintypes.LPVOID),
            0,
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            ctypes.cast(handle_array, wintypes.LPVOID),
            ctypes.sizeof(handle_array),
            None,
            None,
        ):
            kernel32.DeleteProcThreadAttributeList(ctypes.cast(buffer, wintypes.LPVOID))
            raise _win_error("UpdateProcThreadAttribute(handle list)")

        security_capabilities = _SECURITY_CAPABILITIES(
            AppContainerSid=wintypes.LPVOID(appcontainer_sid_pointer),
            Capabilities=None,
            CapabilityCount=0,
            Reserved=0,
        )
        if not kernel32.UpdateProcThreadAttribute(
            ctypes.cast(buffer, wintypes.LPVOID),
            0,
            PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.cast(ctypes.byref(security_capabilities), wintypes.LPVOID),
            ctypes.sizeof(security_capabilities),
            None,
            None,
        ):
            kernel32.DeleteProcThreadAttributeList(
                ctypes.cast(buffer, wintypes.LPVOID)
            )
            raise _win_error("UpdateProcThreadAttribute(security capabilities)")
        return buffer, handle_array, security_capabilities

    def _launch_restricted_process(
        self,
        executable: str,
        args: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str],
    ) -> _RestrictedProcess:
        """Create a suspended restricted child with only its stdio handles inherited."""

        launch_context = self._isolation_launch_context()
        kernel32 = self._extended_process_apis()
        advapi32 = self._advapi32()
        handles_to_close: set[int] = set()
        attribute_buffer: ctypes.Array[ctypes.c_char] | None = None
        process_info = _PROCESS_INFORMATION()
        stdout_stream: BinaryIO | None = None
        stderr_stream: BinaryIO | None = None
        try:
            stdout_read, stdout_write = self._create_inheritable_pipe(kernel32)
            handles_to_close.update((stdout_read, stdout_write))
            stderr_read, stderr_write = self._create_inheritable_pipe(kernel32)
            handles_to_close.update((stderr_read, stderr_write))

            security = _SECURITY_ATTRIBUTES(
                nLength=ctypes.sizeof(_SECURITY_ATTRIBUTES),
                lpSecurityDescriptor=None,
                bInheritHandle=True,
            )
            stdin_handle = _handle_value(
                kernel32.CreateFileW(
                    "NUL",
                    GENERIC_READ,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    ctypes.byref(security),
                    OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL,
                    None,
                )
            )
            if not stdin_handle or stdin_handle == INVALID_HANDLE_VALUE:
                raise _win_error("CreateFileW(NUL)")
            handles_to_close.add(stdin_handle)

            attribute_buffer, _handle_array, _security_capabilities = (
                self._create_attribute_list(
                    kernel32,
                    (stdin_handle, stdout_write, stderr_write),
                    launch_context.appcontainer_sid_pointer,
                )
            )
            startup = _STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = wintypes.HANDLE(stdin_handle)
            startup.StartupInfo.hStdOutput = wintypes.HANDLE(stdout_write)
            startup.StartupInfo.hStdError = wintypes.HANDLE(stderr_write)
            startup.lpAttributeList = ctypes.cast(attribute_buffer, wintypes.LPVOID)

            argv = [executable, *list(args)]
            command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            environment = self._environment_block(env)
            creation_flags = (
                CREATE_SUSPENDED
                | CREATE_NEW_PROCESS_GROUP
                | CREATE_UNICODE_ENVIRONMENT
                | EXTENDED_STARTUPINFO_PRESENT
            )
            if not advapi32.CreateProcessAsUserW(
                wintypes.HANDLE(launch_context.token_handle),
                executable,
                command_line,
                None,
                None,
                True,
                creation_flags,
                ctypes.cast(environment, wintypes.LPVOID),
                cwd,
                ctypes.byref(startup.StartupInfo),
                ctypes.byref(process_info),
            ):
                raise _win_error("CreateProcessAsUserW")

            for child_only_handle in (stdin_handle, stdout_write, stderr_write):
                kernel32.CloseHandle(wintypes.HANDLE(child_only_handle))
                handles_to_close.discard(child_only_handle)

            stdout_stream = self._pipe_reader(stdout_read)
            handles_to_close.discard(stdout_read)
            stderr_stream = self._pipe_reader(stderr_read)
            handles_to_close.discard(stderr_read)
            return _RestrictedProcess(
                process_handle=_handle_value(process_info.hProcess),
                thread_handle=_handle_value(process_info.hThread),
                pid=int(process_info.dwProcessId),
                stdout=stdout_stream,
                stderr=stderr_stream,
            )
        except Exception:
            if process_info.hProcess:
                raw_process = _handle_value(process_info.hProcess)
                fallback_stdout = stdout_stream or open(os.devnull, "rb")
                fallback_stderr = stderr_stream or open(os.devnull, "rb")
                terminate = _RestrictedProcess(
                    process_handle=raw_process,
                    thread_handle=_handle_value(process_info.hThread),
                    pid=int(process_info.dwProcessId),
                    stdout=fallback_stdout,
                    stderr=fallback_stderr,
                )
                try:
                    terminate.kill()
                    terminate.wait(timeout=5)
                except Exception:
                    logger.debug("Could not terminate failed restricted launch", exc_info=True)
                finally:
                    terminate.close_native_handles()
                    if stdout_stream is None:
                        fallback_stdout.close()
                    if stderr_stream is None:
                        fallback_stderr.close()
                    process_info.hProcess = None
                    process_info.hThread = None
            if stdout_stream is not None:
                stdout_stream.close()
            if stderr_stream is not None:
                stderr_stream.close()
            raise
        finally:
            if attribute_buffer is not None:
                kernel32.DeleteProcThreadAttributeList(
                    ctypes.cast(attribute_buffer, wintypes.LPVOID)
                )
            for handle in handles_to_close:
                kernel32.CloseHandle(wintypes.HANDLE(handle))

    @staticmethod
    def _token_information(
        advapi32: ctypes.WinDLL,
        token: int,
        information_class: int,
    ) -> ctypes.Array[ctypes.c_char]:
        required = wintypes.DWORD()
        ctypes.set_last_error(0)
        advapi32.GetTokenInformation(
            wintypes.HANDLE(token),
            information_class,
            None,
            0,
            ctypes.byref(required),
        )
        if not required.value:
            raise _win_error("GetTokenInformation(size)")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            wintypes.HANDLE(token),
            information_class,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise _win_error("GetTokenInformation")
        return buffer

    @staticmethod
    def _sid_to_string(
        advapi32: ctypes.WinDLL,
        kernel32: ctypes.WinDLL,
        sid_pointer: int,
    ) -> str:
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(
            wintypes.LPVOID(sid_pointer),
            ctypes.byref(text),
        ):
            raise _win_error("ConvertSidToStringSidW")
        try:
            value = text.value
            if not value:
                raise SandboxUnavailable("token SID string is empty")
            return value
        finally:
            kernel32.LocalFree(text)

    def _verify_child_isolation_token(self, process: _RestrictedProcess) -> None:
        try:
            import win32security

            launch_context = self._isolation_launch_context()
            token = win32security.OpenProcessToken(
                process.native_process_handle,
                win32security.TOKEN_QUERY,
            )
            try:
                if not win32security.IsTokenRestricted(token):
                    raise SandboxUnavailable("restricted child received an unrestricted token")
                if (
                    win32security.GetTokenInformation(token, win32security.TokenType)
                    != win32security.TokenPrimary
                ):
                    raise SandboxUnavailable("restricted child token is not primary")

                advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                advapi32.GetTokenInformation.argtypes = [
                    wintypes.HANDLE,
                    ctypes.c_int,
                    wintypes.LPVOID,
                    wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD),
                ]
                advapi32.GetTokenInformation.restype = wintypes.BOOL
                advapi32.ConvertSidToStringSidW.argtypes = [
                    wintypes.LPVOID,
                    ctypes.POINTER(wintypes.LPWSTR),
                ]
                advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
                advapi32.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
                advapi32.EqualSid.restype = wintypes.BOOL
                kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
                kernel32.LocalFree.restype = wintypes.HLOCAL

                is_appcontainer = wintypes.DWORD()
                returned = wintypes.DWORD()
                if not advapi32.GetTokenInformation(
                    wintypes.HANDLE(int(token)),
                    TOKEN_IS_APPCONTAINER,
                    ctypes.byref(is_appcontainer),
                    ctypes.sizeof(is_appcontainer),
                    ctypes.byref(returned),
                ):
                    raise _win_error("GetTokenInformation(TokenIsAppContainer)")
                if is_appcontainer.value != 1:
                    raise SandboxUnavailable("child token is not an AppContainer token")

                appcontainer_buffer = self._token_information(
                    advapi32,
                    int(token),
                    TOKEN_APPCONTAINER_SID,
                )
                actual_sid_pointer = ctypes.cast(
                    appcontainer_buffer,
                    ctypes.POINTER(wintypes.LPVOID),
                ).contents.value
                if not actual_sid_pointer:
                    raise SandboxUnavailable("child AppContainer SID is missing")
                if not advapi32.EqualSid(
                    wintypes.LPVOID(actual_sid_pointer),
                    wintypes.LPVOID(launch_context.appcontainer_sid_pointer),
                ):
                    raise SandboxUnavailable("child AppContainer SID does not match broker")

                integrity_buffer = self._token_information(
                    advapi32,
                    int(token),
                    TOKEN_INTEGRITY_LEVEL,
                )
                integrity = ctypes.cast(
                    integrity_buffer,
                    ctypes.POINTER(_SID_AND_ATTRIBUTES),
                ).contents
                integrity_sid = self._sid_to_string(
                    advapi32,
                    kernel32,
                    int(integrity.Sid),
                )
                if integrity_sid != LOW_INTEGRITY_SID:
                    raise SandboxUnavailable(
                        f"child integrity level is not Low: {integrity_sid}"
                    )
            finally:
                token.Close()
        except SandboxUnavailable:
            raise
        except Exception as exc:
            raise SandboxUnavailable(
                f"could not verify child isolation token: {exc}"
            ) from exc

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
        with sandbox._lock:
            if sandbox.closed or sandbox.closing:
                raise SandboxUnavailable("sandbox handle is closed")
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
        if self._isolation_broker is not None:
            if not self._isolation_broker.path_is_in_workspace(cwd):
                raise SandboxUnavailable("sandbox cwd must be inside the task workspace")
            if not self._isolation_broker.executable_is_authorized(executable):
                raise SandboxUnavailable(
                    "sandbox executable must be inside the workspace or an explicit "
                    "runtime_root"
                )
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
        requested_env = {
            str(key): str(value) for key, value in sandbox.profile.env_vars.items()
        }
        requested_env.update({str(key): str(value) for key, value in env.items()})
        if self._isolation_broker is not None:
            merged_env = self._isolation_broker.filter_environment(requested_env)
        else:
            merged_env.update(requested_env)
        creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED
        try:
            if self._isolation_broker is not None:
                process: subprocess.Popen[bytes] | _RestrictedProcess = (
                    self._launch_restricted_process(
                        executable,
                        args,
                        cwd=cwd,
                        env=merged_env,
                    )
                )
            else:
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
        except SandboxUnavailable:
            raise
        except (OSError, ValueError) as exc:
            raise SandboxUnavailable(f"process launch failed: {exc}") from exc

        sandbox.pid = int(process.pid)
        try:
            self._assign_process(sandbox, process)
            if isinstance(process, _RestrictedProcess):
                self._verify_child_isolation_token(process)
                process.resume()
            else:
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
            if isinstance(process, _RestrictedProcess):
                process.close_native_handles()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
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
            if (
                sandbox.broker_launch_acquired
                and self._isolation_broker is not None
            ):
                self._isolation_broker.release_launch()
                sandbox.broker_launch_acquired = False
            raise SandboxUnavailable(
                "could not establish child isolation boundary"
            ) from exc

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
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            if isinstance(process, _RestrictedProcess):
                process.close_native_handles()
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
            sandbox.closing = True
        # Terminate first.  Waiting for the run lock before terminating would
        # deadlock because an active run owns that lock while waiting on the
        # child process to exit.
        try:
            self._terminate_job(sandbox)
        except Exception:
            logger.debug("Job termination during close failed", exc_info=True)
        await asyncio.to_thread(sandbox._run_lock.acquire)
        try:
            with sandbox._lock:
                if sandbox.closed:
                    sandbox.closing = False
                    return
                try:
                    self._terminate_job(sandbox)
                finally:
                    if sandbox.job_handle and sys.platform == "win32":
                        try:
                            self._kernel32().CloseHandle(
                                wintypes.HANDLE(sandbox.job_handle)
                            )
                        except Exception:
                            logger.debug("Job Object close failed", exc_info=True)
                    sandbox.closed = True
                    sandbox.closing = False
                    sandbox.job_handle = 0
                    if (
                        sandbox.broker_launch_acquired
                        and self._isolation_broker is not None
                    ):
                        self._isolation_broker.release_launch()
                        sandbox.broker_launch_acquired = False
        finally:
            with sandbox._lock:
                if not sandbox.closed:
                    sandbox.closing = False
            sandbox._run_lock.release()


    # Compatibility with the name used by the implementation manual.
    def _kill_job(self, sandbox: WindowsSandboxHandle) -> None:
        self._terminate_job(sandbox)


__all__ = ["WindowsProcessSandbox", "WindowsSandboxHandle"]
