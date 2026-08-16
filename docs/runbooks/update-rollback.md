# Update and Rollback Runbook

> Updated: 2026-08-16
> Scope: Windows NSIS package
> Current status: manual signed-package procedure only; automatic updater is `BLOCKED`

## 1. Release Preconditions

Do not start an update unless all of the following are available:

- Approved release record with source revision, installer SHA-256, SBOM, test evidence, signer identity, timestamp and rollback package.
- Production Authenticode signatures on the desktop executable, sidecar executables and final installer.
- A known-good N-1 installer retained offline.
- A validated database backup created immediately before the update.
- Schema compatibility decision for both forward update and N-1 rollback.

The current `WindowsPlatformAdapter.updater()` raises `CapabilityUnavailable("updater", "P4 scope")`. There is no signed manifest, CDN endpoint, anti-replay check, atomic updater or automatic rollback in the current source.

## 2. Create and Validate the Pre-Update Backup

With control-core running and an administrator bearer token supplied at runtime:

```powershell
$headers = @{ Authorization = "Bearer $env:ZCODE_ADMIN_TOKEN" }
$backup = Invoke-RestMethod `
  -Method Post `
  -Uri 'http://127.0.0.1:8000/api/v1/admin/backup' `
  -Headers $headers

$backupPath = $backup.data.backup_path
$backupId = [IO.Path]::GetFileNameWithoutExtension($backupPath)

Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/api/v1/admin/backups/$backupId/validate" `
  -Headers $headers
```

Do not place the token in a script, command history, installer argument or release record.

## 3. Verify the Candidate Package

```powershell
$installer = Resolve-Path '.\Zcode Desktop Agent_<version>_x64-setup.exe'
$expectedSha256 = '<sha256-from-approved-gate-record>'
$actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $installer).Hash
$signature = Get-AuthenticodeSignature -LiteralPath $installer

if ($actualSha256 -ne $expectedSha256) { throw 'installer digest mismatch' }
if ($signature.Status -ne 'Valid') { throw "invalid Authenticode status: $($signature.Status)" }
if (-not $signature.TimeStamperCertificate) { throw 'trusted timestamp is missing' }
```

## 4. Manual Update

1. Stop the desktop application and verify port `9876` is released.
2. Run the approved NSIS installer silently or interactively.
3. Start the application.
4. Verify desktop sidecar health and, after real control-core integration, `/api/v1/health/ready`.
5. Run one read-only task and one approval-gated task before expanding rollout.

```powershell
$process = Start-Process -FilePath $installer -ArgumentList '/S' -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "installer failed: $($process.ExitCode)" }

Invoke-RestMethod 'http://127.0.0.1:9876/health' -TimeoutSec 10
```

## 5. Roll Back to N-1

Roll back when startup, health, IPC, schema migration or a mandatory smoke test fails.

1. Stop the new desktop process and verify its child process tree is gone.
2. Run the installed `uninstall.exe /S`.
3. Verify the N-1 installer digest and signature against its archived gate record.
4. Install N-1.
5. Restore the pre-update database only when the schema compatibility record says N-1 cannot safely open the migrated database.
6. Run the same health and smoke checks.

```powershell
$reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Zcode Desktop Agent'
$uninstall = (Get-ItemProperty $reg).UninstallString.Trim('"')
$result = Start-Process -FilePath $uninstall -ArgumentList '/S' -Wait -PassThru
if ($result.ExitCode -ne 0) { throw "uninstall failed: $($result.ExitCode)" }

$nMinusOne = Resolve-Path '.\archive\Zcode Desktop Agent_<n-1>_x64-setup.exe'
Start-Process -FilePath $nMinusOne -ArgumentList '/S' -Wait
```

Use [db-corruption.md](./db-corruption.md) for offline database validation and restore.

## 6. Exit Criteria

- Installed version and installer digest match the selected release record.
- All required signatures and timestamps are valid.
- Health and smoke tests pass.
- N-1 package remains available and verified.
- Database integrity check returns `ok`.
- Rollout decision and operator identity are recorded.

## 7. Automatic Updater Gate

Automatic rollout remains blocked until all of these are implemented and tested:

- Signed update manifest and immutable package digest.
- Channel isolation for `internal`, `invited`, `10%`, `50%`, and `100%`.
- Minimum previous version and version-replay rejection.
- Power-loss-safe staging and atomic activation.
- Automatic N-1 rollback after failed post-install health checks.
- Tamper, wrong-channel, interrupted-update and downgrade test evidence.
