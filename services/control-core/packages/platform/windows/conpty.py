"""P3.10B: real, task-scoped Windows ConPTY sessions.

The manager combines the native ConPTY API with the P3.9 isolation broker and
the existing Windows Job Object sandbox. A child is created suspended with both
the pseudo-console and AppContainer security attributes, assigned to its Job,
verified, and only then resumed.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from packages.platform.shared.contracts import SandboxProfile
from packages.platform.shared.errors import (
    CapabilityUnavailable,
    PermissionDenied,
    SandboxUnavailable,
)
from packages.platform.shared.terminal import (
    TERMINAL_PROTOCOL_VERSION,
    TerminalMessage,
    TerminalMessageType,
    TerminalOpenSpec,
    TerminalReadResult,
    TerminalSession,
    TerminalSessionProvider,
    TerminalSessionState,
    TerminalSignal,
)

from .isolation import WindowsIsolationBroker, create_default_isolation
from .process_sandbox import (
    _PROCESS_INFORMATION,
    _SECURITY_ATTRIBUTES,
    _SECURITY_CAPABILITIES,
    _STARTUPINFOEXW,
    CREATE_NEW_PROCESS_GROUP,
    CREATE_SUSPENDED,
    CREATE_UNICODE_ENVIRONMENT,
    EXTENDED_STARTUPINFO_PRESENT,
    HANDLE_FLAG_INHERIT,
    PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
    STARTF_USESTDHANDLES,
    WindowsProcessSandbox,
    WindowsSandboxHandle,
    _handle_value,
    _RestrictedProcess,
    _win_error,
)

logger = logging.getLogger(__name__)

TERMINAL_SESSION_VERSION = TERMINAL_PROTOCOL_VERSION
SessionState = TerminalSessionState
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
PSEUDOCONSOLE_INHERIT_CURSOR = 0x1
_MAX_READ_BYTES = 1024 * 1024
_OUTPUT_CHUNK_SIZE = 8192
_FINAL_STATES = frozenset(
    {
        TerminalSessionState.EXITED,
        TerminalSessionState.CLOSED,
        TerminalSessionState.TIMEOUT,
        TerminalSessionState.CANCELLED,
        TerminalSessionState.OUTPUT_LIMIT,
        TerminalSessionState.ERROR,
    }
)


class _COORD(ctypes.Structure):  # noqa: N801 - Win32 ABI name
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


@dataclass(slots=True, frozen=True)
class ResizeRequest:
    """Validated terminal resize request."""

    cols: int
    rows: int

    def __post_init__(self) -> None:
        if not 1 <= self.cols <= 500:
            raise ValueError(f"cols must be 1-500, got {self.cols}")
        if not 1 <= self.rows <= 200:
            raise ValueError(f"rows must be 1-200, got {self.rows}")


class ConPTYNotImplemented(CapabilityUnavailable):
    """Compatibility error retained for hosts without the ConPTY API."""

    def __init__(self, reason: str = "CreatePseudoConsole is unavailable") -> None:
        super().__init__("terminal_session", reason)


@dataclass(slots=True)
class _NativeConPTY:
    process: _RestrictedProcess
    pseudo_console_handle: int
    input_stream: BinaryIO
    output_stream: BinaryIO
    stderr_stream: BinaryIO


@dataclass(slots=True)
class _SessionRecord:
    session_id: str
    owner_principal_id: str
    workspace_id: str
    requested_executable: str
    args: tuple[str, ...]
    spec: TerminalOpenSpec
    sandbox: WindowsProcessSandbox
    sandbox_handle: WindowsSandboxHandle
    broker: WindowsIsolationBroker
    native: _NativeConPTY
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    state: TerminalSessionState = TerminalSessionState.CREATED
    exit_code: int | None = None
    cols: int = 80
    rows: int = 24
    output_bytes: int = 0
    output_truncated: bool = False
    connected: bool = True
    next_sequence: int = 1
    messages: deque[TerminalMessage] = field(default_factory=deque)
    condition: threading.Condition = field(
        default_factory=lambda: threading.Condition(threading.RLock()),
        repr=False,
    )
    reader_thread: threading.Thread | None = field(default=None, repr=False)
    watcher_thread: threading.Thread | None = field(default=None, repr=False)
    disconnect_timer: threading.Timer | None = field(default=None, repr=False)
    cleanup_started: bool = False
    cleanup_done: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def output_limit_bytes(self) -> int:
        return self.spec.output_size_limit_mb * 1024 * 1024

    def snapshot(self) -> TerminalSession:
        return TerminalSession(
            session_id=self.session_id,
            owner_principal_id=self.owner_principal_id,
            workspace_id=self.workspace_id,
            executable=self.requested_executable,
            args=self.args,
            created_at=self.created_at,
            updated_at=self.updated_at,
            state=self.state,
            exit_code=self.exit_code,
            cols=self.cols,
            rows=self.rows,
            output_truncated=self.output_truncated,
            resource_limits={
                "cpu_limit_cores": self.spec.cpu_limit_cores,
                "memory_limit_mb": self.spec.memory_limit_mb,
                "pids_limit": self.spec.pids_limit,
                "timeout_sec": self.spec.timeout_sec,
                "output_size_limit_mb": self.spec.output_size_limit_mb,
            },
            protocol_version=self.spec.protocol_version,
        )


def is_conpty_available() -> bool:
    """Return whether the required native ConPTY entry points exist."""

    if sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        return all(
            hasattr(kernel32, name)
            for name in (
                "CreatePseudoConsole",
                "ResizePseudoConsole",
                "ClosePseudoConsole",
            )
        )
    except Exception:
        return False


class WindowsConPTYManager(TerminalSessionProvider):
    """Own real ConPTY sessions and bind them to server-side task scope."""

    def __init__(
        self,
        *,
        disconnect_grace_sec: float = 30.0,
        max_active_sessions: int = 8,
        max_retained_sessions: int = 32,
    ) -> None:
        if disconnect_grace_sec <= 0:
            raise ValueError("disconnect_grace_sec must be positive")
        if max_active_sessions <= 0:
            raise ValueError("max_active_sessions must be positive")
        if max_retained_sessions < max_active_sessions:
            raise ValueError(
                "max_retained_sessions must be at least max_active_sessions"
            )
        self._disconnect_grace_sec = float(disconnect_grace_sec)
        self._max_active_sessions = int(max_active_sessions)
        self._max_retained_sessions = int(max_retained_sessions)
        self._sessions: dict[str, _SessionRecord] = {}
        self._pending_opens = 0
        self._sessions_lock = threading.RLock()

    @staticmethod
    def is_supported() -> bool:
        return is_conpty_available()

    @staticmethod
    def default_shell_executable() -> str:
        system_root = os.environ.get("SYSTEMROOT")
        if not system_root:
            raise SandboxUnavailable("SYSTEMROOT is unavailable")
        executable = Path(system_root) / "System32" / "cmd.exe"
        if not executable.is_file():
            raise SandboxUnavailable(f"Windows command shell is unavailable: {executable}")
        return str(executable.resolve(strict=True))

    @staticmethod
    def _canonical_path(path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    @classmethod
    def _path_is_inside(cls, root: str, path: str) -> bool:
        root_path = cls._canonical_path(root)
        candidate = cls._canonical_path(path)
        try:
            return os.path.commonpath((root_path, candidate)) == root_path
        except ValueError:
            return False

    @staticmethod
    def _conpty_kernel32() -> ctypes.WinDLL:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreatePseudoConsole.argtypes = [
            _COORD,
            wintypes.HANDLE,
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        kernel32.CreatePseudoConsole.restype = ctypes.c_long
        kernel32.ResizePseudoConsole.argtypes = [wintypes.HANDLE, _COORD]
        kernel32.ResizePseudoConsole.restype = ctypes.c_long
        kernel32.ClosePseudoConsole.argtypes = [wintypes.HANDLE]
        kernel32.ClosePseudoConsole.restype = None
        if hasattr(kernel32, "ReleasePseudoConsole"):
            kernel32.ReleasePseudoConsole.argtypes = [wintypes.HANDLE]
            kernel32.ReleasePseudoConsole.restype = ctypes.c_long
        return kernel32

    @staticmethod
    def _check_hresult(operation: str, result: int) -> None:
        if result == 0:
            return
        unsigned = ctypes.c_uint32(result).value
        raise SandboxUnavailable(f"{operation} failed with HRESULT 0x{unsigned:08X}")

    @staticmethod
    def _pipe_writer(handle: int) -> BinaryIO:
        import msvcrt

        flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
        fd = msvcrt.open_osfhandle(handle, flags)
        try:
            return os.fdopen(fd, "wb", buffering=0)
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _create_pty_pipe(
        kernel32: ctypes.WinDLL,
        *,
        host_reads: bool,
    ) -> tuple[int, int]:
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
            raise _win_error("CreatePipe(ConPTY)")
        read_value = _handle_value(read_handle)
        write_value = _handle_value(write_handle)
        host_handle = read_value if host_reads else write_value
        pseudo_handle = write_value if host_reads else read_value
        if not kernel32.SetHandleInformation(
            wintypes.HANDLE(host_handle),
            HANDLE_FLAG_INHERIT,
            0,
        ):
            kernel32.CloseHandle(wintypes.HANDLE(read_value))
            kernel32.CloseHandle(wintypes.HANDLE(write_value))
            raise _win_error("SetHandleInformation(ConPTY host pipe)")
        return host_handle, pseudo_handle

    @staticmethod
    def _create_attribute_list(
        kernel32: ctypes.WinDLL,
        *,
        pseudo_console_handle: int,
        appcontainer_sid_pointer: int,
    ) -> tuple[ctypes.Array[ctypes.c_char], _SECURITY_CAPABILITIES]:
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
            raise _win_error("InitializeProcThreadAttributeList(ConPTY)")

        if not kernel32.UpdateProcThreadAttribute(
            ctypes.cast(buffer, wintypes.LPVOID),
            0,
            PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
            wintypes.LPVOID(pseudo_console_handle),
            ctypes.sizeof(wintypes.HANDLE),
            None,
            None,
        ):
            kernel32.DeleteProcThreadAttributeList(ctypes.cast(buffer, wintypes.LPVOID))
            raise _win_error("UpdateProcThreadAttribute(pseudoconsole)")

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
            kernel32.DeleteProcThreadAttributeList(ctypes.cast(buffer, wintypes.LPVOID))
            raise _win_error("UpdateProcThreadAttribute(security capabilities)")
        return buffer, security_capabilities

    def _launch_native(
        self,
        sandbox: WindowsProcessSandbox,
        sandbox_handle: WindowsSandboxHandle,
        executable: str,
        args: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str],
        cols: int,
        rows: int,
    ) -> _NativeConPTY:
        launch_context = sandbox._isolation_launch_context(sandbox_handle.profile)
        pipe_kernel32 = sandbox._extended_process_apis()
        conpty_kernel32 = self._conpty_kernel32()
        advapi32 = sandbox._advapi32()
        handles_to_close: set[int] = set()
        attribute_buffer: ctypes.Array[ctypes.c_char] | None = None
        process_info = _PROCESS_INFORMATION()
        pseudo_console_handle = 0
        input_stream: BinaryIO | None = None
        output_stream: BinaryIO | None = None
        stderr_stream: BinaryIO | None = None
        process: _RestrictedProcess | None = None
        try:
            input_host, input_pseudo = self._create_pty_pipe(
                pipe_kernel32,
                host_reads=False,
            )
            output_host, output_pseudo = self._create_pty_pipe(
                pipe_kernel32,
                host_reads=True,
            )
            handles_to_close.update(
                (input_host, input_pseudo, output_host, output_pseudo)
            )

            pseudo_console = wintypes.HANDLE()
            result = conpty_kernel32.CreatePseudoConsole(
                _COORD(cols, rows),
                wintypes.HANDLE(input_pseudo),
                wintypes.HANDLE(output_pseudo),
                0,
                ctypes.byref(pseudo_console),
            )
            self._check_hresult("CreatePseudoConsole", result)
            pseudo_console_handle = _handle_value(pseudo_console)
            if not pseudo_console_handle:
                raise SandboxUnavailable("CreatePseudoConsole returned an empty handle")

            for pseudo_side in (input_pseudo, output_pseudo):
                pipe_kernel32.CloseHandle(wintypes.HANDLE(pseudo_side))
                handles_to_close.discard(pseudo_side)

            attribute_buffer, _security_capabilities = self._create_attribute_list(
                pipe_kernel32,
                pseudo_console_handle=pseudo_console_handle,
                appcontainer_sid_pointer=launch_context.appcontainer_sid_pointer,
            )
            startup = _STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
            # Prevent redirected parent std handles from bypassing ConPTY.
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            startup.lpAttributeList = ctypes.cast(attribute_buffer, wintypes.LPVOID)
            command_line = ctypes.create_unicode_buffer(
                subprocess.list2cmdline([executable, *list(args)])
            )
            environment = sandbox._environment_block(env)
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
                False,
                creation_flags,
                ctypes.cast(environment, wintypes.LPVOID),
                cwd,
                ctypes.byref(startup.StartupInfo),
                ctypes.byref(process_info),
            ):
                raise _win_error("CreateProcessAsUserW(ConPTY)")

            input_stream = self._pipe_writer(input_host)
            handles_to_close.discard(input_host)
            output_stream = sandbox._pipe_reader(output_host)
            handles_to_close.discard(output_host)
            stderr_stream = open(os.devnull, "rb")
            process = _RestrictedProcess(
                process_handle=_handle_value(process_info.hProcess),
                thread_handle=_handle_value(process_info.hThread),
                pid=int(process_info.dwProcessId),
                stdout=output_stream,
                stderr=stderr_stream,
            )
            sandbox_handle.pid = process.pid
            sandbox._assign_process(sandbox_handle, process)
            sandbox._verify_child_isolation_token(process)
            process.resume()
            process_info.hProcess = None
            process_info.hThread = None
            return _NativeConPTY(
                process=process,
                pseudo_console_handle=pseudo_console_handle,
                input_stream=input_stream,
                output_stream=output_stream,
                stderr_stream=stderr_stream,
            )
        except Exception:
            if process is not None:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except Exception:
                    logger.debug("Could not terminate failed ConPTY process", exc_info=True)
                process.close_native_handles()
            elif process_info.hProcess:
                failed_process = _RestrictedProcess(
                    process_handle=_handle_value(process_info.hProcess),
                    thread_handle=_handle_value(process_info.hThread),
                    pid=int(process_info.dwProcessId),
                    stdout=output_stream or open(os.devnull, "rb"),
                    stderr=stderr_stream or open(os.devnull, "rb"),
                )
                try:
                    failed_process.kill()
                    failed_process.wait(timeout=5)
                except Exception:
                    logger.debug("Could not terminate failed ConPTY launch", exc_info=True)
                finally:
                    failed_process.close_native_handles()
            for stream in (input_stream, output_stream, stderr_stream):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
            if pseudo_console_handle:
                try:
                    conpty_kernel32.ClosePseudoConsole(
                        wintypes.HANDLE(pseudo_console_handle)
                    )
                except Exception:
                    logger.debug("Could not close failed pseudo console", exc_info=True)
            raise
        finally:
            if attribute_buffer is not None:
                pipe_kernel32.DeleteProcThreadAttributeList(
                    ctypes.cast(attribute_buffer, wintypes.LPVOID)
                )
            for handle in handles_to_close:
                pipe_kernel32.CloseHandle(wintypes.HANDLE(handle))

    def _validate_open_spec(
        self,
        spec: TerminalOpenSpec,
        workspace_root: str,
    ) -> tuple[str, str]:
        if not isinstance(spec, TerminalOpenSpec):
            raise TypeError("spec must be a TerminalOpenSpec")
        workspace = str(Path(workspace_root).resolve(strict=True))
        cwd = str(Path(spec.cwd).resolve(strict=True))
        if not Path(cwd).is_dir():
            raise SandboxUnavailable(f"terminal cwd is not a directory: {cwd}")
        if not self._path_is_inside(workspace, cwd):
            raise PermissionDenied("terminal cwd must stay inside the task workspace")

        executable = str(Path(spec.executable).resolve(strict=True))
        if not Path(executable).is_file():
            raise SandboxUnavailable(f"terminal executable does not exist: {executable}")
        inside_workspace = self._path_is_inside(workspace, executable)
        is_trusted_shell = (
            self._canonical_path(executable)
            == self._canonical_path(self.default_shell_executable())
        )
        if not inside_workspace and not is_trusted_shell:
            raise PermissionDenied(
                "terminal executable must be inside the task workspace or the "
                "trusted Windows command shell"
            )
        return workspace, cwd

    @staticmethod
    def _append_message_locked(
        record: _SessionRecord,
        message_type: TerminalMessageType,
        payload: bytes,
    ) -> None:
        record.messages.append(
            TerminalMessage(
                message_type=message_type,
                payload=bytes(payload),
                sequence=record.next_sequence,
            )
        )
        record.next_sequence += 1
        record.updated_at = time.time()
        record.condition.notify_all()

    def _append_output(self, record: _SessionRecord, chunk: bytes) -> bool:
        terminate = False
        with record.condition:
            remaining = record.output_limit_bytes - record.output_bytes
            accepted = chunk[: max(0, remaining)]
            for offset in range(0, len(accepted), _OUTPUT_CHUNK_SIZE):
                part = accepted[offset : offset + _OUTPUT_CHUNK_SIZE]
                self._append_message_locked(
                    record,
                    TerminalMessageType.OUTPUT,
                    part,
                )
            record.output_bytes += len(accepted)
            if len(accepted) < len(chunk):
                record.output_truncated = True
                record.state = TerminalSessionState.OUTPUT_LIMIT
                self._append_message_locked(
                    record,
                    TerminalMessageType.ERROR,
                    b"terminal output limit exceeded",
                )
                terminate = True
        return terminate

    def _reader_main(self, record: _SessionRecord) -> None:
        try:
            while True:
                chunk = record.native.output_stream.read(64 * 1024)
                if not chunk:
                    break
                if self._append_output(record, bytes(chunk)):
                    self._request_termination(record)
                    break
        except Exception as exc:
            with record.condition:
                if record.state not in _FINAL_STATES:
                    record.state = TerminalSessionState.ERROR
                    self._append_message_locked(
                        record,
                        TerminalMessageType.ERROR,
                        f"terminal output reader failed: {exc}".encode(
                            "utf-8", errors="replace"
                        ),
                    )
        finally:
            with record.condition:
                record.condition.notify_all()

    def _request_termination(self, record: _SessionRecord) -> None:
        try:
            record.sandbox._terminate_job(record.sandbox_handle)
        except Exception:
            logger.debug("Job termination failed for terminal session", exc_info=True)
            try:
                record.native.process.kill()
            except Exception:
                logger.debug("Process termination fallback failed", exc_info=True)

    def _release_pseudoconsole(self, record: _SessionRecord) -> bool:
        handle = record.native.pseudo_console_handle
        if not handle:
            return False
        kernel32 = self._conpty_kernel32()
        try:
            release = getattr(kernel32, "ReleasePseudoConsole", None)
            if release is None:
                return False
            result = release(wintypes.HANDLE(handle))
            if result != 0:
                logger.debug(
                    "ReleasePseudoConsole returned HRESULT 0x%08X",
                    ctypes.c_uint32(result).value,
                )
                return False
            return True
        except Exception:
            logger.debug("ReleasePseudoConsole failed", exc_info=True)
            return False

    def _close_pseudoconsole(self, record: _SessionRecord) -> None:
        handle = record.native.pseudo_console_handle
        if not handle:
            return
        kernel32 = self._conpty_kernel32()
        try:
            kernel32.ClosePseudoConsole(wintypes.HANDLE(handle))
        finally:
            record.native.pseudo_console_handle = 0

    def _cleanup_record(self, record: _SessionRecord) -> None:
        with record.condition:
            if record.cleanup_started:
                return
            record.cleanup_started = True
            timer = record.disconnect_timer
            record.disconnect_timer = None
        if timer is not None:
            timer.cancel()

        try:
            self._request_termination(record)
            try:
                record.native.input_stream.close()
            except Exception:
                pass
            released = self._release_pseudoconsole(record)
            reader = record.reader_thread
            if released and reader is not None and reader is not threading.current_thread():
                reader.join(timeout=5)
            try:
                self._close_pseudoconsole(record)
            except Exception:
                logger.debug("Pseudo console close failed", exc_info=True)
            if reader is not None and reader is not threading.current_thread():
                reader.join(timeout=5)
            for stream in (record.native.output_stream, record.native.stderr_stream):
                try:
                    stream.close()
                except Exception:
                    pass
            record.native.process.close_native_handles()
            try:
                asyncio.run(record.sandbox.kill_tree(record.sandbox_handle))
            except Exception:
                logger.debug("Terminal sandbox cleanup failed", exc_info=True)
            try:
                record.broker.close()
            except Exception:
                logger.debug("Terminal isolation cleanup failed", exc_info=True)
        finally:
            record.cleanup_done.set()
            with record.condition:
                record.condition.notify_all()

    def _watcher_main(self, record: _SessionRecord) -> None:
        try:
            record.native.process.wait(timeout=record.spec.timeout_sec)
        except subprocess.TimeoutExpired:
            with record.condition:
                if record.state not in _FINAL_STATES:
                    record.state = TerminalSessionState.TIMEOUT
                    self._append_message_locked(
                        record,
                        TerminalMessageType.ERROR,
                        f"terminal timed out after {record.spec.timeout_sec:g}s".encode(),
                    )
            self._request_termination(record)
            try:
                record.native.process.wait(timeout=5)
            except Exception:
                pass
        except Exception as exc:
            with record.condition:
                if record.state not in _FINAL_STATES:
                    record.state = TerminalSessionState.ERROR
                    self._append_message_locked(
                        record,
                        TerminalMessageType.ERROR,
                        f"terminal process wait failed: {exc}".encode(
                            "utf-8", errors="replace"
                        ),
                    )
        finally:
            with record.condition:
                record.exit_code = record.native.process.returncode
                if record.state not in _FINAL_STATES:
                    record.state = TerminalSessionState.EXITED
                record.updated_at = time.time()
                record.condition.notify_all()
            self._cleanup_record(record)

    def _get_record(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> _SessionRecord:
        if not session_id:
            raise ValueError("session_id must be non-empty")
        with self._sessions_lock:
            record = self._sessions.get(session_id)
        if record is None:
            raise SandboxUnavailable("terminal session not found")
        if (
            record.owner_principal_id != owner_principal_id
            or record.workspace_id != workspace_id
        ):
            raise PermissionDenied("terminal session scope mismatch")
        return record

    def _disconnect_expired(self, record: _SessionRecord) -> None:
        with record.condition:
            if record.state != TerminalSessionState.DISCONNECTED or record.connected:
                return
            record.state = TerminalSessionState.CLOSED
            self._append_message_locked(
                record,
                TerminalMessageType.ERROR,
                b"terminal disconnect grace period expired",
            )
        self._request_termination(record)

    def _prune_finished_locked(self) -> None:
        finished = sorted(
            (
                record
                for record in self._sessions.values()
                if record.cleanup_done.is_set()
            ),
            key=lambda record: record.updated_at,
        )
        while len(self._sessions) >= self._max_retained_sessions and finished:
            record = finished.pop(0)
            self._sessions.pop(record.session_id, None)

    async def open(
        self,
        spec: TerminalOpenSpec,
        *,
        owner_principal_id: str,
        workspace_id: str,
        workspace_root: str,
    ) -> TerminalSession:
        if not self.is_supported():
            raise ConPTYNotImplemented()
        if not owner_principal_id or not workspace_id:
            raise PermissionDenied("terminal owner and workspace scope are required")
        workspace, cwd = self._validate_open_spec(spec, workspace_root)
        with self._sessions_lock:
            self._prune_finished_locked()
            active = sum(
                1 for item in self._sessions.values() if not item.cleanup_done.is_set()
            )
            if active + self._pending_opens >= self._max_active_sessions:
                raise SandboxUnavailable("terminal active-session limit reached")
            self._pending_opens += 1

        broker: WindowsIsolationBroker | None = None
        sandbox: WindowsProcessSandbox | None = None
        sandbox_handle: WindowsSandboxHandle | None = None
        native: _NativeConPTY | None = None
        pending_open = True
        try:
            broker = create_default_isolation(workspace)
            broker.initialize()
            sandbox = WindowsProcessSandbox(broker)
            profile = SandboxProfile(
                cpu_limit_cores=spec.cpu_limit_cores,
                memory_limit_mb=spec.memory_limit_mb,
                pids_limit=spec.pids_limit,
                exec_timeout_sec=max(1, math.ceil(spec.timeout_sec)),
                output_size_limit_mb=spec.output_size_limit_mb,
            )
            sandbox_handle = await sandbox.create(profile)
            filtered_env = broker.filter_environment(spec.env_dict)
            native = await asyncio.to_thread(
                self._launch_native,
                sandbox,
                sandbox_handle,
                spec.executable,
                spec.args,
                cwd=cwd,
                env=filtered_env,
                cols=spec.cols,
                rows=spec.rows,
            )
            record = _SessionRecord(
                session_id=uuid.uuid4().hex,
                owner_principal_id=owner_principal_id,
                workspace_id=workspace_id,
                requested_executable=spec.executable,
                args=spec.args,
                spec=spec,
                sandbox=sandbox,
                sandbox_handle=sandbox_handle,
                broker=broker,
                native=native,
                state=TerminalSessionState.RUNNING,
                cols=spec.cols,
                rows=spec.rows,
            )
            with record.condition:
                self._append_message_locked(
                    record,
                    TerminalMessageType.HEARTBEAT,
                    b"terminal session opened",
                )
            record.reader_thread = threading.Thread(
                target=self._reader_main,
                args=(record,),
                name=f"conpty-output-{record.session_id[:8]}",
                daemon=True,
            )
            record.watcher_thread = threading.Thread(
                target=self._watcher_main,
                args=(record,),
                name=f"conpty-watch-{record.session_id[:8]}",
                daemon=True,
            )
            record.reader_thread.start()
            record.watcher_thread.start()
            with self._sessions_lock:
                self._sessions[record.session_id] = record
                self._pending_opens -= 1
                pending_open = False
            return record.snapshot()
        except Exception:
            if native is not None:
                try:
                    native.process.kill()
                except Exception:
                    pass
                for stream in (
                    native.input_stream,
                    native.output_stream,
                    native.stderr_stream,
                ):
                    try:
                        stream.close()
                    except Exception:
                        pass
                native.process.close_native_handles()
            if sandbox_handle is not None and sandbox is not None:
                try:
                    await sandbox.kill_tree(sandbox_handle)
                except Exception:
                    logger.debug("Failed terminal-open sandbox cleanup", exc_info=True)
            if broker is not None:
                try:
                    broker.close()
                except Exception:
                    logger.debug("Failed terminal-open broker cleanup", exc_info=True)
            raise
        finally:
            if pending_open:
                with self._sessions_lock:
                    self._pending_opens -= 1

    async def write(
        self,
        session_id: str,
        data: bytes,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession:
        if not isinstance(data, bytes) or not data:
            raise ValueError("terminal input must be non-empty bytes")
        record = self._get_record(
            session_id,
            owner_principal_id=owner_principal_id,
            workspace_id=workspace_id,
        )
        with record.condition:
            if record.state in _FINAL_STATES:
                raise SandboxUnavailable("terminal session is no longer writable")
        try:
            await asyncio.to_thread(record.native.input_stream.write, data)
            await asyncio.to_thread(record.native.input_stream.flush)
        except Exception as exc:
            raise SandboxUnavailable(f"terminal input write failed: {exc}") from exc
        with record.condition:
            self._append_message_locked(
                record,
                TerminalMessageType.INPUT,
                json.dumps({"bytes": len(data)}, separators=(",", ":")).encode(),
            )
            return record.snapshot()

    async def read(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
        after_sequence: int = 0,
        max_bytes: int = 64 * 1024,
        timeout_sec: float = 1.0,
    ) -> TerminalReadResult:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if not _OUTPUT_CHUNK_SIZE <= max_bytes <= _MAX_READ_BYTES:
            raise ValueError(
                f"max_bytes must be {_OUTPUT_CHUNK_SIZE}-{_MAX_READ_BYTES}"
            )
        if timeout_sec < 0 or not math.isfinite(timeout_sec):
            raise ValueError("timeout_sec must be a finite non-negative number")
        record = self._get_record(
            session_id,
            owner_principal_id=owner_principal_id,
            workspace_id=workspace_id,
        )

        def collect() -> TerminalReadResult:
            deadline = time.monotonic() + timeout_sec
            with record.condition:
                while True:
                    available = [
                        message
                        for message in record.messages
                        if message.sequence > after_sequence
                    ]
                    if available or record.state in _FINAL_STATES or timeout_sec == 0:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    record.condition.wait(timeout=remaining)

                selected: list[TerminalMessage] = []
                size = 0
                for message in available:
                    payload_size = len(message.payload)
                    if selected and size + payload_size > max_bytes:
                        break
                    if not selected and payload_size > max_bytes:
                        selected.append(
                            TerminalMessage(
                                message_type=message.message_type,
                                payload=message.payload[:max_bytes],
                                sequence=message.sequence,
                                timestamp=message.timestamp,
                            )
                        )
                        break
                    selected.append(message)
                    size += payload_size
                next_sequence = (
                    selected[-1].sequence if selected else after_sequence
                )
                return TerminalReadResult(
                    session=record.snapshot(),
                    messages=tuple(selected),
                    next_sequence=next_sequence,
                )

        return await asyncio.to_thread(collect)

    async def resize(
        self,
        session_id: str,
        cols: int,
        rows: int,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession:
        request = ResizeRequest(cols=cols, rows=rows)
        record = self._get_record(
            session_id,
            owner_principal_id=owner_principal_id,
            workspace_id=workspace_id,
        )
        with record.condition:
            if record.state in _FINAL_STATES:
                raise SandboxUnavailable("terminal session is no longer resizable")
            handle = record.native.pseudo_console_handle
        result = await asyncio.to_thread(
            self._conpty_kernel32().ResizePseudoConsole,
            wintypes.HANDLE(handle),
            _COORD(request.cols, request.rows),
        )
        self._check_hresult("ResizePseudoConsole", result)
        with record.condition:
            record.cols = request.cols
            record.rows = request.rows
            record.state = TerminalSessionState.RESIZED
            self._append_message_locked(
                record,
                TerminalMessageType.RESIZE,
                json.dumps(
                    {"cols": request.cols, "rows": request.rows},
                    separators=(",", ":"),
                ).encode(),
            )
            return record.snapshot()

    async def signal(
        self,
        session_id: str,
        signal: TerminalSignal,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession:
        if not isinstance(signal, TerminalSignal):
            signal = TerminalSignal(signal)
        record = self._get_record(
            session_id,
            owner_principal_id=owner_principal_id,
            workspace_id=workspace_id,
        )
        with record.condition:
            if record.state in _FINAL_STATES:
                raise SandboxUnavailable("terminal session is no longer running")
        if signal is TerminalSignal.CTRL_C:
            await asyncio.to_thread(record.native.input_stream.write, b"\x03")
            await asyncio.to_thread(record.native.input_stream.flush)
        elif signal is TerminalSignal.EOF:
            await asyncio.to_thread(record.native.input_stream.close)
        elif signal is TerminalSignal.TERMINATE:
            await asyncio.to_thread(self._request_termination, record)
        with record.condition:
            record.state = TerminalSessionState.SIGNALLED
            self._append_message_locked(
                record,
                TerminalMessageType.SIGNAL,
                signal.value.encode(),
            )
            return record.snapshot()

    async def attach(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession:
        record = self._get_record(
            session_id,
            owner_principal_id=owner_principal_id,
            workspace_id=workspace_id,
        )
        with record.condition:
            timer = record.disconnect_timer
            record.disconnect_timer = None
            record.connected = True
            if record.state == TerminalSessionState.DISCONNECTED:
                record.state = TerminalSessionState.RUNNING
            self._append_message_locked(
                record,
                TerminalMessageType.HEARTBEAT,
                b"terminal session attached",
            )
            snapshot = record.snapshot()
        if timer is not None:
            timer.cancel()
        return snapshot

    async def heartbeat(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession:
        record = self._get_record(
            session_id,
            owner_principal_id=owner_principal_id,
            workspace_id=workspace_id,
        )
        with record.condition:
            self._append_message_locked(
                record,
                TerminalMessageType.HEARTBEAT,
                b"heartbeat",
            )
            return record.snapshot()

    async def disconnect(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession:
        record = self._get_record(
            session_id,
            owner_principal_id=owner_principal_id,
            workspace_id=workspace_id,
        )
        with record.condition:
            if record.state in _FINAL_STATES:
                return record.snapshot()
            if record.disconnect_timer is not None:
                record.disconnect_timer.cancel()
            record.connected = False
            record.state = TerminalSessionState.DISCONNECTED
            self._append_message_locked(
                record,
                TerminalMessageType.HEARTBEAT,
                b"terminal session disconnected",
            )
            timer = threading.Timer(
                self._disconnect_grace_sec,
                self._disconnect_expired,
                args=(record,),
            )
            timer.daemon = True
            record.disconnect_timer = timer
            snapshot = record.snapshot()
        timer.start()
        return snapshot

    async def close(
        self,
        session_id: str,
        *,
        owner_principal_id: str,
        workspace_id: str,
    ) -> TerminalSession:
        record = self._get_record(
            session_id,
            owner_principal_id=owner_principal_id,
            workspace_id=workspace_id,
        )
        with record.condition:
            if record.state not in _FINAL_STATES:
                record.state = TerminalSessionState.CLOSED
                self._append_message_locked(
                    record,
                    TerminalMessageType.CLOSE,
                    b"terminal session closed",
                )
        await asyncio.to_thread(self._request_termination, record)
        await asyncio.to_thread(record.cleanup_done.wait, 10)
        with record.condition:
            snapshot = record.snapshot()
        with self._sessions_lock:
            self._sessions.pop(session_id, None)
        return snapshot


_DEFAULT_MANAGER: WindowsConPTYManager | None = None
_DEFAULT_MANAGER_LOCK = threading.Lock()


def get_default_conpty_manager() -> WindowsConPTYManager:
    """Return the process-wide manager used by registered terminal tools."""

    global _DEFAULT_MANAGER
    with _DEFAULT_MANAGER_LOCK:
        if _DEFAULT_MANAGER is None:
            _DEFAULT_MANAGER = WindowsConPTYManager()
        return _DEFAULT_MANAGER


__all__ = [
    "TERMINAL_SESSION_VERSION",
    "SessionState",
    "TerminalSession",
    "TerminalMessage",
    "TerminalMessageType",
    "TerminalOpenSpec",
    "TerminalReadResult",
    "TerminalSignal",
    "ResizeRequest",
    "ConPTYNotImplemented",
    "WindowsConPTYManager",
    "get_default_conpty_manager",
    "is_conpty_available",
]
