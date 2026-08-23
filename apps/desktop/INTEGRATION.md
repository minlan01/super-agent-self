# Zcode Desktop Agent - Control-core Sidecar Integration

**Date:** 2026-08-20
**Protocol:** IPC v1
**Status:** real sidecar and IPC v1 are implemented and verified on the current host; manual UI, second-account and clean-OS acceptance remain separate gates.

## Architecture

```text
Tauri desktop shell
  -> Windows Job Object owns sidecar process tree
  -> \\.\pipe\zcode-control-core-v1
  -> IPC v1 hello/ping/http.request/shutdown
  -> control-core sidecar
  -> 127.0.0.1:<random port> FastAPI application
  -> %LOCALAPPDATA%\zcode\agent_platform.db
```

The pipe uses a current-user-only DACL and validates the connecting process PID
against `ZCODE_LAUNCHER_PID`. The desktop shell creates a fresh 256-bit run
nonce each launch, completes `hello` and `ipc.ping` before declaring readiness,
and serializes v1 requests on one persistent pipe session.

The loopback API is not exposed to the WebView. The sidecar requires an internal
`X-Zcode-Sidecar-Token`; `http_via_sidecar` keeps that token in Rust and
preserves any business `Authorization` header for the normal API authentication
layer.

## Source Layout

- Contract: `services/control-core/docs/contracts/ipc-v1.md`
- Sidecar host: `services/control-core/packages/platform/windows/sidecar_host.py`
- Nuitka entry point: `services/control-core/scripts/nuitka-build/control_core_sidecar.py`
- Smoke client: `services/control-core/scripts/nuitka-build/smoke_client.py`
- Rust owner: `apps/desktop/src-tauri/src/lib.rs`

## Build

```powershell
Set-Location D:\agent\Agents\super-agent-self\services\control-core\scripts\nuitka-build
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1

Set-Location D:\agent\Agents\super-agent-self\apps\desktop
npm.cmd run build
npm.cmd run tauri -- build --bundles nsis --ci
```

`build.ps1` installs the locked Windows runtime plus Nuitka dependencies, builds
the real entry point, and replaces `apps/desktop/src-tauri/resources/sidecar/`
with the generated standalone distribution.

## Source Smoke Test

The smoke client launches the sidecar itself so its PID is the registered
launcher. This is deliberate: a separately launched arbitrary process must be
rejected by the peer-PID check.

```powershell
Set-Location D:\agent\Agents\super-agent-self\services\control-core
.\.venv-win\Scripts\python.exe .\scripts\nuitka-build\smoke_client.py `
  --nonce p4-manual-smoke `
  --pipe '\\.\pipe\zcode-control-core-v1-manual' `
  --sidecar .\scripts\nuitka-build\control_core_sidecar.py
```

Expected result: JSON containing successful `hello`, `ipc.ping`, `GET /health`,
and `ipc.shutdown` responses.

## Remaining Acceptance Boundaries

- A clean installed NSIS artifact has been exercised with the packaged sidecar;
  the latest machine-readable evidence is under
  `services/control-core/artifacts/p4-final-release-suite-2026-08-20/`.
- Final suite startup was `4.659s`, `4.757s`, and `4.949s`; all three runs
  satisfied the 5-second gate.
- A second ordinary local Windows account must demonstrate DACL rejection with
  Win32 error 5.
- Manual UI acceptance must verify login, task creation/execution/cancel and
  approval actions.
- Desktop lifecycle acceptance has verified normal close, forced parent cleanup,
  three sidecar restarts, and fourth-crash cutoff against the new pipe protocol.
- Product version remains `0.1.0` until these gates and the broader v1.0 release
  blockers are actually complete. No commit or push was performed.
