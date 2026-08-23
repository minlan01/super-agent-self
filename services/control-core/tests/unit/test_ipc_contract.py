"""Unit coverage for the formal Windows IPC v1 contract."""

from __future__ import annotations

import io
import struct
import urllib.error
from email.message import Message
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.platform.windows.sidecar_host import (
    HTTP_HEADER,
    IpcServer,
    IpcSession,
    MAX_FRAME_SIZE,
    ProtocolFailure,
    SidecarTokenGate,
    decode_frame,
    encode_frame,
)


def _server(**kwargs: Any) -> IpcServer:
    return IpcServer(
        http_port=49152,
        http_token="a" * 64,
        run_nonce="test-nonce",
        sidecar_pid=456,
        **kwargs,
    )


def _hello(server: IpcServer, session: IpcSession, **params: Any) -> dict[str, Any]:
    request = {
        "v": 1,
        "id": 1,
        "method": "hello",
        "params": {
            "nonce": "test-nonce",
            "client_versions": [1],
            "pid": session.peer_pid or 123,
            **params,
        },
    }
    return server.dispatch(request, session)


def test_frame_is_little_endian_utf8_json() -> None:
    frame = encode_frame({"v": 1, "message": "中文"})
    assert struct.unpack("<I", frame[:4])[0] == len(frame) - 4
    assert decode_frame(frame) == {"v": 1, "message": "中文"}


def test_decode_frame_rejects_missing_prefix() -> None:
    with pytest.raises(ProtocolFailure, match="length prefix"):
        decode_frame(b"{}")


def test_decode_frame_rejects_length_mismatch() -> None:
    with pytest.raises(ProtocolFailure, match="length does not match"):
        decode_frame(struct.pack("<I", 9) + b"{}")


def test_decode_frame_rejects_oversized_payload() -> None:
    with pytest.raises(ProtocolFailure) as exc_info:
        decode_frame(struct.pack("<I", MAX_FRAME_SIZE + 1))
    assert exc_info.value.code == "E_MSG_TOO_LARGE"


def test_hello_succeeds_with_matching_nonce_version_and_peer() -> None:
    response = _hello(_server(), IpcSession(peer_pid=123))
    assert response["ok"] is True
    assert response["data"] == {
        "version": 1,
        "http_port": 49152,
        "http_token": "a" * 64,
        "sidecar_pid": 456,
        "schema_version": "1.0.0",
    }


def test_hello_rejects_wrong_nonce() -> None:
    response = _hello(_server(), IpcSession(peer_pid=123), nonce="wrong")
    assert response["error"]["code"] == "E_NONCE_MISMATCH"


def test_hello_rejects_no_shared_version() -> None:
    response = _hello(_server(), IpcSession(peer_pid=123), client_versions=[99])
    assert response["error"]["code"] == "E_VERSION"


def test_hello_rejects_mismatched_claimed_pid() -> None:
    response = _hello(_server(), IpcSession(peer_pid=123), pid=456)
    assert response["error"]["code"] == "E_PEER_DENIED"


def test_non_handshake_request_is_rejected_before_hello() -> None:
    response = _server().dispatch(
        {"v": 1, "id": 1, "method": "ipc.ping", "params": {}},
        IpcSession(peer_pid=123),
    )
    assert response["error"]["code"] == "E_HANDSHAKE_REQUIRED"


def test_ping_reports_uptime_after_hello() -> None:
    server = _server()
    session = IpcSession(peer_pid=123)
    assert _hello(server, session)["ok"] is True
    response = server.dispatch({"v": 1, "id": 2, "method": "ipc.ping", "params": {}}, session)
    assert response["data"]["pong"] is True
    assert response["data"]["uptime_s"] >= 0


def test_unknown_method_is_rejected() -> None:
    server = _server()
    session = IpcSession(peer_pid=123)
    _hello(server, session)
    response = server.dispatch({"v": 1, "id": 2, "method": "unknown", "params": {}}, session)
    assert response["error"]["code"] == "E_UNKNOWN_METHOD"


def test_shutdown_sets_stop_event() -> None:
    server = _server()
    session = IpcSession(peer_pid=123)
    _hello(server, session)
    response = server.dispatch({"v": 1, "id": 2, "method": "ipc.shutdown", "params": {}}, session)
    assert response["data"] == {"bye": True}
    assert server.stop_event.is_set()


class _FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b'{"status":"ok"}') -> None:
        self.status = status
        self.headers = {"content-type": "application/json"}
        self._body = body

    def read(self, _limit: int) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status


def test_http_proxy_injects_internal_token_and_preserves_business_authorization() -> None:
    captured: dict[str, Any] = {}

    def opener(request, timeout: float):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse()

    server = _server(proxy_opener=opener)
    session = IpcSession(peer_pid=123)
    _hello(server, session)
    response = server.dispatch(
        {
            "v": 1,
            "id": 2,
            "method": "http.request",
            "params": {
                "method": "POST",
                "path": "/api/v1/tasks",
                "headers": {"Authorization": "Bearer business-jwt", HTTP_HEADER: "attacker"},
                "body": {"goal": "test"},
                "request_id": "req-123",
            },
        },
        session,
    )
    headers = {key.lower(): value for key, value in captured["request"].header_items()}
    assert response["data"]["status"] == 200
    assert headers["authorization"] == "Bearer business-jwt"
    assert headers[HTTP_HEADER.lower()] == "a" * 64
    assert headers["x-request-id"] == "req-123"
    assert captured["request"].full_url == "http://127.0.0.1:49152/api/v1/tasks"


def test_http_proxy_returns_http_error_as_data() -> None:
    headers = Message()
    headers["content-type"] = "application/json"
    failure = urllib.error.HTTPError(
        "http://127.0.0.1:49152/health",
        401,
        "Unauthorized",
        headers,
        io.BytesIO(b'{"detail":"sidecar token required"}'),
    )

    def opener(_request, timeout: float):
        raise failure

    server = _server(proxy_opener=opener)
    session = IpcSession(peer_pid=123)
    _hello(server, session)
    response = server.dispatch(
        {"v": 1, "id": 2, "method": "http.request", "params": {"path": "/health"}},
        session,
    )
    assert response["ok"] is True
    assert response["data"]["status"] == 401
    assert "sidecar token required" in response["data"]["body"]


def test_sidecar_token_gate_requires_its_dedicated_header() -> None:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(SidecarTokenGate(app, "internal-token")) as client:
        assert client.get("/health").status_code == 401
        assert client.get("/health", headers={HTTP_HEADER: "internal-token"}).json() == {"status": "ok"}
