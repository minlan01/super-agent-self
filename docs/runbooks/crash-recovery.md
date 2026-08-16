# Crash Recovery Runbook

> Updated: 2026-08-16
> Scope: Windows NSIS desktop package and bundled Nuitka sidecar
> Current status: `OPERABLE` for the P-1 health/echo sidecar; real control-core integration remains `BLOCKED`

## 1. Trigger Conditions

Use this runbook when any of the following occurs:

- `Zcode Desktop Agent` exits unexpectedly.
- Port `9876` remains occupied after the desktop process exits.
- The sidecar restarts repeatedly or stops after the restart limit.
- The desktop window opens but `/health` does not become ready within 10 seconds.

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

Get-NetTCPConnection -LocalPort 9876 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, State, OwningProcess |
  ConvertTo-Json -Depth 3 |
  Set-Content -Encoding utf8 (Join-Path $evidence 'port-9876.json')
```

If the health endpoint responds, retain its body:

```powershell
Invoke-RestMethod 'http://127.0.0.1:9876/health' -TimeoutSec 2 |
  ConvertTo-Json |
  Set-Content -Encoding utf8 (Join-Path $evidence 'health.json')
```

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
3. Verify that the recorded child PID and port `9876` are gone.
4. Start the desktop executable once and wait for health readiness.

```powershell
$desktop = Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'tauri-spike.exe' -and $_.ExecutablePath -eq $desktopExe } |
  Select-Object -First 1

if ($desktop) {
  Stop-Process -Id $desktop.ProcessId -Force
}

$deadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $deadline -and
       (Get-NetTCPConnection -LocalPort 9876 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Sleep -Milliseconds 200
}

Start-Process -FilePath $desktopExe
Invoke-RestMethod 'http://127.0.0.1:9876/health' -TimeoutSec 10
```

If health still fails, do not loop indefinitely. Uninstall the package, verify the install directory and port are removed, and reinstall the exact approved package.

## 5. Exit Criteria

- Desktop process remains running for at least 60 seconds.
- `/health` returns `status=ready`, a non-empty nonce, and a live sidecar PID.
- Port `9876` belongs to that sidecar PID.
- Closing the desktop removes the sidecar and releases port `9876` within 10 seconds.
- Artifact digest and production signature match the release gate.

## 6. Known Gaps

- The packaged sidecar currently implements only `/health` and Named Pipe echo, not the real control-core API.
- Desktop stdout/stderr are currently redirected to null, so a persistent diagnostic log and support-bundle command are still required.
- There is no Windows service wrapper or central crash telemetry.
