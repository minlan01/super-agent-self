# Database Corruption Runbook

> Updated: 2026-08-16
> Scope: local SQLite database used by control-core
> Current status: backup validation and offline restore are implemented

## 1. Trigger Conditions

- Readiness reports `checks.db=error`.
- SQLite reports `database disk image is malformed`, `file is not a database`, I/O errors or repeated WAL recovery failures.
- A migration or update leaves the database unreadable.

Do not overwrite the database while control-core or the desktop sidecar is using it.

## 2. Contain and Preserve Evidence

Run from `services\control-core` in PowerShell:

```powershell
$python = Resolve-Path '.\.venv-win\Scripts\python.exe'
$db = Resolve-Path '.\data\agent_platform.db'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$evidence = Join-Path '.\artifacts' "db-incident-$stamp"
New-Item -ItemType Directory -Path $evidence | Out-Null

Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'apps\.api_server|uvicorn|sidecar\.exe' } |
  Select-Object Name, ProcessId, ParentProcessId, ExecutablePath, CommandLine |
  ConvertTo-Json -Depth 4 |
  Set-Content -Encoding utf8 (Join-Path $evidence 'processes.json')

Copy-Item -LiteralPath $db -Destination (Join-Path $evidence 'agent_platform.db.observed')
```

Stop only the identified service/desktop PIDs. Verify they have exited before continuing.

## 3. Check the Current Database

```powershell
& $python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0]); c.close()" $db
```

Expected result: `ok`. Any other result is a failed integrity check and the file must not be used as a restore source.

## 4. Select and Validate a Backup

Backups are stored under `data\backups` and named `agent_platform_<UTC timestamp>.db`.

```powershell
$backupDir = Resolve-Path '.\data\backups'
Get-ChildItem -LiteralPath $backupDir -Filter 'agent_platform_*.db' |
  Sort-Object LastWriteTime -Descending |
  Select-Object FullName, Length, LastWriteTime, @{n='SHA256';e={(Get-FileHash $_.FullName -Algorithm SHA256).Hash}}

$backup = Resolve-Path '.\data\backups\agent_platform_<timestamp>.db'
& $python -c "from packages.admin.backup_service import BackupService; import json,sys; print(json.dumps(BackupService.validate_backup(sys.argv[1])))" $backup
```

Proceed only when `is_valid_sqlite` is `true` and the backup digest is recorded in the incident evidence.

## 5. Restore Offline

Preserve the current file before replacement, even when it is corrupt.

```powershell
$preRestore = "$db.pre-restore-$stamp"
Copy-Item -LiteralPath $db -Destination $preRestore

$dbUrl = "sqlite:///$($db.Path -replace '\\','/')"
& $python -c "from packages.admin.backup_service import BackupService; import sys; print(BackupService.restore_backup(sys.argv[1], sys.argv[2], sys.argv[3]))" $dbUrl $backup $backupDir
```

The current restore implementation validates the source and constrains it to the backup directory, but the final copy is not an atomic replace. Keep the service stopped until every validation step completes.

## 6. Validate and Restart

```powershell
& $python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('PRAGMA integrity_check').fetchone()[0]); print(c.execute('PRAGMA foreign_key_check').fetchall()); c.close()" $db
& $python -m alembic current
```

Expected results:

- `PRAGMA integrity_check` prints `ok`.
- `PRAGMA foreign_key_check` prints `[]`.
- Alembic reports the expected release revision.

After restarting control-core:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health/ready' -TimeoutSec 10
```

Run a read-only task before re-enabling side effects.

## 7. Exit Criteria

- Original observed database and pre-restore copy are preserved.
- Selected backup digest and validation result are recorded.
- Integrity, foreign-key and Alembic checks pass.
- Readiness is healthy after restart.
- A read-only task completes and audit events remain queryable.

## 8. Escalation

Escalate to `NO-GO` when no backup passes validation, schema downgrade is unsupported, or the restore result differs from the recorded backup digest. Do not attempt ad hoc table salvage on the production file; work on a copy.
