"""Protocol and endpoint validation tests for the Named Pipe adapter."""

from __future__ import annotations

import json

import pytest

from packages.platform.shared.contracts import IpcEndpoint
from packages.platform.shared.errors import IpcAuthError
from packages.platform.windows._errors import IpcProtocolError
from packages.platform.windows.local_ipc import (
    MAX_MESSAGE_SIZE,
    WindowsNamedPipeIpc,
    _decode_frame,
    _encode_frame,
    _endpoint_address,
    _validate_handshake,
    _validate_request,
)
from packages.protocol.schemas.enums import SCHEMA_VERSION


def test_frame_round_trip_is_bounded_json() -> None:
    value = {"ok": True, "text": "中文-safe UTF-8", "seq": 1}
    assert _decode_frame(_encode_frame(value)) == value
    assert len(_encode_frame(value)) < MAX_MESSAGE_SIZE


def test_frame_rejects_non_object_and_oversize() -> None:
    with pytest.raises(IpcProtocolError):
        _encode_frame(["not", "an", "object"])  # type: ignore[arg-type]
    with pytest.raises(IpcProtocolError):
        _decode_frame(json.dumps("not an object").encode())
    with pytest.raises(IpcProtocolError):
        _encode_frame({"data": "x" * MAX_MESSAGE_SIZE})


def test_handshake_binds_nonce_and_schema() -> None:
    nonce = "instance-nonce"
    normalized = _validate_handshake(
        {"protocol_version": SCHEMA_VERSION, "nonce": nonce},
        expected_nonce=nonce,
    )
    assert normalized["max_message_size"] == MAX_MESSAGE_SIZE
    with pytest.raises(IpcAuthError):
        _validate_handshake(
            {"protocol_version": SCHEMA_VERSION, "nonce": "other"},
            expected_nonce=nonce,
        )


def test_request_nonce_and_sequence_are_strict() -> None:
    assert _validate_request({"nonce": "n", "seq": 1}, nonce="n", last_seq=0) == 1
    with pytest.raises(IpcAuthError):
        _validate_request({"nonce": "n", "seq": 3}, nonce="n", last_seq=1)
    with pytest.raises(IpcAuthError):
        _validate_request({"nonce": "wrong", "seq": 2}, nonce="n", last_seq=1)


def test_endpoint_validation_uses_real_contract() -> None:
    endpoint = IpcEndpoint(
        transport="named_pipe",
        address=r"\\.\pipe\zcode-control-core",
        peer_sid="S-1-5-21",
    )
    assert _endpoint_address(endpoint) == (endpoint.address, endpoint.peer_sid)
    assert _endpoint_address(endpoint.address) == (endpoint.address, None)
    with pytest.raises(ValueError):
        _endpoint_address(IpcEndpoint(transport="uds", address="/tmp/control.sock"))


def test_unknown_peer_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="fail-closed"):
        WindowsNamedPipeIpc(allow_unknown_peer=True)
