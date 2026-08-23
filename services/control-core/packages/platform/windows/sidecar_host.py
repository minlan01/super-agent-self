"""True Windows control-core sidecar and IPC v1 implementation.

The module keeps the protocol and dispatch logic importable for unit tests while
deferring Windows-only imports until the Named Pipe host is started.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import socket
import sqlite3
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

LOGGER = logging.getLogger("zcode.sidecar")

PIPE_PATH = os.environ.get("ZCODE_PIPE", r"\\.\pipe\zcode-control-core-v1")
RUN_NONCE = os.environ.get("ZCODE_RUN_NONCE", "")
PROTOCOL_VERSIONS = (1,)
SCHEMA_VERSION = "1.0.0"
MAX_FRAME_SIZE = 1 << 20
HTTP_HOST = "127.0.0.1"
HTTP_HEADER = "X-Zcode-Sidecar-Token"
DEFAULT_HTTP_TIMEOUT = 15.0
DESKTOP_API_LOAD_TIMEOUT = 12.0
BOOTSTRAP_FORMAT = 1
BOOTSTRAP_DATABASE = "agent_platform.db"
BOOTSTRAP_MANIFEST = "manifest.json"


class ProtocolFailure(Exception):
    """A protocol-level failure that can be returned to the peer."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


def _error(message: Mapping[str, Any] | None, code: str, detail: str | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code}
    if detail:
        error["message"] = detail
    return {"v": 1, "id": message.get("id") if message else None, "ok": False, "error": error}


def _ok(message: Mapping[str, Any] | None, data: Mapping[str, Any]) -> dict[str, Any]:
    return {"v": 1, "id": message.get("id") if message else None, "ok": True, "data": dict(data)}


def encode_frame(value: Mapping[str, Any]) -> bytes:
    """Encode one length-prefixed JSON object."""

    if not isinstance(value, Mapping):
        raise ProtocolFailure("E_BAD_REQUEST", "IPC frame must be a JSON object")
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolFailure("E_BAD_JSON", "IPC frame is not JSON serializable") from exc
    if len(payload) > MAX_FRAME_SIZE:
        raise ProtocolFailure("E_MSG_TOO_LARGE")
    return struct.pack("<I", len(payload)) + payload


