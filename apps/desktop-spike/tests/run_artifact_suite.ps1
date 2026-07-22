param(
  [string]$Sidecar = 'D:\agent\sidecar-demo\dist-final\sidecar.dist\sidecar.exe',
  [string]$EvidenceDir = 'D:\agent\evidence\p1-2026-07-22'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$tests = Join-Path $projectRoot 'tests'
$manifest = Join-Path $projectRoot 'src-tauri\Cargo.toml'
$rustProbe = Join-Path $projectRoot 'src-tauri\target\release\examples\ipc_smoke_v2.exe'
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null

function Save-Output {
  param([string]$Name, [object[]]$Lines)
  $path = Join-Path $EvidenceDir $Name
  $Lines | Set-Content -Encoding utf8 $path
  return $path
}

$startup = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tests 'measure_startup.ps1') -Runs 5 -Sidecar $Sidecar
if ($LASTEXITCODE -ne 0) { throw 'startup gate failed' }
$startupPath = Save-Output 'nuitka-startup.json' $startup

$lifecycle = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tests 'test_lifecycle.ps1') -Sidecar $Sidecar
if ($LASTEXITCODE -ne 0) { throw 'lifecycle gate failed' }
$lifecyclePath = Save-Output 'nuitka-lifecycle.json' $lifecycle

& cargo build --offline --release --example ipc_smoke_v2 --manifest-path $manifest
if ($LASTEXITCODE -ne 0) { throw 'Rust IPC probe build failed' }

$sidecarProcess = Start-Process -FilePath $Sidecar -PassThru -WindowStyle Hidden
try {
  $deadline = (Get-Date).AddSeconds(10)
  $ready = $false
  while (-not $ready -and (Get-Date) -lt $deadline) {
    try {
      $health = Invoke-RestMethod 'http://127.0.0.1:9876/health' -TimeoutSec 1
      $ready = ($health.status -eq 'ready' -and $health.nonce -eq 'development' -and [int]$health.pid -eq $sidecarProcess.Id)
    } catch {
      Start-Sleep -Milliseconds 50
    }
  }
  if (-not $ready) { throw 'direct sidecar health timeout' }

  $powershellIpc = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $tests 'measure_ipc_v2.ps1') -Nonce development
  if ($LASTEXITCODE -ne 0) { throw 'PowerShell IPC gate failed' }
  $powershellIpcPath = Save-Output 'nuitka-ipc-powershell.json' $powershellIpc

  $env:ZCODE_RUN_NONCE = 'development'
  $rustIpc = & $rustProbe
  if ($LASTEXITCODE -ne 0) { throw 'Rust IPC gate failed' }
  $rustIpcPath = Save-Output 'nuitka-ipc-rust.json' $rustIpc
} finally {
  Stop-Process -Id $sidecarProcess.Id -Force -ErrorAction SilentlyContinue
  Remove-Item Env:ZCODE_RUN_NONCE -ErrorAction SilentlyContinue
}

$summary = [pscustomobject]@{
  sidecar = $Sidecar
  startup = $startupPath
  lifecycle = $lifecyclePath
  powershell_ipc = $powershellIpcPath
  rust_ipc = $rustIpcPath
  passed = $true
}
$summary | ConvertTo-Json
$summary | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $EvidenceDir 'nuitka-suite-summary.json')
