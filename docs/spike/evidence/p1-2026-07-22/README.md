# P-1 Evidence Index

- `tauri-demo-first.*.log` - untouched official demo first compile/run output.
- `tauri-demo-incremental-*.log` and `tauri-demo-timings.json` - controlled incremental timing evidence.
- `nuitka-startup.json` - five final Tauri-to-sidecar startup samples.
- `nuitka-lifecycle.json` - forced kill, normal close, restart PIDs, and fourth-crash cutoff.
- `nuitka-ipc-powershell.json` - 100 PowerShell Named Pipe samples.
- `nuitka-ipc-rust.json` - 100 Rust Named Pipe samples.
- `installer-validation.json` - install, installed runtime, version upgrade, and uninstall evidence.
- `build-artifacts.json` - sidecar and NSIS sizes, hashes, and signature states.
- `acceptance-decision.json` - approved P-1.1 waiver, Win10 follow-up, Git `N/A`, and final GO decision.

No UI screenshots were retained. Command output and structured JSON are the reproducible evidence for this run.
