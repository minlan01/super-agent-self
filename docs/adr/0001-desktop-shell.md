# ADR-001: Desktop Shell

**Status:** Accepted with follow-up  
**Date:** 2026-07-22

## Context

The desktop Agent needs a small Windows shell that renders a local UI, invokes native commands, supervises a Python core, and ships through a signed installer. P-1 tested Tauri 2 with WebView2, a Python sidecar, and a real current-user NSIS package.

## Decision

Adopt Tauri 2 as the desktop shell for entry into P0.

The release UI and commands work, the NSIS bundle includes and resolves the complete sidecar directory, and install/upgrade/uninstall passed on the current host. The project owner approved a documented waiver for the untouched demo's `15.380s` development-only startup because the installed product starts in `3.595s`. Clean Windows 10 22H2 validation remains a release follow-up.

## Evidence

- Final installed app startup: `3.595s`.
- Final sidecar startup suite maximum: `3.804s` across five runs.
- Rust-to-Python Named Pipe P95: `2.997ms` across 100 requests.
- Current-user NSIS install, 0.1.0 to 0.1.1 upgrade, and uninstall: PASS.
- Forced parent cleanup, normal close cleanup, three crash restarts, and fourth-crash cutoff: PASS.
- Official demo second command-to-window: `15.380s`, WAIVED against the manual target; the value remains recorded as a miss.
- Clean Windows 10 22H2 missing-runtime path: not tested.

Full measurements are in `D:\agent\RESULT.md`.

## Accepted Exception

On 2026-07-22 the project owner approved the P-1.1 `<10s` development-startup exception. This waiver does not change the measurement to PASS and does not relax the installed-product startup requirement.

## Alternatives

- Electron plus Node sidecar: larger runtime, mature process and installer tooling.
- Native WinUI/WPF: stronger Windows integration, higher cross-platform cost.
- Tauri plus a non-Python core: smaller delivery surface, larger core rewrite cost.

## Consequences

- P0 may proceed with Tauri 2.
- Production builds must use the Tauri CLI, not plain `cargo build --release`.
- Installer configuration remains current-user NSIS with explicit WebView2 bootstrap handling.
- Production capabilities must replace `csp: null` and remove unused opener permission.
- Release binaries and installer require production signing and timestamping.

## Required Follow-Up

1. Install and run the bundled application on clean Windows 10 22H2 with WebView2 absent, covering online and offline behavior.
2. Re-run final artifact startup/lifecycle/IPC checks on the supported target OS matrix.
3. Validate production signatures and timestamps for shell, sidecar, and installer.
4. Tighten CSP and remove unused Tauri permissions before release.

## Reconsideration Triggers

Start an Electron spike if target-OS testing exposes a Tauri/WebView2 blocker that cannot be closed in the allocated follow-up, or if the updater cannot safely deliver the standalone sidecar directory atomically.
