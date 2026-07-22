# ADR-002: Python Core Delivery As A Sidecar

**Status:** Accepted with follow-up  
**Date:** 2026-07-22

## Context

The existing core is Python. The shell must start it deterministically, prove readiness and instance ownership, communicate locally, recover from crashes, and remove descendants when the shell exits or is killed.

## Decision

Package the Python 3.12 core as a Nuitka standalone directory bundled as a Tauri resource and supervised by Rust. Use:

- a Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`;
- shutdown gating and a maximum of three crash restarts;
- a per-run nonce plus PID in health responses;
- nonce-bound local Named Pipe request/response IPC;
- direct `.exe` execution for packaged artifacts and Python only for development `.py` files.

Adopt this delivery model for P0. Clean Windows 10 testing, production signing, and IPC hardening remain release follow-up rather than P-1 acceptance blockers.

## Evidence

- Python 3.12.10 and Nuitka 4.1.3 standalone directory: 17 files, `20.427MB`.
- Five final Tauri startup runs: max `3.804s`, all `<=5s`.
- PowerShell Named Pipe P95: `1.032ms`; Rust P95: `2.997ms`.
- Forced-parent cleanup and normal-close cleanup: PASS.
- First three sidecar crashes restarted; the fourth did not restart: PASS.
- Installed app resolved bundled resources without sidecar environment variables: PASS.
- NSIS install, real version upgrade, and uninstall: PASS on the current host.

PyInstaller onefile and onedir were rejected for this candidate because their recorded cold maxima were `7.996s` and `6.258s` respectively.

## Alternatives

- PyInstaller onefile: smallest operational layout, failed the 5-second maximum.
- PyInstaller onedir: simpler toolchain, still had a 6.258-second cold sample.
- Standard input/output IPC: simpler access control, tighter coupling to one transport connection.
- Node or Rust core: removes Python distribution, requires a larger core rewrite.

## Consequences

- The entire standalone directory is one versioned deployment unit; copying only `sidecar.exe` is invalid.
- Installer/updater changes must replace that directory atomically.
- Fixed endpoint names remain an operational constraint even though nonce/PID checks prevent cross-instance confusion.
- Explicit pipe ACLs, hard I/O timeouts, live-unhealthy detection, and concurrency limits remain production work.
- The current spawn-then-assign Job Object sequence has a small startup race that requires hardening or a documented risk decision.

## Required Follow-Up

1. Re-run startup, cleanup, restart, and IPC gates against the installed artifact on clean Windows 10 22H2 and supported Windows 11.
2. Add explicit single-instance behavior or per-user endpoint names and local-user pipe ACLs.
3. Add hard IPC timeouts plus malformed, oversized, concurrent, disconnect, idle-client, and hung-sidecar tests.
4. Detect and recover from a live sidecar whose IPC thread is unhealthy.
5. Sign and timestamp the final sidecar with the production certificate.

## Rollback / Reconsideration

Reconsider the packaging mode if Nuitka cannot compile the real core or updater size/atomicity becomes unacceptable. Reconsider Python-as-sidecar if process supervision and IPC hardening cost exceeds a Node/Rust core migration spike.