def decode_frame(frame: bytes | bytearray | memoryview) -> dict[str, Any]:
    """Decode a complete length-prefixed JSON object for tests and clients."""

    raw = bytes(frame)
    if len(raw) < 4:
        raise ProtocolFailure("E_BAD_JSON", "IPC frame is missing its length prefix")
    size = struct.unpack("<I", raw[:4])[0]
    if size > MAX_FRAME_SIZE:
        raise ProtocolFailure("E_MSG_TOO_LARGE")
    if len(raw) != size + 4:
        raise ProtocolFailure("E_BAD_JSON", "IPC frame length does not match payload")
    try:
        value = json.loads(raw[4:].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolFailure("E_BAD_JSON", "IPC frame is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolFailure("E_BAD_JSON", "IPC frame must be a JSON object")
    return value


@dataclass
class IpcSession:
    peer_pid: int | None = None
    negotiated_version: int | None = None


class IpcServer:
    """Contract v1 dispatcher independent from the Windows transport."""

    def __init__(
        self,
        http_port: int,
        http_token: str,
        *,
        run_nonce: str | None = None,
        sidecar_pid: int | None = None,
        proxy_opener: Any | None = None,
    ) -> None:
        self.http_port = int(http_port)
        self.http_token = http_token
        self.run_nonce = run_nonce if run_nonce is not None else os.environ.get("ZCODE_RUN_NONCE", "")
        self.sidecar_pid = sidecar_pid or os.getpid()
        self.started_at = time.monotonic()
        self.stop_event = threading.Event()
        self._proxy_opener = proxy_opener

    def dispatch(self, message: Mapping[str, Any], session: IpcSession) -> dict[str, Any]:
        if not isinstance(message, Mapping):
            return _error(None, "E_BAD_JSON")
        if message.get("v") not in PROTOCOL_VERSIONS:
            return _error(message, "E_VERSION")
        method = message.get("method")
        if not isinstance(method, str) or not method:
            return _error(message, "E_BAD_REQUEST")
        if self.stop_event.is_set() and method != "ipc.shutdown":
            return _error(message, "E_SHUTTING_DOWN")
        if session.negotiated_version is None and method != "hello":
            return _error(message, "E_HANDSHAKE_REQUIRED")
        if session.negotiated_version is not None and method == "hello":
            return _error(message, "E_BAD_REQUEST", "hello may only be called once")
        if method == "hello":
            return self._hello(message, session)
        if method == "ipc.ping":
            return _ok(
                message,
                {"pong": True, "uptime_s": round(time.monotonic() - self.started_at, 3)},
            )
        if method == "http.request":
            return self._proxy(message)
        if method == "ipc.shutdown":
            response = _ok(message, {"bye": True})
            self.stop_event.set()
            return response
        return _error(message, "E_UNKNOWN_METHOD")

    def _hello(self, message: Mapping[str, Any], session: IpcSession) -> dict[str, Any]:
        params = message.get("params")
        if not isinstance(params, Mapping):
            return _error(message, "E_BAD_REQUEST")
        nonce = params.get("nonce")
        versions = params.get("client_versions")
        pid = params.get("pid")
        if not isinstance(nonce, str) or not nonce or len(nonce) > 256:
            return _error(message, "E_NONCE_MISMATCH")
        if nonce != self.run_nonce:
            return _error(message, "E_NONCE_MISMATCH")
        if not isinstance(versions, list) or not all(isinstance(v, int) for v in versions):
            return _error(message, "E_VERSION")
        if not isinstance(pid, int) or isinstance(pid, bool):
            return _error(message, "E_PEER_DENIED")
        if session.peer_pid is not None and pid != session.peer_pid:
            return _error(message, "E_PEER_DENIED")
        common = set(versions).intersection(PROTOCOL_VERSIONS)
        if not common:
            return _error(message, "E_VERSION")
        version = max(common)
        session.negotiated_version = version
        return _ok(
            message,
            {
                "version": version,
                "http_port": self.http_port,
                "http_token": self.http_token,
                "sidecar_pid": self.sidecar_pid,
                "schema_version": SCHEMA_VERSION,
            },
        )

    def _proxy(self, message: Mapping[str, Any]) -> dict[str, Any]:
        params = message.get("params")
        if not isinstance(params, Mapping):
            return _error(message, "E_BAD_REQUEST")
        method = params.get("method", "GET")
        path = params.get("path")
        headers = params.get("headers") or {}
        if not isinstance(method, str) or not method or not method.isascii() or not method.isalpha():
            return _error(message, "E_BAD_REQUEST")
        method = method.upper()
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or "\r" in path
            or "\n" in path
        ):
            return _error(message, "E_BAD_REQUEST")
        if not isinstance(headers, Mapping) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()
        ):
            return _error(message, "E_BAD_REQUEST")
        request_headers = {
            key: value
            for key, value in headers.items()
            if key.lower()
            not in {"host", "connection", "content-length", "transfer-encoding", HTTP_HEADER.lower()}
        }
        request_id = params.get("request_id")
        if request_id is not None:
            if not isinstance(request_id, str) or len(request_id) > 128:
                return _error(message, "E_BAD_REQUEST")
            request_headers.setdefault("X-Request-ID", request_id)
        request_headers[HTTP_HEADER] = self.http_token

        body = params.get("body")
        payload: bytes | None
        if body is None:
            payload = None
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            try:
                payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError):
                return _error(message, "E_BAD_REQUEST")
            request_headers.setdefault("Content-Type", "application/json")
        if payload is not None and len(payload) > MAX_FRAME_SIZE:
            return _error(message, "E_MSG_TOO_LARGE")

        url = f"http://{HTTP_HOST}:{self.http_port}{path}"
        try:
            request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
            opener = self._proxy_opener or urllib.request.urlopen
            response = opener(request, timeout=DEFAULT_HTTP_TIMEOUT)
            return _ok(message, self._read_http_response(response))
        except urllib.error.HTTPError as exc:
            return _ok(message, self._read_http_response(exc))
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            LOGGER.warning("Sidecar HTTP proxy failed: %s", exc)
            return _error(message, "E_INTERNAL")
        except ProtocolFailure as exc:
            return _error(message, exc.code)

    @staticmethod
    def _read_http_response(response: Any) -> dict[str, Any]:
        body = response.read(MAX_FRAME_SIZE + 1)
        if len(body) > MAX_FRAME_SIZE:
            raise ProtocolFailure("E_MSG_TOO_LARGE")
        headers = dict(response.headers.items()) if getattr(response, "headers", None) else {}
        return {
            "status": int(response.getcode()),
            "body": body.decode("utf-8", errors="replace"),
            "headers": headers,
        }


