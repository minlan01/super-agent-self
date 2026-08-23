"""Windows subprocess coverage for the real control-core sidecar."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from packages.platform.windows.sidecar_host import MAX_FRAME_SIZE, decode_frame, encode_frame

pytestmark = [pytest.mark.integration, pytest.mark.skipif(sys.platform != "win32", reason="Windows Named Pipe")]

CONTROL_CORE = Path(__file__).resolve().parents[2]
SIDECAR_ENTRY = CONTROL_CORE / "scripts" / "nuitka-build" / "control_core_sidecar.py"
SMOKE_CLIENT = CONTROL_CORE / "scripts" / "nuitka-build" / "smoke_client.py"


class PipeClient:
    def __init__(self, handle: Any) -> None:
        self.handle = handle

    @classmethod
    def connect(cls, pipe_path: str, timeout: float = 20.0) -> "PipeClient":
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
                return cls(handle)
            except pywintypes.error as exc:
                if getattr(exc, "winerror", None) in {2, 231}:
                    time.sleep(0.05)
                    continue
                raise
        raise TimeoutError(f"sidecar pipe was not ready: {pipe_path}")

    def read_exact(self, size: int) -> bytes:
        import win32file

        chunks: list[bytes] = []
        remaining = size
        while remaining:
            status, data = win32file.ReadFile(self.handle, remaining)
            if status:
                raise OSError(f"Named Pipe ReadFile returned status {status}")
            chunk = bytes(data)
            if not chunk:
                raise ConnectionError("sidecar closed the pipe")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def request(self, message: dict[str, Any]) -> dict[str, Any]:
        import win32file

        win32file.WriteFile(self.handle, encode_frame(message))
        header = self.read_exact(4)
        size = int.from_bytes(header, "little")
        assert size <= MAX_FRAME_SIZE
        return decode_frame(header + self.read_exact(size))

    def write_raw(self, data: bytes) -> None:
        import win32file

        win32file.WriteFile(self.handle, data)

    def close(self) -> None:
        import win32file

        win32file.CloseHandle(self.handle)


@dataclass
class RunningSidecar:
    process: subprocess.Popen[bytes]
    pipe_path: str
    nonce: str
    data_dir: Path
    log_path: Path

    def connect(self) -> PipeClient:
        return PipeClient.connect(self.pipe_path)

    def hello(self, client: PipeClient, request_id: int = 1) -> dict[str, Any]:
        return client.request(
            {
                "v": 1,
                "id": request_id,
                "method": "hello",
                "params": {
                    "nonce": self.nonce,
                    "client_versions": [1],
                    "pid": os.getpid(),
                },
            }
        )

    def log_text(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace") if self.log_path.exists() else ""


@pytest.fixture
def sidecar(tmp_path: Path):
    nonce = uuid.uuid4().hex
    pipe_path = rf"\\.\pipe\zcode-control-core-v1-pytest-{uuid.uuid4().hex}"
    data_dir = tmp_path / "appdata"
    log_path = tmp_path / "sidecar.log"
    environment = os.environ.copy()
    environment.update(
        {
            "ZCODE_RUN_NONCE": nonce,
            "ZCODE_LAUNCHER_PID": str(os.getpid()),
            "ZCODE_PIPE": pipe_path,
            "ZCODE_DATA_DIR": str(data_dir),
            "TESTING": "1",
            "LLM_PROVIDER": "mock",
            "PYTHONUNBUFFERED": "1",
        }
    )
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [sys.executable, str(SIDECAR_ENTRY)],
            cwd=CONTROL_CORE,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        running = RunningSidecar(process, pipe_path, nonce, data_dir, log_path)
        try:
            yield running
        finally:
            if process.poll() is None:
                try:
                    client = running.connect()
                    try:
                        if running.hello(client).get("ok"):
                            client.request({"v": 1, "id": 2, "method": "ipc.shutdown", "params": {}})
                    finally:
                        client.close()
                    process.wait(timeout=12)
                except Exception:
                    process.kill()
                    process.wait(timeout=5)


def test_pipe_handshake_ping_http_gate_and_migrated_database(sidecar: RunningSidecar) -> None:
    client = sidecar.connect()
    try:
        hello = sidecar.hello(client)
        assert hello["ok"] is True
        assert hello["data"]["version"] == 1
        ping = client.request({"v": 1, "id": 2, "method": "ipc.ping", "params": {}})
        assert ping["data"]["pong"] is True

        port = hello["data"]["http_port"]
        token = hello["data"]["http_token"]
        with pytest.raises(urllib.error.HTTPError) as unauthenticated:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3)
        assert unauthenticated.value.code == 401
        direct = urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:{port}/health",
                headers={"X-Zcode-Sidecar-Token": token},
            ),
            timeout=3,
        )
        assert json.loads(direct.read().decode("utf-8"))["status"] == "ok"

        proxied = client.request(
            {
                "v": 1,
                "id": 3,
                "method": "http.request",
                "params": {"method": "GET", "path": "/health"},
            }
        )
        assert proxied["data"]["status"] == 200
        assert json.loads(proxied["data"]["body"])["status"] == "ok"
    finally:
        client.close()

    database = sidecar.data_dir / "agent_platform.db"
    assert database.is_file(), sidecar.log_text()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()


def test_wrong_nonce_is_rejected_without_stopping_the_server(sidecar: RunningSidecar) -> None:
    wrong_client = sidecar.connect()
    try:
        rejected = wrong_client.request(
            {
                "v": 1,
                "id": 1,
                "method": "hello",
                "params": {"nonce": "wrong", "client_versions": [1], "pid": os.getpid()},
            }
        )
        assert rejected["error"]["code"] == "E_NONCE_MISMATCH"
    finally:
        wrong_client.close()

    valid_client = sidecar.connect()
    try:
        assert sidecar.hello(valid_client)["ok"] is True
    finally:
        valid_client.close()


def test_wrong_same_user_process_is_rejected_by_peer_pid(sidecar: RunningSidecar) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SMOKE_CLIENT),
            "--nonce",
            sidecar.nonce,
            "--pipe",
            sidecar.pipe_path,
        ],
        cwd=CONTROL_CORE,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode != 0
    assert "E_PEER_DENIED" in (completed.stdout + completed.stderr)

    valid_client = sidecar.connect()
    try:
        assert sidecar.hello(valid_client)["ok"] is True
    finally:
        valid_client.close()


def test_oversized_frame_returns_contract_error_and_server_recovers(sidecar: RunningSidecar) -> None:
    client = sidecar.connect()
    try:
        assert sidecar.hello(client)["ok"] is True
        client.write_raw((MAX_FRAME_SIZE + 1).to_bytes(4, "little"))
        header = client.read_exact(4)
        rejected = decode_frame(header + client.read_exact(int.from_bytes(header, "little")))
        assert rejected["error"]["code"] == "E_MSG_TOO_LARGE"
    finally:
        client.close()

    valid_client = sidecar.connect()
    try:
        assert sidecar.hello(valid_client)["ok"] is True
    finally:
        valid_client.close()


def test_shutdown_returns_ack_and_exits_cleanly(sidecar: RunningSidecar) -> None:
    client = sidecar.connect()
    try:
        assert sidecar.hello(client)["ok"] is True
        response = client.request({"v": 1, "id": 2, "method": "ipc.shutdown", "params": {}})
        assert response["data"] == {"bye": True}
    finally:
        client.close()
    assert sidecar.process.wait(timeout=12) == 0, sidecar.log_text()


def test_real_api_auth_task_and_approval_surface(sidecar: RunningSidecar) -> None:
    """Exercise the real control-core API through the IPC HTTP proxy."""

    client = sidecar.connect()
    try:
        assert sidecar.hello(client)["ok"] is True

        def request(
            method: str,
            path: str,
            *,
            body: dict[str, Any] | None = None,
            token: str | None = None,
        ) -> tuple[int, dict[str, Any]]:
            headers = {"Accept": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            response = client.request(
                {
                    "v": 1,
                    "id": int(time.monotonic_ns() % 2_000_000_000),
                    "method": "http.request",
                    "params": {
                        "method": method,
                        "path": path,
                        "headers": headers,
                        "body": body,
                    },
                }
            )
            assert response["ok"] is True, response
            data = response["data"]
            return int(data["status"]), json.loads(data["body"] or "{}")

        username = f"p4_{uuid.uuid4().hex[:12]}"
        status, registered = request(
            "POST",
            "/api/v1/auth/register",
            body={"username": username, "password": "P4-test-password!"},
        )
        assert status == 201, registered
        assert registered["success"] is True

        status, logged_in = request(
            "POST",
            "/api/v1/auth/login",
            body={"username": username, "password": "P4-test-password!"},
        )
        assert status == 200, logged_in
        token = logged_in["data"]["token"]
        assert isinstance(token, str) and token

        status, created = request(
            "POST",
            "/api/v1/tasks",
            body={"goal": "Read the P4 smoke workspace metadata", "edition": "enterprise"},
            token=token,
        )
        assert status == 201, created
        task_id = created["data"]["id"]
        assert created["data"]["status"] == "pending"

        status, listed = request("GET", "/api/v1/tasks", token=token)
        assert status == 200, listed
        assert any(item["id"] == task_id for item in listed["data"]["items"])

        status, approvals = request("GET", "/api/v1/approvals", token=token)
        assert status == 200, approvals
        assert isinstance(approvals["data"], list)
    finally:
        client.close()
