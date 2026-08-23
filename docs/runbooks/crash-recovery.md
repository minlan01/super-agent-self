# Crash Recovery Runbook

> Updated: 2026-08-20
> Scope: Windows NSIS desktop package and bundled Nuitka sidecar
> Current status: `OPERABLE` for the packaged control-core sidecar and IPC v1; production release gates remain blocked.

## 1. Trigger Conditions

Use this runbook when any of the following occurs:

- `Zcode Desktop Agent` exits unexpectedly.
- A sidecar listener remains after the desktop process exits.
- The sidecar restarts repeatedly or stops after the restart limit.
- The desktop window opens but the sidecar does not become ready within 15 seconds.

The current Rust supervisor restarts the sidecar after the first three crashes. After the fourth crash it leaves the desktop process running but stops restarting the sidecar. Closing or force-terminating the desktop process must release the Job Object and remove the sidecar process tree.

## 2. Capture State Before Recovery

Run from PowerShell. Do not stop unrelated Python processes by name.

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$evidence = Join-Path $env:TEMP "zcode-crash-$stamp"
New-Item -ItemType Directory -Path $evidence | Out-Null

Get-CimInstance Win32_Process |
  Where-Object { $_.Name -in @('tauri-spike.exe', 'sidecar.exe') } |
  Select-Object Name, ProcessId, ParentProcessId, CreationDate, ExecutablePath, CommandLine |
  ConvertTo-Json -Depth 4 |
  Set-Content -Encoding utf8 (Join-Path $evidence 'processes.json')

Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.OwningProcess -in @(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('tauri-spike.exe', 'sidecar.exe') } | Select-Object -ExpandProperty ProcessId) } |
  Select-Object LocalAddress, LocalPort, State, OwningProcess |
  ConvertTo-Json -Depth 3 |
  Set-Content -Encoding utf8 (Join-Path $evidence 'sidecar-listeners.json')
```

The loopback HTTP port is random and its token remains inside the Rust shell.
Use the desktop sidecar status action or the packaged IPC/API smoke client; do
not assume a fixed public health URL.

## 3. Confirm the Installed Artifact

```powershell
$reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Zcode Desktop Agent'
$installRoot = (Get-ItemProperty $reg).InstallLocation.Trim('"')
$desktopExe = Join-Path $installRoot 'tauri-spike.exe'
$sidecarExe = Join-Path $installRoot 'sidecar\sidecar.exe'

Get-FileHash -Algorithm SHA256 -LiteralPath $desktopExe, $sidecarExe
Get-AuthenticodeSignature -LiteralPath $desktopExe, $sidecarExe |
  Select-Object Path, Status, StatusMessage, SignerCertificate, TimeStamperCertificate
```

For production recovery, every executable must match the approved release record and report `Status = Valid`. The current P4 local artifact is not production-signed and must not be treated as a GA package.

## 4. Recover

1. Close the desktop window normally and wait up to 10 seconds.
2. If it does not exit, terminate only the recorded desktop PID.
3. Verify that the recorded child PID and its listener are gone.
4. Start the desktop executable once and wait for IPC readiness.

```powershell
$desktop = Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'tauri-spike.exe' -and $_.ExecutablePath -eq $desktopExe } |
  Select-Object -First 1

if ($desktop) {
  Stop-Process -Id $desktop.ProcessId -Force
}

$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline -and
       (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
         Where-Object { $_.Name -eq 'sidecar.exe' })) {
  Start-Sleep -Milliseconds 200
}

Start-Process -FilePath $desktopExe
Get-Content -LiteralPath (Join-Path (Split-Path $desktopExe) 'logs\sidecar.log') -Tail 20
```

If IPC readiness still fails, do not loop indefinitely. Uninstall the package,
verify the install directory, process tree and owned listeners are removed, and
reinstall the exact approved package.

## 5. Exit Criteria

- Desktop process remains running for at least 60 seconds.
- IPC readiness reports a live sidecar PID and negotiated protocol v1.
- The sidecar log records a random loopback HTTP port and the v1 pipe name.
- Closing the desktop removes the sidecar and its listener within 10 seconds.
- Artifact digest and production signature match the release gate.

## 6. Known Gaps

- The packaged sidecar exposes the real control-core API through the IPC
  `http.request` proxy; direct loopback access is token-gated.
- Desktop stdout/stderr are currently redirected to null, so a persistent diagnostic log and support-bundle command are still required.
- There is no Windows service wrapper or central crash telemetry.
