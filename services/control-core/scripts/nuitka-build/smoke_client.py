"""IPC v1 smoke client.

Use ``--sidecar`` to launch a sidecar owned by this process. This is required
for the production peer-PID policy; an arbitrary process cannot attach to a
sidecar launched by Tauri.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.platform.windows.sidecar_host import MAX_FRAME_SIZE, decode_frame, encode_frame


class _PipeStream:
    def __init__(self, handle: Any) -> None:
        self.handle = handle

    def read(self, size: int) -> bytes:
        import win32file

        status, data = win32file.ReadFile(self.handle, size)
        if status:
            raise OSError(f"Named Pipe ReadFile returned status {status}")
        return bytes(data)

    def write(self, data: bytes) -> int:
        import win32file

        _status, written = win32file.WriteFile(self.handle, data)
        return int(written)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        import win32file

        win32file.CloseHandle(self.handle)

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _open_pipe(pipe_path: str, timeout: float = 15.0) -> _PipeStream:
    import pywintypes
    import win32con
    import win32file
    import win32pipe

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            handle = win32file.CreateFile(
                pipe_path,
                win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                0,
                None,
                win32con.OPEN_EXISTING,
                0,
                None,
            )
            win32pipe.SetNamedPipeHandleState(
                handle,
                win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                None,
                None,
            )
            return _PipeStream(handle)
        except pywintypes.error as exc:
            if getattr(exc, "winerror", None) in {2, 231}:
                time.sleep(0.05)
                continue
            raise
    raise TimeoutError(f"Named Pipe was not ready within {timeout}s: {pipe_path}")


def _read_exact(stream, size: int) -> bytes:
    parts: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise ConnectionError("sidecar closed the pipe")
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


def _request(stream, message: dict[str, Any]) -> dict[str, Any]:
    stream.write(encode_frame(message))
    stream.flush()
    header = _read_exact(stream, 4)
    size = int.from_bytes(header, "little")
    if size > MAX_FRAME_SIZE:
        raise RuntimeError("sidecar returned an oversized response")
    return decode_frame(header + _read_exact(stream, size))


def _http_request(
    stream: _PipeStream,
    request_id: int,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = _request(
        stream,
        {
            "v": 1,
            "id": request_id,
            "method": "http.request",
            "params": {"method": method, "path": path, "headers": headers, "body": body},
        },
    )
    if not response.get("ok"):
        raise RuntimeError(f"http.request IPC failed: {response}")
    data = response["data"]
    return int(data["status"]), json.loads(data.get("body") or "{}")


def _spawn_sidecar(path: Path, pipe_path: str, nonce: str) -> subprocess.Popen[bytes]:
    environment = os.environ.copy()
    standalone = path.suffix.lower() == ".exe"
    resource_root = path.parent if standalone else ROOT
    environment.update(
        {
            "ZCODE_RUN_NONCE": nonce,
            "ZCODE_LAUNCHER_PID": str(os.getpid()),
            "ZCODE_PIPE": pipe_path,
            "ZCODE_DATA_DIR": tempfile.mkdtemp(prefix="zcode_sidecar_smoke_"),
            "ZCODE_RESOURCE_ROOT": str(resource_root),
            "TESTING": "1",
            "LLM_PROVIDER": "mock",
        }
    )
    command = [str(path)] if path.suffix.lower() == ".exe" else [sys.executable, str(path)]
    return subprocess.Popen(command, cwd=str(resource_root), env=environment)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the zcode IPC v1 sidecar")
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--pipe", default=r"\\.\pipe\zcode-control-core-v1")
    parser.add_argument("--sidecar", type=Path, help="launch this sidecar before testing")
    parser.add_argument(
        "--api-smoke",
        action="store_true",
        help="exercise registration, login, task creation, listing, and approvals through the IPC HTTP proxy",
    )
    args = parser.parse_args()

    child: subprocess.Popen[bytes] | None = None
    try:
        if args.sidecar:
            child = _spawn_sidecar(args.sidecar.resolve(), args.pipe, args.nonce)
        with _open_pipe(args.pipe) as stream:
            hello = _request(
                stream,
                {
                    "v": 1,
                    "id": 1,
                    "method": "hello",
                    "params": {"nonce": args.nonce, "client_versions": [1], "pid": os.getpid()},
                },
            )
            if not hello.get("ok"):
                raise RuntimeError(f"hello failed: {hello}")
            ping = _request(stream, {"v": 1, "id": 2, "method": "ipc.ping", "params": {}})
            health = _request(
                stream,
                {
                    "v": 1,
                    "id": 3,
                    "method": "http.request",
                    "params": {"method": "GET", "path": "/health"},
                },
            )
            api_smoke: dict[str, Any] | None = None
            next_id = 4
            if args.api_smoke:
                username = f"p4_{uuid.uuid4().hex[:12]}"
                password = "P4-test-password!"
                status, registered = _http_request(
                    stream,
                    next_id,
                    "POST",
                    "/api/v1/auth/register",
                    body={"username": username, "password": password},
                )
                next_id += 1
                if status != 201 or registered.get("success") is not True:
                    raise RuntimeError(f"registration failed: HTTP {status} {registered}")

                status, logged_in = _http_request(
                    stream,
                    next_id,
                    "POST",
                    "/api/v1/auth/login",
                    body={"username": username, "password": password},
                )
                next_id += 1
                if status != 200 or not logged_in.get("data", {}).get("token"):
                    raise RuntimeError(f"login failed: HTTP {status} {logged_in}")
                token = str(logged_in["data"]["token"])

                status, created = _http_request(
                    stream,
                    next_id,
                    "POST",
                    "/api/v1/tasks",
                    body={"goal": "Read the packaged P4 smoke workspace metadata", "edition": "enterprise"},
                    token=token,
                )
                next_id += 1
                if status != 201 or not created.get("data", {}).get("id"):
                    raise RuntimeError(f"task creation failed: HTTP {status} {created}")
                task_id = str(created["data"]["id"])

                status, listed = _http_request(stream, next_id, "GET", "/api/v1/tasks", token=token)
                next_id += 1
                if status != 200 or not any(item.get("id") == task_id for item in listed.get("data", {}).get("items", [])):
                    raise RuntimeError(f"task listing failed: HTTP {status} {listed}")

                status, approvals = _http_request(stream, next_id, "GET", "/api/v1/approvals", token=token)
                next_id += 1
                if status != 200 or not isinstance(approvals.get("data"), list):
                    raise RuntimeError(f"approval listing failed: HTTP {status} {approvals}")
                api_smoke = {
                    "username": username,
                    "registered": True,
                    "authenticated": True,
                    "task_id": task_id,
                    "task_created": True,
                    "task_listed": True,
                    "approvals_listed": True,
                }

            shutdown = _request(stream, {"v": 1, "id": next_id, "method": "ipc.shutdown", "params": {}})
        result = {"hello": hello, "ping": ping, "health": health, "shutdown": shutdown}
        if api_smoke is not None:
            result["api_smoke"] = api_smoke
        print(json.dumps(result))
    finally:
        if child is not None:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
