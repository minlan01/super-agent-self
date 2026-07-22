# Tauri Sidecar Spike

This is the executable P-1 spike summarized in `D:\agent\RESULT.md`.

## Layout

- `src-tauri/src/lib.rs` - Tauri commands, sidecar supervisor, Job Object, bounded restarts, instance identity, and Named Pipe client.
- `sidecar.py` - standard-library HTTP health and Windows Named Pipe server.
- `scripts/prepare-sidecar.ps1` - stages a Nuitka standalone directory into the Tauri bundle resources.
- `tests/run_artifact_suite.ps1` - reruns startup, lifecycle, PowerShell IPC, and Rust IPC against one artifact and saves JSON evidence.
- `tests/test_authenticode.ps1` - temporary certificate, signature, tamper, and cleanup test.

## Toolchain

- Node `24.18.0` (`.node-version`)
- Rust `1.97.1` (`rust-toolchain.toml`)
- Python `3.12.10` (`D:\agent\sidecar-demo\.python-version`)
- Nuitka `4.1.3` and PyInstaller `6.21.0` (`D:\agent\sidecar-demo\requirements-build.lock`)

Use `npm.cmd` because this machine's PowerShell policy blocks `npm.ps1`.

## Build The Sidecar

```powershell
cd D:\agent\sidecar-demo
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1

cd D:\agent\tauri-spike
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-sidecar.ps1
```

The bundle input is the entire `sidecar.dist` directory, not only `sidecar.exe`.

## Build Tauri

```powershell
cd D:\agent\tauri-spike
npm.cmd ci
npm.cmd run build
cargo check --offline --manifest-path .\src-tauri\Cargo.toml
npm.cmd run tauri -- build --bundles nsis
```

Do not replace the final command with plain `cargo build --release`; the Tauri CLI embeds frontend and bundle resources. The NSIS configuration installs for the current user and downloads the WebView2 Evergreen Bootstrapper silently when needed.

## Verify The Final Artifact

Run from a normal PowerShell session because the lifecycle test needs process and listener ownership information:

```powershell
cd D:\agent\tauri-spike
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\run_artifact_suite.ps1 `
  -Sidecar D:\agent\sidecar-demo\dist-final\sidecar.dist\sidecar.exe
```

Evidence is written to `D:\agent\evidence\p1-2026-07-22`.

## Current Decision

Nuitka standalone on Python 3.12 meets the 5-second startup target and passes lifecycle plus IPC tests. Current-user NSIS install, 0.1.0 to 0.1.1 upgrade, installed execution, and uninstall also pass on this host. P-1 is accepted as GO with follow-up: the project owner approved a documented waiver for the official-demo `<10s` development-startup miss, and Git commit/push is `N/A` for this non-repository workspace. Clean Windows 10 22H2, production signing, and hardening remain release follow-up.
