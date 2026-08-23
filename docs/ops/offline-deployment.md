# Offline Deployment Guide

> Updated: 2026-08-20
> Scope: Windows desktop package and optional local control-core
> Current release status: `NO-GO` for production offline distribution

## 1. Current Constraints

The current desktop bundle is an NSIS `.exe`, not MSI/MSIX. Its WebView2 mode is `downloadBootstrapper`, so a truly air-gapped target must already have a supported WebView2 Runtime. The packaged sidecar is the real control-core service over IPC v1, and the local installer is not production-signed.

Do not distribute the current `0.1.0` artifact as a production offline release.

## 2. Build the Transfer Set on a Connected Windows Host

Run from the repository root:

```powershell
cd 'D:\agent\Agents\super-agent-self'

# Python wheel cache for self-hosted/local control-core deployment.
New-Item -ItemType Directory -Force -Path '.\offline\wheels' | Out-Null
& '.\services\control-core\.venv-win\Scripts\python.exe' -m pip download `
  --requirement '.\services\control-core\requirements-win-locked.txt' `
  --dest '.\offline\wheels'

# Build the desktop and NSIS installer from locked dependencies.
cd '.\apps\desktop'
npm.cmd ci
npm.cmd run tauri -- build --bundles nsis --ci
```

The release transfer set must contain:

- Production-signed NSIS installer.
- N-1 production-signed installer.
- `requirements-win-locked.txt` and matching wheel directory when control-core is installed separately.
- CycloneDX SBOM files.
- Release gate record with source revision, SHA-256, signatures, test evidence and rollback point.
- WebView2 Evergreen Standalone Installer when the target image does not already provide WebView2.

## 3. Verify Before Transfer

```powershell
$installer = Resolve-Path '.\src-tauri\target\release\bundle\nsis\Zcode Desktop Agent_<version>_x64-setup.exe'
$signature = Get-AuthenticodeSignature -LiteralPath $installer
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $installer

$signature | Select-Object Status, StatusMessage, SignerCertificate, TimeStamperCertificate
$hash

if ($signature.Status -ne 'Valid') { throw 'installer is not production-signed' }
if (-not $signature.TimeStamperCertificate) { throw 'trusted timestamp is missing' }
```

Compare the SHA-256 with `docs/releases/v1.0-gate.md`. Copy the transfer set to approved media and record a second hash after copying.

## 4. Prepare the Air-Gapped Windows Target

### 4.1 Confirm WebView2

```powershell
$webViewClient = 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
Get-ItemProperty -LiteralPath $webViewClient -ErrorAction SilentlyContinue |
  Select-Object name, pv
```

If no supported runtime is present, install the approved offline Evergreen Standalone package before Zcode. The current `downloadBootstrapper` setting cannot download anything on an air-gapped host.

### 4.2 Verify Transfer Integrity Again

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath '.\Zcode Desktop Agent_<version>_x64-setup.exe'
Get-AuthenticodeSignature -LiteralPath '.\Zcode Desktop Agent_<version>_x64-setup.exe'
```

Stop when the digest differs, the signature is not `Valid`, or the trusted timestamp is missing.

## 5. Install the Desktop Package

The current NSIS configuration uses `currentUser`, so it installs without an administrator-only per-machine deployment mode.

```powershell
$installer = Resolve-Path '.\Zcode Desktop Agent_<version>_x64-setup.exe'
$process = Start-Process -FilePath $installer -ArgumentList '/S' -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "installer failed: $($process.ExitCode)" }
```

Verify registration and installed files:

```powershell
$reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Zcode Desktop Agent'
$installRoot = (Get-ItemProperty $reg).InstallLocation.Trim('"')
Get-ChildItem -LiteralPath $installRoot -Recurse -File |
  Select-Object FullName, Length
```

Enterprise per-machine installation is not implemented in the current configuration. Do not use `msiexec`; there is no MSI artifact.

## 6. Install Local Control-Core Dependencies When Required

```powershell
cd '.\services\control-core'
& '.\.venv-win\Scripts\python.exe' -m pip install `
  --no-index `
  --find-links '..\..\offline\wheels' `
  --requirement '.\requirements-win-locked.txt'

& '.\.venv-win\Scripts\python.exe' -m pip check
& '.\.venv-win\Scripts\python.exe' -m alembic upgrade head
```

Provision `SECRET_KEY` through the target organization's secret manager or service identity. Do not pass it in an installer command line, write it into the repository, or store it in deployment logs.

For an interactive one-process test without command-history exposure:

```powershell
$secure = Read-Host 'SECRET_KEY' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $env:SECRET_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
  & '.\.venv-win\Scripts\python.exe' -m uvicorn apps.api_server.main:app --host 127.0.0.1 --port 8000
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
  Remove-Item Env:SECRET_KEY -ErrorAction SilentlyContinue
}
```

## 7. Acceptance Checks

Desktop readiness is verified through the Tauri sidecar status command and
the IPC v1 handshake. The sidecar loopback HTTP port is random and its token
is kept inside the Rust shell. Use the packaged API smoke client for an
automated health/task/approval check; do not assume a fixed public port.

Required offline acceptance evidence:

- Install completes without network access.
- WebView2 is present or installed from the approved offline package.
- Desktop, sidecar and installer signatures are valid.
- IPC readiness and packaged API smoke checks pass.
- One read-only task and one approval-gated task pass.
- Uninstall removes the app, registry entry, sidecar process and port listener.
- N-1 reinstall and database restore are exercised.

## 8. Offline Update and Rollback

Use only manually transferred, production-signed packages until the signed updater exists. Follow [update-rollback.md](../runbooks/update-rollback.md) and create a validated backup before installing the new version.

## 9. Uninstall

```powershell
$reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Zcode Desktop Agent'
$uninstall = (Get-ItemProperty $reg).UninstallString.Trim('"')
$process = Start-Process -FilePath $uninstall -ArgumentList '/S' -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "uninstall failed: $($process.ExitCode)" }
```

Verify the registry key, install directory, desktop/sidecar processes and any
listeners owned by those processes are absent.

## 10. Production Gate

Offline production deployment remains blocked until:

- The real control-core sidecar and IPC v1 pass the current-host evidence
  suite; second-account, clean-OS and UI acceptance remain required.
- Production signing and trusted timestamping cover all executable payloads and the installer.
- WebView2 offline distribution is configured and tested.
- Clean Windows 10 and Windows 11 offline VMs pass install, startup, task, rollback and uninstall checks.
- A secure persistent secret-provisioning path is implemented.
