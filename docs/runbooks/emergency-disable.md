# Emergency Disable Runbook

> Updated: 2026-08-16
> Scope: Windows desktop and local control-core
> Current status: manual break-glass procedure; one-command emergency stop is `BLOCKED`

## 1. When to Use

Use this procedure for suspected unauthorized side effects, tenant isolation failure, forged grants, unsafe desktop control, malicious update, credential compromise or uncontrolled process execution.

The repository does not currently implement the previously documented `zcode emergency-stop` command. Stopping dispatch and the process tree is the only reliable immediate containment action.

## 2. Immediate Containment

1. Disconnect the affected host from untrusted networks when data exfiltration is possible.
2. Record the current desktop, sidecar and control-core PIDs.
3. Stop the desktop owner process first so its Job Object removes the bundled sidecar.
4. Stop only the identified control-core server PIDs.

```powershell
$targets = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -in @('tauri-spike.exe', 'sidecar.exe') -or
    $_.CommandLine -match 'apps\.api_server|uvicorn'
  } |
  Select-Object Name, ProcessId, ParentProcessId, ExecutablePath, CommandLine

$targets | Format-Table -AutoSize
$targets | ConvertTo-Json -Depth 4 |
  Set-Content -Encoding utf8 (Join-Path $env:TEMP "zcode-emergency-processes-$(Get-Date -Format 'yyyyMMdd-HHmmss').json")

$desktopPids = @($targets | Where-Object Name -eq 'tauri-spike.exe' | Select-Object -ExpandProperty ProcessId)
foreach ($processId in $desktopPids) {
  Stop-Process -Id $processId -Force
}

$serverPids = @($targets |
  Where-Object { $_.CommandLine -match 'apps\.api_server|uvicorn' } |
  Select-Object -ExpandProperty ProcessId)
foreach ($processId in $serverPids) {
  Stop-Process -Id $processId -Force
}
```

Verify containment:

```powershell
Get-NetTCPConnection -LocalPort 9876,8000 -State Listen -ErrorAction SilentlyContinue
Get-Process tauri-spike,sidecar -ErrorAction SilentlyContinue
```

Expected result: no listener and no matching desktop/sidecar process.

## 3. Disable High-Risk Tools Before Restart

Edit `services/control-core/configs/tools.yaml` and set `enabled: false` for all affected tools. For broad containment, disable at least:

- `shell.execute`
- `process.execute`
- `terminal.open`, `terminal.write`, `terminal.signal`, `terminal.attach`, `terminal.close`
- `desktop.click`, `desktop.type`, `desktop.screenshot`, `desktop.files`, `desktop.windows`

The tool registry reads this configuration during startup. Restart is required. Keep the original file and the reviewed emergency version as incident evidence.

## 4. Revoke Unconsumed Grants

There is no audited bulk-revocation API. The following break-glass action directly marks every `issued` grant as `revoked`; run it only after preserving a database backup and recording the operator and incident ID.

```powershell
cd 'D:\agent\Agents\super-agent-self\services\control-core'
$python = Resolve-Path '.\.venv-win\Scripts\python.exe'

& $python -c "from sqlalchemy import update; from packages.db.models import CapabilityGrantModel,GrantStatusDB; from packages.db.session import SessionLocal; db=SessionLocal(); result=db.execute(update(CapabilityGrantModel).where(CapabilityGrantModel.status==GrantStatusDB.ISSUED).values(status=GrantStatusDB.REVOKED)); db.commit(); print(result.rowcount); db.close()"
```

Stopping the process tree remains mandatory because this operation does not terminate already-running external effects and does not bulk-expire leases.

## 5. Preserve Evidence

Collect, without modifying the originals:

- Current database and WAL/SHM files.
- `artifacts/` test and audit records.
- Process command lines and network listeners.
- Installer, desktop and sidecar SHA-256 digests and Authenticode results.
- Relevant configuration files and their hashes.
- Approval, Grant, Lease, Effect and Receipt records for the incident window.

Do not restart repeatedly before capturing state.

## 6. Controlled Re-Enable

1. Identify and remediate the root cause.
2. Rebuild from an approved source revision.
3. Verify SBOM, dependency audits, signatures and release digest.
4. Restore a validated configuration with only required tools enabled.
5. Start control-core without desktop side effects and check readiness.
6. Run a read-only task.
7. Enable approval-gated tools in small groups.
8. Issue new grants; never restore revoked grants.

## 7. Exit Criteria

- No unauthorized process or listener remains.
- All unconsumed grants from the affected database are revoked.
- High-risk tools stay disabled until reviewed.
- Evidence bundle and incident timeline are preserved.
- A fixed, signed build passes health, read-only and approval-gated smoke tests.

## 8. Required Product Work

Before Windows GA, implement an authenticated, audited emergency-stop path that stops new dispatch, cancels safe runners, revokes grants and leases, records an immutable event and reports completion within a defined SLO.
