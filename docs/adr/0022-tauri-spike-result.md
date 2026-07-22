# ADR-022: Tauri Spike Result

**Status:** Accepted / P-1 complete with documented waiver  
**Date:** 2026-07-22

## Context

P-1 was intended to freeze desktop-shell and Python-delivery choices using real Windows measurements from the manual checklist.

## Result

The spike demonstrates a viable local deployment path:

- Tauri release UI and commands: PASS.
- Python 3.12 Nuitka standalone startup maximum: `3.804s`, PASS.
- Rust-to-Python Named Pipe P95: `2.997ms`, PASS.
- Forced parent cleanup, normal close cleanup, and bounded crash recovery: PASS.
- Current-user NSIS resources, install, 0.1.0 to 0.1.1 upgrade, and uninstall: PASS.
- Temporary Authenticode signing and tamper detection: PASS mechanism.

Accepted exception and follow-up:

- Official demo second command-to-window: `15.380s`, WAIVED against `<10s` by the project owner on 2026-07-22; not relabeled as PASS.
- No clean Windows 10 22H2 missing-WebView2 online/offline test.
- No production signing or timestamping.
- Production IPC ACL/timeout/concurrency and live-unhealthy hardening remain.
- Git commit/push is `N/A` because this Windows spike workspace is intentionally not a Git repository.

## Decision

Record **GO with follow-up**. Enter P0 with Tauri 2 and the Python 3.12 Nuitka standalone sidecar. Accept the P-1.1 development-startup waiver and the P-1.5 Git `N/A` disposition. Do not switch to Electron based on current data.

## Alternatives Considered

- GO with documented exception: selected because all product-facing hard metrics and the installed delivery path pass.
- Immediate Electron switch: rejected because final Tauri packaging, runtime startup, IPC, lifecycle, install, upgrade, and uninstall all work locally.
- HOLD pending optional VM/signing work: rejected because those items are release follow-up under the approved P-1 disposition.

## Consequences

- The former onefile startup blocker is closed by Nuitka standalone.
- P0 can begin; follow-up work is target validation, signing, and hardening rather than architecture discovery.
- Raw evidence is retained under `D:\agent\evidence\p1-2026-07-22`.
- The full report and reproduction commands are in `D:\agent\RESULT.md`.

## Required Follow-up

1. Test the installer with WebView2 absent on clean Windows 10 22H2, including offline failure behavior.
2. Re-run the artifact suite on the supported Windows matrix.
3. Production-sign and timestamp the shell, sidecar, and installer.
4. Complete IPC, endpoint, health-monitor, Job Object startup-race, and Tauri capability hardening.
5. Transfer these handoff artifacts to the consuming project without requiring this workspace to become a Git repository.

## Reconsideration

Start an Electron spike only if the target-OS follow-up exposes an unresolvable Tauri/WebView2 or updater limitation, or if the remaining hardening cannot meet the product schedule.
