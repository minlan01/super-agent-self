"""Windows Named Pipe IPC with a current-user SID ACL (P1.5).

The implementation is intentionally Windows-only.  A pipe is created with a
protected DACL for the current user, and the connecting token is checked again
after connection.  The first message negotiates the schema and binds a nonce;
subsequent messages carry that nonce and a strictly increasing sequence number.
"""

from __future__ import annotations

import asyncio
import ctypes
import inspect
import json
import logging
import os
import secrets
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from packages.platform.shared.contracts import IpcEndpoint, LocalIpc
from packages.platform.shared.errors import CapabilityUnavailable, IpcAuthError, PlatformError
from packages.protocol.schemas.enums import SCHEMA_VERSION

from ._errors import IpcProtocolError, IpcRateLimitError, UnsupportedPlatformError

logger = logging.getLogger(__name__)

PIPE_NAME = r"\\.\pipe\zcode-control-core"
MAX_MESSAGE_SIZE = 10 * 1024 * 1024
RATE_LIMIT_PER_SEC = 100
RATE_LIMIT_WINDOW = 1.0
ERROR_PIPE_CONNECTED = 535
ERROR_PIPE_LISTENING = 536
ERROR_MORE_DATA = 234
ERROR_NO_DATA = 232
ERROR_OPERATION_ABORTED = 995
THREAD_TERMINATE = 0x0001


@dataclass(frozen=True, slots=True)
class IpcHandshake:
    protocol_version: str
    nonce: str
    peer_sid: str | None
    peer_pid: int | None
    max_message_size: int = MAX_MESSAGE_SIZE


