# zcode-control-core IPC v1

## Endpoint and framing

- Default pipe: `\\.\pipe\zcode-control-core-v1`
- Transport: local Windows Named Pipe, duplex, message-type pipe, byte-read mode
- Peer policy: protected DACL grants the current Windows user only; the server then
  verifies the connecting process PID against `ZCODE_LAUNCHER_PID`
- Framing: `4-byte little-endian unsigned length` followed by UTF-8 JSON bytes
- Maximum encoded JSON payload: `1 MiB` (`1048576` bytes)
- Every response echoes the request `id` when one is available

The length prefix is the application boundary. The underlying message-type pipe is
configured for byte reads so a frame can be read incrementally without relying on
message boundaries.

## Handshake

The first request on every connection **must** be:

```json
{
  "v": 1,
  "id": 1,
  "method": "hello",
  "params": {
    "nonce": "<run nonce>",
    "client_versions": [1],
    "pid": 123
  }
}
```

The server validates the nonce, the version intersection, and that `pid` matches
the Windows Named Pipe client PID. A successful response is:

```json
{
  "v": 1,
  "id": 1,
  "ok": true,
  "data": {
    "version": 1,
    "http_port": 49152,
    "http_token": "<64 hex characters>",
    "sidecar_pid": 456,
    "schema_version": "1.0.0"
  }
}
```

The token is an internal sidecar credential. It must never be exposed to the
WebView or used in place of the business `Authorization` header.

## Methods

After a successful handshake, the following methods are available:

### `ipc.ping`

```json
{"v":1,"id":2,"method":"ipc.ping","params":{}}
```

Response data:

```json
{"pong":true,"uptime_s":0.123}
```

### `http.request`

```json
{
  "v": 1,
  "id": 3,
  "method": "http.request",
  "params": {
    "method": "GET",
    "path": "/health",
    "headers": {"Accept": "application/json"},
    "body": null,
    "request_id": "optional-correlation-id"
  }
}
```

The sidecar constructs the destination as `http://127.0.0.1:<http_port><path>`
and injects `X-Zcode-Sidecar-Token`. Caller-supplied `Authorization` is preserved
for the API's normal JWT/session checks. The response data is:

```json
{
  "status": 200,
  "body": "{\"status\":\"ok\"}",
  "headers": {"content-type": "application/json"}
}
```

HTTP status codes are returned as data, not converted into IPC failures. This
preserves API `401`, `403`, `404`, `409`, `422`, and `500` semantics for the UI.

### `ipc.shutdown`

The sidecar replies with `{"bye":true}` and then closes its HTTP server and pipe
listener. It is intended for an orderly Tauri close; process termination remains
covered by the Windows Job Object.

## Error codes

An IPC failure has `ok: false` and an `error.code`:

| Code | Meaning |
|---|---|
| `E_NONCE_MISMATCH` | Run nonce is missing or does not match |
| `E_VERSION` | No supported protocol version is shared |
| `E_PEER_DENIED` | Same-user process PID is not the registered launcher |
| `E_UNKNOWN_METHOD` | Method is not part of this contract |
| `E_HANDSHAKE_REQUIRED` | A non-`hello` request arrived before handshake |
| `E_BAD_REQUEST` | Request fields are malformed or invalid |
| `E_BAD_JSON` | Frame is not valid UTF-8 JSON object |
| `E_MSG_TOO_LARGE` | Length or payload exceeds `1 MiB` |
| `E_INTERNAL` | Sidecar or HTTP proxy failed internally |
| `E_SHUTTING_DOWN` | A request arrived after shutdown began |

When a different local Windows account connects, the DACL rejects the connection
before an application response can be written; the expected evidence is Win32
`ERROR_ACCESS_DENIED` (5), not an `E_PEER_DENIED` response.