class SidecarTokenGate:
    """ASGI middleware requiring the internal token on loopback HTTP."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        presented = headers.get(HTTP_HEADER.lower().encode("ascii"), b"").decode("utf-8", errors="ignore")
        if not hmac.compare_digest(presented, self.token):
            if scope.get("type") == "websocket":
                await send({"type": "websocket.close", "code": 4401})
                return
            body = b'{"detail":"sidecar token required"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


class DeferredDesktopApplication:
    """Serve health immediately while the desktop FastAPI app initializes."""

    def __init__(self, loader: Any = None, *, timeout: float = DESKTOP_API_LOAD_TIMEOUT) -> None:
        self.loader = loader or self._load_application
        self.timeout = timeout
        self.initialization_complete = threading.Event()
        self._ready: asyncio.Event | None = None
        self._load_task: asyncio.Task[None] | None = None
        self._application: Any | None = None
        self._failure: BaseException | None = None
        self._lifespan_context: Any | None = None

    def preload(self) -> None:
        """Import the desktop API before the transport threads start.

        The production sidecar has a strict end-to-end readiness budget.  If
        the API import competes with Uvicorn and pywin32 imports on newly
        created threads, Windows can delay the loader by several seconds even
        though the import itself is short.  Preloading removes that scheduler
        and import-lock variance while preserving deferred behavior for unit
        tests and callers that do not opt in.
        """

        if self._application is not None or self._failure is not None:
            return
        try:
            self._application = self.loader()
        except BaseException as exc:
            self._failure = exc
            LOGGER.exception("control-core desktop API preload failed")

    @staticmethod
    def _load_application() -> Any:
        from apps.api_server.main import app

        return app

    async def _load(self) -> None:
        try:
            if self._application is None and self._failure is None:
                loop = asyncio.get_running_loop()
                loaded: asyncio.Future[Any] = loop.create_future()

                def publish_result(value: Any = None, error: BaseException | None = None) -> None:
                    if loaded.done() or loop.is_closed():
                        return
                    if error is not None:
                        loaded.set_exception(error)
                    else:
                        loaded.set_result(value)

                def import_application() -> None:
                    try:
                        application = self.loader()
                    except BaseException as exc:
                        try:
                            loop.call_soon_threadsafe(publish_result, None, exc)
                        except RuntimeError:
                            pass
                    else:
                        try:
                            loop.call_soon_threadsafe(publish_result, application, None)
                        except RuntimeError:
                            pass

                threading.Thread(
                    target=import_application,
                    name="zcode-desktop-api-loader",
                    daemon=True,
                ).start()
                application = await loaded
                self._application = application
            if self._failure is not None or self._application is None:
                raise RuntimeError(
                    "desktop API preload did not produce an application"
                ) from self._failure
            application = self._application
            lifespan_context = application.router.lifespan_context(application)
            await lifespan_context.__aenter__()
            self._lifespan_context = lifespan_context
            self._application = application
            LOGGER.info("control-core desktop API ready")
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._failure = exc
            LOGGER.exception("control-core desktop API initialization failed")
        finally:
            assert self._ready is not None
            self._ready.set()
            self.initialization_complete.set()

    async def _serve_lifespan(self, receive: Any, send: Any) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                if self._ready is None:
                    self._ready = asyncio.Event()
                    self._load_task = asyncio.create_task(self._load())
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                if self._load_task is not None and not self._load_task.done():
                    self._load_task.cancel()
                if self._load_task is not None:
                    try:
                        await self._load_task
                    except asyncio.CancelledError:
                        pass
                if self._lifespan_context is not None:
                    await self._lifespan_context.__aexit__(None, None, None)
                await send({"type": "lifespan.shutdown.complete"})
                return

    @staticmethod
    async def _json_response(send: Any, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "lifespan":
            await self._serve_lifespan(receive, send)
            return
        if scope.get("type") == "http" and scope.get("path") == "/health":
            from packages.agent_core.version import __version__

            await self._json_response(
                send,
                200,
                {
                    "status": "ok",
                    "version": __version__,
                    "edition": "enterprise",
                    "api_ready": self._application is not None,
                },
            )
            return
        if self._ready is None:
            self._ready = asyncio.Event()
            self._load_task = asyncio.create_task(self._load())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self.timeout)
        except TimeoutError:
            await self._json_response(
                send,
                503,
                {"detail": "control-core desktop API is still initializing"},
            )
            return
        if self._failure is not None or self._application is None:
            await self._json_response(
                send,
                503,
                {"detail": "control-core desktop API initialization failed"},
            )
            return
        await self._application(scope, receive, send)


@dataclass
class HttpRuntime:
    server: Any
    thread: threading.Thread
    socket: socket.socket
    port: int
    token: str
    application: DeferredDesktopApplication

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            try:
                self.socket.close()
            except OSError:
                pass
            self.thread.join(timeout=1)


def _resource_root() -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("ZCODE_RESOURCE_ROOT")
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            Path.cwd(),
            Path(sys.argv[0]).resolve().parent,
            Path(__file__).resolve().parents[3],
        ]
    )
    for candidate in candidates:
        for directory in (candidate, *candidate.parents):
            source_layout = (directory / "packages").is_dir()
            standalone_layout = (
                (directory / "alembic").is_dir()
                and (directory / "configs").is_dir()
            )
            if (directory / "alembic.ini").is_file() and (source_layout or standalone_layout):
                return directory
    raise RuntimeError("could not locate the control-core resource root")


def _sqlite_url(path: Path) -> str:
    return "sqlite:///" + path.resolve().as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _sqlite_database_path(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    path_text = database_url[len(prefix) :].split("?", 1)[0]
    if not path_text or path_text == ":memory:":
        return None
    return Path(path_text).expanduser().resolve()


def _read_sqlite_revision(path: Path, *, immutable: bool = False) -> str | None:
    if not path.is_file():
        return None
    suffix = "?mode=ro"
    if immutable:
        suffix += "&immutable=1"
    try:
        with sqlite3.connect(path.resolve().as_uri() + suffix, uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            try:
                rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc).lower():
                    return None
                raise
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"could not read SQLite migration revision: {path}") from exc
    if not rows:
        return None
    if len(rows) != 1 or not isinstance(rows[0][0], str) or not rows[0][0]:
        raise RuntimeError(f"invalid alembic_version state in SQLite database: {path}")
    return rows[0][0]


def _load_bootstrap(resource_root: Path) -> tuple[Path, dict[str, Any]] | None:
    bootstrap_dir = resource_root / "bootstrap"
    database = bootstrap_dir / BOOTSTRAP_DATABASE
    manifest_path = bootstrap_dir / BOOTSTRAP_MANIFEST
    if not database.exists() and not manifest_path.exists():
        return None
    if not database.is_file() or not manifest_path.is_file():
        raise RuntimeError("packaged SQLite bootstrap is incomplete")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("packaged SQLite bootstrap manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("packaged SQLite bootstrap manifest must be an object")
    sha256 = manifest.get("sha256")
    size = manifest.get("size")
    revision = manifest.get("revision")
    if (
        manifest.get("format") != BOOTSTRAP_FORMAT
        or manifest.get("database") != BOOTSTRAP_DATABASE
        or not isinstance(revision, str)
        or not revision
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in sha256)
    ):
        raise RuntimeError("packaged SQLite bootstrap manifest fields are invalid")
    manifest["sha256"] = sha256.upper()
    return database, manifest


def _verify_bootstrap(database: Path, manifest: Mapping[str, Any]) -> None:
    if database.stat().st_size != manifest["size"]:
        raise RuntimeError("packaged SQLite bootstrap size does not match its manifest")
    if _sha256_file(database) != manifest["sha256"]:
        raise RuntimeError("packaged SQLite bootstrap SHA-256 does not match its manifest")
    if _read_sqlite_revision(database, immutable=True) != manifest["revision"]:
        raise RuntimeError("packaged SQLite bootstrap revision does not match its manifest")
    try:
        with sqlite3.connect(
            database.resolve().as_uri() + "?mode=ro&immutable=1",
            uri=True,
        ) as connection:
            quick_check = connection.execute("PRAGMA quick_check").fetchall()
    except sqlite3.DatabaseError as exc:
        raise RuntimeError("packaged SQLite bootstrap integrity check failed") from exc
    if quick_check != [("ok",)]:
        raise RuntimeError("packaged SQLite bootstrap failed PRAGMA quick_check")


def _install_bootstrap(source: Path, target: Path, manifest: Mapping[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / (
        f".{target.name}.bootstrap-{os.getpid()}-{secrets.token_hex(8)}"
    )
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if temporary.stat().st_size != manifest["size"]:
            raise RuntimeError("copied SQLite bootstrap size does not match its manifest")
        if _sha256_file(temporary) != manifest["sha256"]:
            raise RuntimeError("copied SQLite bootstrap SHA-256 does not match its manifest")
        try:
            # A hard-link publish is atomic and refuses to replace a database
            # another Sidecar created while this process was copying.
            os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _bootstrap_sqlite_if_current(resource_root: Path) -> bool:
    packaged = _load_bootstrap(resource_root)
    if packaged is None:
        return False
    source, manifest = packaged
    _verify_bootstrap(source, manifest)
    target = _sqlite_database_path(os.environ.get("DATABASE_URL", ""))
    if target is None:
        return False
    if not target.exists():
        _install_bootstrap(source, target, manifest)
        LOGGER.info("Installed verified SQLite bootstrap at %s", target)
    revision = _read_sqlite_revision(target)
    if revision == manifest["revision"]:
        LOGGER.info("SQLite schema already at packaged revision %s", revision)
        return True
    return False


def prepare_runtime_environment(resource_root: Path) -> Path:
    """Set writable runtime paths before importing the FastAPI application."""

    resource_root = resource_root.resolve()
    if str(resource_root) not in sys.path:
        sys.path.insert(0, str(resource_root))
    os.chdir(resource_root)
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    data_root = Path(os.environ.get("ZCODE_DATA_DIR", local_app_data / "zcode"))
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "logs").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ZCODE_DATA_DIR", str(data_root))
    os.environ.setdefault("DATABASE_URL", _sqlite_url(data_root / "agent_platform.db"))
    os.environ.setdefault("APP_WORKSPACE_ROOT", str(data_root / "workspace"))
    os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))
    os.environ.setdefault("REQUIRE_AUTH", "true")
    os.environ["ZCODE_API_PROFILE"] = "desktop"
    return data_root


def run_migrations(resource_root: Path) -> None:
    if os.environ.get("ZCODE_SKIP_MIGRATIONS") == "1":
        return
    if _bootstrap_sqlite_if_current(resource_root):
        return
    from alembic import command
    from alembic.config import Config

    # Alembic's ``Config(path)`` reads ini files through the Windows locale
    # codec.  This repository's UTF-8 comments then fail under a GBK locale,
    # so configure the already-known migration inputs programmatically.
    config = Config()
    config.set_main_option("script_location", str(resource_root / "alembic"))
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"].replace("%", "%%"))
    command.upgrade(config, "head")


def start_http_server(http_token: str, *, resource_root: Path) -> HttpRuntime:
    application = DeferredDesktopApplication()
    # Let Uvicorn start its lifespan task before importing the desktop route
    # graph.  ``DeferredDesktopApplication`` loads the application in its own
    # background task, so the HTTP health endpoint and Named Pipe handshake can
    # become available while the heavier route graph initializes.  Requests
    # other than ``/health`` still wait for the same completion event.
    import uvicorn

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HTTP_HOST, 0))
    sock.listen(128)
    port = int(sock.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            SidecarTokenGate(application, http_token),
            host=HTTP_HOST,
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [sock]},
        name="zcode-control-core-http",
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2)
        raise RuntimeError("control-core HTTP server did not become ready")
    LOGGER.info("control-core HTTP server ready on %s:%s", HTTP_HOST, port)
    return HttpRuntime(
        server=server,
        thread=thread,
        socket=sock,
        port=port,
        token=http_token,
        application=application,
    )


class NamedPipeServer:
    """Windows Named Pipe transport for the contract dispatcher."""

    def __init__(self, pipe_path: str, launcher_pid: int, dispatcher: IpcServer) -> None:
        if not pipe_path.startswith("\\\\.\\pipe\\"):
            raise ValueError("ZCODE_PIPE must be a local \\\\.\\pipe\\ path")
        if launcher_pid <= 0:
            raise ValueError("ZCODE_LAUNCHER_PID is required")
        self.pipe_path = pipe_path
        self.launcher_pid = launcher_pid
        self.dispatcher = dispatcher
        self._security_attributes_value: Any | None = None
        self.listening_event = threading.Event()

    @staticmethod
    def _win32() -> tuple[Any, Any, Any, Any]:
        if sys.platform != "win32":
            raise RuntimeError("the true sidecar requires Windows")
        import pywintypes
        import win32api
        import win32file
        import win32pipe

        return pywintypes, win32api, win32file, win32pipe

    def _build_security_attributes(self) -> Any:
        pywintypes, win32api, _win32file, _win32pipe = self._win32()
        import ntsecuritycon
        import win32security

        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        try:
            sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
            sid_text = win32security.ConvertSidToStringSid(sid)
        finally:
            close = getattr(token, "Close", None)
            if close:
                close()
        dacl = win32security.ACL()
        dacl.AddAccessAllowedAce(
            win32security.ACL_REVISION,
            ntsecuritycon.GENERIC_READ
            | ntsecuritycon.GENERIC_WRITE
            | getattr(ntsecuritycon, "SYNCHRONIZE", 0x00100000),
            sid,
        )
        descriptor = win32security.SECURITY_DESCRIPTOR()
        descriptor.SetSecurityDescriptorOwner(sid, False)
        descriptor.SetSecurityDescriptorDacl(1, dacl, 0)
        protected = getattr(win32security, "SE_DACL_PROTECTED", 0x1000)
        setter = getattr(descriptor, "SetSecurityDescriptorControl", None)
        if setter is None:
            raise RuntimeError("pywin32 cannot protect the Named Pipe DACL")
        setter(protected, protected)
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = descriptor
        attributes.bInheritHandle = False
        LOGGER.info("Named Pipe DACL restricted to current SID %s", sid_text)
        return attributes

    @staticmethod
    def _client_pid(handle: Any) -> int:
        _pywintypes, _win32api, _win32file, win32pipe = NamedPipeServer._win32()
        getter = getattr(win32pipe, "GetNamedPipeClientProcessId", None)
        if getter is None:
            raise RuntimeError("pywin32 cannot query Named Pipe client PID")
        pid = int(getter(handle))
        if pid <= 0:
            raise RuntimeError("Named Pipe client PID is unavailable")
        return pid

    @staticmethod
    def _read_exact(handle: Any, size: int) -> bytes:
        _pywintypes, _win32api, win32file, _win32pipe = NamedPipeServer._win32()
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            status, data = win32file.ReadFile(handle, remaining)
            if status:
                raise OSError(f"Named Pipe ReadFile returned status {status}")
            chunk = bytes(data)
            if not chunk:
                raise ConnectionError("Named Pipe peer disconnected")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @classmethod
    def _read_frame(cls, handle: Any) -> dict[str, Any]:
        header = cls._read_exact(handle, 4)
        size = struct.unpack("<I", header)[0]
        if size > MAX_FRAME_SIZE:
            raise ProtocolFailure("E_MSG_TOO_LARGE")
        return decode_frame(header + cls._read_exact(handle, size))

    @staticmethod
    def _write_frame(handle: Any, message: Mapping[str, Any]) -> None:
        _pywintypes, _win32api, win32file, _win32pipe = NamedPipeServer._win32()
        win32file.WriteFile(handle, encode_frame(message))

    def _serve_connection(self, handle: Any) -> None:
        _pywintypes, _win32api, win32file, win32pipe = self._win32()
        peer_pid = self._client_pid(handle)
        session = IpcSession(peer_pid=peer_pid)
        if peer_pid != self.launcher_pid:
            self._write_frame(handle, _error(None, "E_PEER_DENIED"))
            return
        while not self.dispatcher.stop_event.is_set():
            try:
                message = self._read_frame(handle)
                response = self.dispatcher.dispatch(message, session)
            except ProtocolFailure as exc:
                response = _error(None, exc.code)
                self._write_frame(handle, response)
                return
            except (ConnectionError, OSError, _pywintypes.error):
                return
            self._write_frame(handle, response)
            if response.get("ok") is True and message.get("method") == "ipc.shutdown":
                return

    def serve_forever(self) -> None:
        _pywintypes, _win32api, win32file, win32pipe = self._win32()
        self._security_attributes_value = self._build_security_attributes()
        flags = (
            win32pipe.PIPE_TYPE_MESSAGE
            | win32pipe.PIPE_READMODE_BYTE
            | win32pipe.PIPE_WAIT
            | 0x00000008  # PIPE_REJECT_REMOTE_CLIENTS
        )
        while not self.dispatcher.stop_event.is_set():
            handle = win32pipe.CreateNamedPipe(
                self.pipe_path,
                win32pipe.PIPE_ACCESS_DUPLEX,
                flags,
                1,
                MAX_FRAME_SIZE + 4,
                MAX_FRAME_SIZE + 4,
                1000,
                self._security_attributes_value,
            )
            self.listening_event.set()
            try:
                try:
                    win32pipe.ConnectNamedPipe(handle, None)
                except _pywintypes.error as exc:
                    if getattr(exc, "winerror", None) != 535:
                        raise
                win32pipe.SetNamedPipeHandleState(
                    handle,
                    win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                    None,
                    None,
                )
                self._serve_connection(handle)
            except _pywintypes.error as exc:
                if getattr(exc, "winerror", None) not in {2, 109, 231, 232, 995}:
                    LOGGER.exception("Named Pipe connection failed")
            finally:
                # DisconnectNamedPipe discards unread server output. Flush the
                # final response, especially ``ipc.shutdown``, before closing.
                try:
                    win32file.FlushFileBuffers(handle)
                except Exception:
                    pass
                try:
                    win32pipe.DisconnectNamedPipe(handle)
                except Exception:
                    pass
                try:
                    win32file.CloseHandle(handle)
                except Exception:
                    pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Zcode control-core IPC v1 sidecar")
    parser.parse_args(argv)
    if sys.platform != "win32":
        raise SystemExit("the true control-core sidecar is Windows-only")
    # Migration modules are shipped as read-only installer resources. Never
    # create __pycache__ files beside them, otherwise uninstall leaves files
    # that were not part of the NSIS manifest behind.
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sys.dont_write_bytecode = True
    run_nonce = os.environ.get("ZCODE_RUN_NONCE", "")
    launcher_text = os.environ.get("ZCODE_LAUNCHER_PID", "")
    if not run_nonce:
        raise SystemExit("ZCODE_RUN_NONCE is required (fail closed)")
    try:
        launcher_pid = int(launcher_text)
    except ValueError as exc:
        raise SystemExit("ZCODE_LAUNCHER_PID is required (fail closed)") from exc
    resource_root = _resource_root()
    prepare_runtime_environment(resource_root)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_migrations(resource_root)
    token = secrets.token_hex(32)
    http = start_http_server(token, resource_root=resource_root)
    dispatcher = IpcServer(
        http.port,
        token,
        run_nonce=run_nonce,
        sidecar_pid=os.getpid(),
    )
    pipe = NamedPipeServer(
        os.environ.get("ZCODE_PIPE", PIPE_PATH),
        launcher_pid,
        dispatcher,
    )
    pipe_failure: list[BaseException] = []

    def serve_pipe() -> None:
        try:
            pipe.serve_forever()
        except BaseException as exc:
            pipe_failure.append(exc)

    pipe_thread = threading.Thread(
        target=serve_pipe,
        name="zcode-control-core-pipe",
        daemon=True,
    )
    try:
        pipe_thread.start()
        if not pipe.listening_event.wait(timeout=5):
            if pipe_failure:
                raise RuntimeError("control-core Named Pipe initialization failed") from pipe_failure[0]
            raise RuntimeError("control-core Named Pipe did not become ready")
        LOGGER.info("control-core sidecar transport ready: pipe=%s", pipe.pipe_path)
        # Readiness is the control-plane boundary: HTTP is listening and the
        # authenticated Named Pipe is accepting the launcher's handshake.  The
        # desktop API continues loading in the deferred lifespan task; its
        # non-health requests remain gated by ``_ready`` and return 503 on a
        # fatal initialization error.  This keeps startup deterministic while
        # preserving fail-closed behavior for business traffic.
        if pipe_failure:
            raise RuntimeError("control-core Named Pipe stopped before API readiness") from pipe_failure[0]
        LOGGER.info("control-core sidecar ready: pipe=%s", pipe.pipe_path)
        pipe_thread.join()
        if pipe_failure:
            raise RuntimeError("control-core Named Pipe failed") from pipe_failure[0]
    finally:
        http.stop()


__all__ = [
    "HTTP_HEADER",
    "IpcServer",
    "IpcSession",
    "MAX_FRAME_SIZE",
    "NamedPipeServer",
    "ProtocolFailure",
    "SCHEMA_VERSION",
    "SidecarTokenGate",
    "decode_frame",
    "encode_frame",
    "main",
    "prepare_runtime_environment",
    "run_migrations",
    "start_http_server",
]
