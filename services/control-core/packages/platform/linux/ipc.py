"""Linux LocalIpc — Unix domain socket with peer-credential auth (P5).

Spec §4.4 Linux column: "UDS + mode/peer creds".

Security model:
  - Socket file created with mode 0600 (owner-only) in a 0700 directory.
  - Every accepted connection verifies SO_PEERCRED: the connecting uid
    must equal the socket owner's uid (analogue of the Windows SID ACL).
    Mismatch → connection closed immediately, attempt logged.
  - Message framing matches the Windows IPC v1 contract (length-prefixed
    JSON) so the desktop shell uses one protocol across platforms.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import struct
from typing import Any, Awaitable, Callable

import structlog

from packages.platform.shared.contracts import IpcEndpoint, LocalIpc

logger = structlog.get_logger()

MAX_FRAME = 1 << 20  # 1 MiB, same cap as Windows IPC v1


def encode_frame(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def decode_frame(buffer: bytes) -> tuple[dict[str, Any] | None, bytes]:
    """Decode one frame; returns (message_or_None, remaining_buffer)."""
    if len(buffer) < 4:
        return None, buffer
    (length,) = struct.unpack("<I", buffer[:4])
    if length > MAX_FRAME:
        raise ValueError("frame too large")
    if len(buffer) < 4 + length:
        return None, buffer
    payload = buffer[4:4 + length]
    return json.loads(payload.decode("utf-8")), buffer[4 + length:]


class UnixSocketIpc(LocalIpc):
    """UDS server enforcing uid peer authentication."""

    def __init__(self, *, allowed_uid: int | None = None):
        self.allowed_uid = allowed_uid  # None → socket owner's uid at bind()
        self._server: asyncio.AbstractServer | None = None
        self._path: str | None = None

    async def serve(self, endpoint: IpcEndpoint, handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        if endpoint.transport != "uds":
            raise ValueError(f"UnixSocketIpc serves 'uds', got '{endpoint.transport}'")
        path = endpoint.address
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)

        # Stale socket from a crashed run: safe to replace (we own the dir).
        if os.path.exists(path):
            os.unlink(path)

        loop = asyncio.get_running_loop()
        self._server = await loop.create_unix_server(
            lambda: _IpcProtocol(self._peer_uid_allowed, handler), path,
        )
        os.chmod(path, 0o600)
        if self.allowed_uid is None:
            self.allowed_uid = os.stat(path).st_uid
        self._path = path
        logger.info("UDS IPC listening: path=%s uid=%s", path, self.allowed_uid)

    def _peer_uid_allowed(self, uid: int) -> bool:
        return uid == self.allowed_uid

    async def connect(self, endpoint: IpcEndpoint) -> object:
        """Open a client connection (authenticated by construction: the
        server side enforces SO_PEERCRED against our uid)."""
        if endpoint.transport != "uds":
            raise ValueError(f"UnixSocketIpc connects to 'uds', got '{endpoint.transport}'")
        return await uds_client(endpoint.address)

    def verify_peer(self, conn: object, expected_sid: str) -> bool:
        """Client-side check: the socket file must be owned by the uid in
        *expected_sid* — ownership by anyone else means we are not talking
        to our own sidecar instance."""
        import stat as _stat
        try:
            writer = conn
            sock = writer.get_extra_info("socket")
            path = sock.getpeername()  # UDS peername is the socket path
            owner_uid = _stat.stat(path).st_uid
        except (OSError, AttributeError, TypeError):
            return False
        return str(owner_uid) == str(expected_sid)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._path and os.path.exists(self._path):
            os.unlink(self._path)
            self._path = None


class _IpcProtocol(asyncio.Protocol):
    def __init__(self, peer_ok: Callable[[int], bool],
                 handler: Callable[[dict], Awaitable[dict]]):
        self._peer_ok = peer_ok
        self._handler = handler
        self._buffer = b""
        self._transport: asyncio.Transport | None = None
        self._peer_uid: int | None = None

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self._transport = transport
        sock = transport.get_extra_info("socket")
        creds = sock.getsockopt(socket.SOL_SOCKET, 17, struct.calcsize("3i"))  # SO_PEERCRED
        pid, uid, gid = struct.unpack("3i", creds)
        self._peer_uid = uid
        if not self._peer_ok(uid):
            logger.warning("UDS peer denied: uid=%s", uid)
            transport.close()
            self._transport = None

    def data_received(self, data: bytes) -> None:  # type: ignore[override]
        if self._transport is None:
            return
        self._buffer += data
        try:
            message, self._buffer = decode_frame(self._buffer)
        except ValueError:
            self._transport.close()
            return
        if message is None:
            return
        asyncio.get_running_loop().create_task(self._reply(message))

    async def _reply(self, message: dict[str, Any]) -> None:
        try:
            response = await self._handler(message)
        except Exception as exc:
            logger.exception("UDS handler error")
            response = {"v": 1, "id": message.get("id"), "ok": False,
                        "error": {"code": "E_INTERNAL", "message": str(exc)}}
        if self._transport is not None:
            self._transport.write(encode_frame(response))


async def uds_client(address: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect a client to the UDS endpoint (for tests and the shell)."""
    return await asyncio.open_unix_connection(address)
