# ADR-010: Windows P1 Native Platform Implementation

**Status:** Accepted with explicit limitations
**Date:** 2026-07-23

## Context

The P1 Windows implementation manual requires the four native control-core
capabilities from the P0.2 contracts: authenticated local IPC, OS secret
storage, interactive-session monitoring, and process isolation. The source
checkout already contains the shared contracts and protocol schemas; the
Windows modules must not replace those definitions or make the protocol layer
depend on the platform layer.

## Decision

Add `packages.platform.windows` with lazy Win32 imports and the following
implementations:

- `WindowsNamedPipeIpc`: protected current-user SID DACL, peer SID verification,
  schema/nonce negotiation, strict sequence numbers, 10 MiB frame limit, and
  100 requests/second per-connection limit. Async handlers are dispatched back
  to the serving event loop; the Python client side is intentionally unavailable
  because the desktop client is implemented in Rust.
- `WindowsCredentialStore`: binary Credential Manager blobs with fail-closed
  errors and upsert rotation; no plaintext file, registry, or database fallback.
- `WindowsSessionMonitor`: WTS console/session queries and input-desktop lock
  detection with a bounded polling callback loop. Unknown state is locked and
  inactive.
- `WindowsProcessSandbox`: per-run Job Object with kill-on-close, process-count,
  memory, CPU, timeout, and output limits. Children are created suspended,
  assigned by process HANDLE, then resumed. Unsupported filesystem, identity,
  capability, syscall, and egress policy fields fail closed.
- `WindowsPlatformAdapter`: capability discovery for the four P1 components;
  P2-P4 interfaces report `CapabilityUnavailable`.

IPC wire helpers remain inside `platform.windows.local_ipc`; the protocol leaf
is not modified and does not import the platform layer.

## Limitations

Windows Job Objects do not enforce filesystem ACLs or network egress policy.
The sandbox rejects those requested policy fields instead of claiming that they
are enforced. A future AppContainer or egress broker is required before those
controls can be marked complete. WTS notifications currently use bounded
polling and are not wired to Grant revocation; Win+L lock/unlock verification
remains a manual interactive check. A second local-account adversarial pipe
connection was not run because no authorized credentials or elevated account
creation were available.

## Verification

The implementation is covered by contract/wire tests and Windows API tests in
`services/control-core/packages/platform/windows/tests/`. Python 3.12.10 with
pywin32 312 ran **106 passed, 4 skipped** (110 collected); Python 3.14.6 also
ran the same result. Evidence is written outside the Git worktree under
`D:\agent\evidence\p1-windows-real`.