def _win32_error_code(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    if isinstance(value, int):
        return value
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def _endpoint_address(endpoint: IpcEndpoint | str | None) -> tuple[str | None, str | None]:
    """Return ``(address, peer_sid)`` while accepting the old spike string."""

    if endpoint is None:
        return None, None
    if isinstance(endpoint, str):
        return endpoint, None
    address = getattr(endpoint, "address", None)
    if not isinstance(address, str):
        raise TypeError("endpoint must be an IpcEndpoint or Named Pipe path")
    transport = getattr(endpoint, "transport", None)
    if transport not in (None, "named_pipe"):
        raise ValueError("WindowsNamedPipeIpc requires a named_pipe endpoint")
    return address, getattr(endpoint, "peer_sid", None)


def _encode_frame(value: Mapping[str, Any]) -> bytes:
    if not isinstance(value, Mapping):
        raise IpcProtocolError("IPC frame must be a JSON object")
    try:
        data = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IpcProtocolError("IPC frame is not JSON serializable") from exc
    if len(data) > MAX_MESSAGE_SIZE:
        raise IpcProtocolError(f"IPC frame exceeds {MAX_MESSAGE_SIZE} bytes")
    return data


def _decode_frame(data: bytes | bytearray | memoryview) -> dict[str, Any]:
    raw = bytes(data)
    if len(raw) > MAX_MESSAGE_SIZE:
        raise IpcProtocolError(f"IPC frame exceeds {MAX_MESSAGE_SIZE} bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IpcProtocolError("IPC frame is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise IpcProtocolError("IPC frame must be a JSON object")
    return value


def _validate_handshake(
    value: Mapping[str, Any], *, expected_nonce: str | None = None
) -> dict[str, Any]:
    if value.get("protocol_version") != SCHEMA_VERSION:
        raise IpcAuthError(
            f"protocol version mismatch: got {value.get('protocol_version')!r}, "
            f"expected {SCHEMA_VERSION!r}"
        )
    nonce = value.get("nonce")
    if not isinstance(nonce, str) or not nonce or len(nonce) > 256:
        raise IpcAuthError("handshake nonce is missing or invalid")
    if expected_nonce is not None and nonce != expected_nonce:
        raise IpcAuthError("handshake nonce mismatch")
    max_size = value.get("max_message_size", MAX_MESSAGE_SIZE)
    if not isinstance(max_size, int) or isinstance(max_size, bool):
        raise IpcProtocolError("invalid handshake max_message_size")
    if max_size <= 0 or max_size > MAX_MESSAGE_SIZE:
        raise IpcProtocolError("invalid handshake max_message_size")
    return {
        "protocol_version": SCHEMA_VERSION,
        "nonce": nonce,
        "max_message_size": max_size,
    }


def _validate_request(value: Mapping[str, Any], *, nonce: str, last_seq: int) -> int:
    if value.get("nonce") != nonce:
        raise IpcAuthError("request nonce mismatch")
    seq = value.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq != last_seq + 1:
        raise IpcAuthError("request sequence is missing, replayed, or out of order")
    return seq


# Keep the framing helpers available to the Rust/Python smoke clients without
# exposing the platform-independent protocol module to Windows-only details.
encode_frame = _encode_frame
decode_frame = _decode_frame
validate_handshake = _validate_handshake
validate_request = _validate_request


class WindowsNamedPipeIpc(LocalIpc):
    """Single-user Named Pipe server used by control-core."""

    def __init__(
        self,
        pipe_name: str = PIPE_NAME,
        *,
        nonce: str | None = None,
        expected_sid: str | None = None,
        max_message_size: int = MAX_MESSAGE_SIZE,
        rate_limit_per_sec: int = RATE_LIMIT_PER_SEC,
        rate_limit_window: float = RATE_LIMIT_WINDOW,
        allow_unknown_peer: bool = False,
        max_instances: int = 1,
    ) -> None:
        if not pipe_name.startswith("\\\\.\\pipe\\"):
            raise ValueError(r"pipe_name must be a local \\.\pipe\ path")
        if not 1 <= max_message_size <= MAX_MESSAGE_SIZE:
            raise ValueError(f"max_message_size must be 1..{MAX_MESSAGE_SIZE}")
        if rate_limit_per_sec <= 0 or rate_limit_window <= 0:
            raise ValueError("rate limit values must be positive")
        if not 1 <= max_instances <= 255:
            raise ValueError("max_instances must be between 1 and 255")
        if allow_unknown_peer:
            raise ValueError("allow_unknown_peer is unsafe; peer identity is fail-closed")
        if expected_sid is not None and (
            not isinstance(expected_sid, str) or not expected_sid
        ):
            raise ValueError("expected_sid must be a non-empty SID string")
        if nonce is not None and (
            not isinstance(nonce, str) or not nonce or len(nonce) > 256
        ):
            raise ValueError("nonce must be a non-empty string of at most 256 characters")
        self.pipe_name = pipe_name
        self.nonce = nonce or secrets.token_urlsafe(32)
        self.expected_sid = expected_sid
        self.max_message_size = max_message_size
        self.rate_limit_per_sec = rate_limit_per_sec
        self.rate_limit_window = rate_limit_window
        self.max_instances = max_instances
        self._stop = threading.Event()
        self._listener_lock = threading.Lock()
        self._listen_handle: Any | None = None
        self._connection_threads: set[threading.Thread] = set()
        self._connection_handles: set[Any] = set()
        self._event_loop: asyncio.AbstractEventLoop | None = None

    @staticmethod
    def is_supported() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import win32file  # noqa: F401
            import win32pipe  # noqa: F401
            import win32security  # noqa: F401
        except ImportError:
            return False
        return True

    def _require_windows(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedPlatformError("Windows Named Pipe IPC requires Windows")
        if not self.is_supported():
            raise UnsupportedPlatformError("Windows Named Pipe IPC requires pywin32")

    @staticmethod
    def _process_handle() -> Any:
        import win32api

        return win32api.GetCurrentProcess()

    @classmethod
    def _current_user_sid(cls) -> str:
        import win32security

        token = win32security.OpenProcessToken(
            cls._process_handle(), win32security.TOKEN_QUERY
        )
        try:
            sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
            return win32security.ConvertSidToStringSid(sid)
        finally:
            close = getattr(token, "Close", None)
            if close:
                close()

    def _build_security_attributes_raw(self) -> Any:
        """Build a protected DACL that grants only the expected user SID."""

        self._require_windows()
        import ntsecuritycon
        import win32security

        try:
            import pywintypes

            sa_type = pywintypes.SECURITY_ATTRIBUTES
        except (ImportError, AttributeError):
            sa_type = getattr(win32security, "SECURITY_ATTRIBUTES", None)
        if sa_type is None:
            raise PlatformError("pywin32 does not expose SECURITY_ATTRIBUTES")

        current_sid = self._current_user_sid()
        if self.expected_sid and self.expected_sid.casefold() != current_sid.casefold():
            raise IpcAuthError(
                "expected_sid must match the current process SID; "
                "Named Pipe DACLs cannot grant another local user"
            )
        # The DACL is always derived from the current token.  ``expected_sid``
        # is a peer assertion, never an authority to grant access.
        sid = win32security.ConvertStringSidToSid(current_sid)
        dacl = win32security.ACL()
        access = (
            ntsecuritycon.GENERIC_READ
            | ntsecuritycon.GENERIC_WRITE
            | getattr(ntsecuritycon, "SYNCHRONIZE", 0x00100000)
        )
        dacl.AddAccessAllowedAce(win32security.ACL_REVISION, access, sid)
        sd = win32security.SECURITY_DESCRIPTOR()
        sd.SetSecurityDescriptorOwner(sid, False)
        sd.SetSecurityDescriptorDacl(1, dacl, 0)
        protected = getattr(win32security, "SE_DACL_PROTECTED", 0x1000)
        set_control = getattr(sd, "SetSecurityDescriptorControl", None)
        if set_control is None:
            raise PlatformError("pywin32 cannot protect the Named Pipe DACL")
        try:
            set_control(protected, protected)
        except Exception as exc:
            raise PlatformError("could not protect the Named Pipe DACL") from exc
        sa = sa_type()
        sa.SECURITY_DESCRIPTOR = sd
        sa.bInheritHandle = False
        return sa

    def _peer_identity(self, handle: Any) -> tuple[str | None, int | None]:
        self._require_windows()
        import win32pipe
        import win32security

        pid: int | None = None
        get_pid = getattr(win32pipe, "GetNamedPipeClientProcessId", None)
        if get_pid is not None:
            try:
                pid = int(get_pid(handle))
            except Exception:
                logger.debug("Could not query Named Pipe client PID", exc_info=True)

        sid_text: str | None = None
        impersonated = False
        try:
            win32pipe.ImpersonateNamedPipeClient(handle)
            impersonated = True
            token = win32security.OpenThreadToken(
                self._thread_handle(), win32security.TOKEN_QUERY, True
            )
            try:
                sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
                sid_text = win32security.ConvertSidToStringSid(sid)
            finally:
                close = getattr(token, "Close", None)
                if close:
                    close()
        except Exception:
            logger.debug("Named Pipe client impersonation failed", exc_info=True)
        finally:
            if impersonated:
                try:
                    win32security.RevertToSelf()
                except Exception:
                    logger.debug("Could not revert Named Pipe impersonation", exc_info=True)

        if sid_text is None and pid is not None:
            try:
                import win32api
                import win32con

                access = getattr(win32con, "PROCESS_QUERY_LIMITED_INFORMATION", 0x1000)
                process = win32api.OpenProcess(access, False, pid)
                token = win32security.OpenProcessToken(process, win32security.TOKEN_QUERY)
                try:
                    sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
                    sid_text = win32security.ConvertSidToStringSid(sid)
                finally:
                    for resource in (token, process):
                        close = getattr(resource, "Close", None)
                        if close:
                            close()
            except Exception:
                logger.debug("Could not query Named Pipe client token", exc_info=True)
        return sid_text, pid

    @staticmethod
    def _thread_handle() -> Any:
        import win32api

        return win32api.GetCurrentThread()

    @staticmethod
    def _cancel_synchronous_io(thread: threading.Thread) -> None:
        """Cancel a client's pending ReadFile from the stopping thread."""

        native_id = thread.native_id
        if native_id is None or sys.platform != "win32":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenThread.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenThread.restype = ctypes.c_void_p
        kernel32.CancelSynchronousIo.argtypes = [ctypes.c_void_p]
        kernel32.CancelSynchronousIo.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        thread_handle = kernel32.OpenThread(THREAD_TERMINATE, 0, native_id)
        if not thread_handle:
            logger.debug("Could not open pipe client thread for cancellation")
            return
        try:
            if not kernel32.CancelSynchronousIo(thread_handle):
                error = ctypes.get_last_error()
                # ERROR_NOT_FOUND means the thread is not currently blocked.
                if error != 1168:
                    logger.debug("CancelSynchronousIo failed with winerror=%s", error)
        finally:
            kernel32.CloseHandle(thread_handle)

    def verify_peer(self, conn: Any, expected_sid: str | None = None) -> bool:
        sid, _pid = self._peer_identity(conn)
        expected = expected_sid or self.expected_sid or self._current_user_sid()
        if sid is None:
            return False
        return sid.casefold() == expected.casefold()

    @staticmethod
    def _read_message(handle: Any, limit: int) -> bytes:
        import pywintypes
        import win32file

        chunks: list[bytes] = []
        total = 0
        chunk_size = min(64 * 1024, limit)
        while True:
            try:
                status, data = win32file.ReadFile(handle, chunk_size)
            except pywintypes.error as exc:
                if _win32_error_code(exc) == ERROR_MORE_DATA:
                    raise IpcProtocolError("IPC message exceeds configured size") from exc
                raise
            piece = bytes(data)
            total += len(piece)
            if total > limit:
                raise IpcProtocolError("IPC message exceeds configured size")
            chunks.append(piece)
            if status != ERROR_MORE_DATA:
                return b"".join(chunks)

    @staticmethod
    def _write_message(handle: Any, value: Mapping[str, Any]) -> None:
        import win32file

        win32file.WriteFile(handle, _encode_frame(value))

    @staticmethod
    def _rate_check(
        timestamps: deque[float], *, now: float, limit: int, window: float
    ) -> None:
        while timestamps and now - timestamps[0] >= window:
            timestamps.popleft()
        if len(timestamps) >= limit:
            raise IpcRateLimitError("IPC request rate limit exceeded")
        timestamps.append(now)

    def _call_handler(
        self, handler: Callable[[dict[str, Any]], Any], request: dict[str, Any]
    ) -> Any:
        result = handler(request)
        if inspect.isawaitable(result):
            loop = self._event_loop
            if loop is None or not loop.is_running():
                raise PlatformError("IPC server event loop is unavailable")

            async def await_result() -> Any:
                return await result

            return asyncio.run_coroutine_threadsafe(await_result(), loop).result()
        return result

    def _handle_connection(self, handle: Any, handler: Callable[[dict[str, Any]], Any]) -> None:
        import win32file

        try:
            if not self.verify_peer(handle):
                raise IpcAuthError("Named Pipe peer SID is not the current user")
            handshake = _validate_handshake(
                _decode_frame(self._read_message(handle, self.max_message_size)),
                expected_nonce=self.nonce,
            )
            effective_limit = min(self.max_message_size, handshake["max_message_size"])
            self._write_message(
                handle,
                {
                    "ok": True,
                    "protocol_version": SCHEMA_VERSION,
                    "nonce": self.nonce,
                    "max_message_size": effective_limit,
                    "server_pid": os.getpid(),
                },
            )

            timestamps: deque[float] = deque()
            last_seq = 0
            while not self._stop.is_set():
                request = _decode_frame(self._read_message(handle, effective_limit))
                self._rate_check(
                    timestamps,
                    now=time.monotonic(),
                    limit=self.rate_limit_per_sec,
                    window=self.rate_limit_window,
                )
                last_seq = _validate_request(request, nonce=self.nonce, last_seq=last_seq)
                result = self._call_handler(handler, request)
                if not isinstance(result, Mapping):
                    raise IpcProtocolError("IPC handler must return a JSON object")
                response = dict(result)
                response.setdefault("ok", True)
                response.setdefault("seq", last_seq)
                self._write_message(handle, response)
        except (IpcAuthError, IpcProtocolError, IpcRateLimitError) as exc:
            logger.warning("IPC request rejected: %s", exc)
            try:
                self._write_message(handle, {"ok": False, "error": "request rejected"})
            except Exception:
                pass
        except Exception as exc:
            if self._stop.is_set() and _win32_error_code(exc) == ERROR_OPERATION_ABORTED:
                logger.debug("IPC connection cancelled during shutdown")
            else:
                logger.exception("IPC connection failed")
        finally:
            with self._listener_lock:
                self._connection_handles.discard(handle)
            if not self._stop.is_set():
                try:
                    win32file.FlushFileBuffers(handle)
                except Exception:
                    pass
                try:
                    win32file.DisconnectNamedPipe(handle)
                except Exception:
                    pass
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass
            with self._listener_lock:
                self._connection_threads.discard(threading.current_thread())

    def _serve_loop(self, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._require_windows()
        import pywintypes
        import win32file
        import win32pipe

        security_attributes = self._build_security_attributes_raw()
        logger.info("Named Pipe IPC listening on %s", self.pipe_name)
        while not self._stop.is_set():
            try:
                handle = win32pipe.CreateNamedPipe(
                    self.pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE
                    | win32pipe.PIPE_READMODE_MESSAGE
                    | getattr(win32pipe, "PIPE_NOWAIT", 1),
                    self.max_instances,
                    64 * 1024,
                    64 * 1024,
                    1000,
                    security_attributes,
                )
            except pywintypes.error as exc:
                if _win32_error_code(exc) == 231 and not self._stop.is_set():
                    self._stop.wait(0.05)
                    continue
                if self._stop.is_set() or _win32_error_code(exc) == ERROR_OPERATION_ABORTED:
                    break
                raise
            with self._listener_lock:
                self._listen_handle = handle
            try:
                connected = False
                while not self._stop.is_set():
                    try:
                        win32pipe.ConnectNamedPipe(handle, None)
                        connected = True
                        break
                    except pywintypes.error as exc:
                        code = _win32_error_code(exc)
                        if code == ERROR_PIPE_CONNECTED:
                            connected = True
                            break
                        if code in (ERROR_PIPE_LISTENING, ERROR_NO_DATA):
                            self._stop.wait(0.05)
                            continue
                        if code == ERROR_OPERATION_ABORTED or self._stop.is_set():
                            break
                        raise
                if not connected:
                    break
                if self._stop.is_set():
                    break
                # The accept handle is non-blocking only so stop() can poll
                # without a permanently blocked worker. Once connected,
                # switch the client handle back to blocking message reads.
                win32pipe.SetNamedPipeHandleState(
                    handle,
                    win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    None,
                    None,
                )
                thread = threading.Thread(
                    target=self._handle_connection,
                    args=(handle, handler),
                    name="p1-named-pipe-client",
                    daemon=True,
                )
                # Hold the same lock used by ``close`` while publishing and
                # starting the thread.  This prevents close() from observing
                # an unstarted thread and then losing it from the join set.
                with self._listener_lock:
                    self._connection_threads.add(thread)
                    self._connection_handles.add(handle)
                    thread.start()
                handle = None
            except Exception:
                logger.exception("Named Pipe accept failed")
            finally:
                with self._listener_lock:
                    self._listen_handle = None
                if handle is not None:
                    try:
                        win32file.CloseHandle(handle)
                    except Exception:
                        pass

    async def serve(
        self,
        endpoint: IpcEndpoint | str | None,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        address, peer_sid = _endpoint_address(endpoint)
        if address:
            if not address.startswith("\\\\.\\pipe\\"):
                raise ValueError("endpoint must be a local Named Pipe path")
            self.pipe_name = address
        if peer_sid:
            self.expected_sid = peer_sid
        self._stop.clear()
        self._event_loop = asyncio.get_running_loop()
        try:
            await asyncio.to_thread(self._serve_loop, handler)
        except asyncio.CancelledError:
            self.stop()
            raise
        finally:
            self._event_loop = None

    def stop(self) -> None:
        self._stop.set()
        with self._listener_lock:
            threads = tuple(self._connection_threads)
        for thread in threads:
            self._cancel_synchronous_io(thread)

    async def close(self) -> None:
        self.stop()
        current = threading.current_thread()
        with self._listener_lock:
            threads = tuple(self._connection_threads)
        for thread in threads:
            if thread is not current:
                # ``serve`` can be stopped between adding a client thread to
                # the set and calling ``start``.  Joining an unstarted thread
                # raises RuntimeError, so only join threads that have begun.
                if thread.ident is not None:
                    thread.join(timeout=1.0)
        with self._listener_lock:
            self._connection_threads.intersection_update(
                thread for thread in threads if thread.is_alive()
            )

    async def connect(self, endpoint: IpcEndpoint | str | None) -> Any:
        self._require_windows()
        _endpoint_address(endpoint)
        raise CapabilityUnavailable(
            "local_ipc_client",
            "Python exposes the Named Pipe server; the desktop client uses Rust",
        )


__all__ = [
    "ERROR_MORE_DATA",
    "ERROR_NO_DATA",
    "ERROR_PIPE_CONNECTED",
    "ERROR_PIPE_LISTENING",
    "IpcHandshake",
    "IpcProtocolError",
    "IpcRateLimitError",
    "MAX_MESSAGE_SIZE",
    "PIPE_NAME",
    "RATE_LIMIT_PER_SEC",
    "WindowsNamedPipeIpc",
    "decode_frame",
    "encode_frame",
    "validate_handshake",
    "validate_request",
]
