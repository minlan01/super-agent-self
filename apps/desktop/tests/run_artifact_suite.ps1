param(
  [string]$Python,
  [string]$DesktopExe,
  [string]$EvidenceDir
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$repository = [IO.Path]::GetFullPath((Join-Path $projectRoot '..\..'))
$controlCore = Join-Path $repository 'services\control-core'
if (-not $Python) { $Python = Join-Path $controlCore '.venv-win\Scripts\python.exe' }
if (-not $DesktopExe) { $DesktopExe = Join-Path $projectRoot 'src-tauri\target\release\tauri-spike.exe' }
if (-not $EvidenceDir) { $EvidenceDir = Join-Path $controlCore 'artifacts\p4-sidecar-suite' }
if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null

function Save-Output {
  param([string]$Name, [object[]]$Lines)
  $path = Join-Path $EvidenceDir $Name
  $Lines | Set-Content -Encoding utf8 $path
  return $path
}

$unit = & $Python -m pytest (Join-Path $controlCore 'tests\unit\test_ipc_contract.py') -q
if ($LASTEXITCODE -ne 0) { throw 'IPC contract unit gate failed' }
$unitPath = Save-Output 'ipc-contract-unit.txt' $unit

$integration = & $Python -m pytest (Join-Path $controlCore 'tests\integration\test_sidecar_pipe_windows.py') -q
if ($LASTEXITCODE -ne 0) { throw 'IPC Windows integration gate failed' }
$integrationPath = Save-Output 'ipc-pipe-integration.txt' $integration

$powershellIpc = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'measure_ipc_v2.ps1')
if ($LASTEXITCODE -ne 0) { throw 'PowerShell IPC measurement failed' }
$powershellIpcPath = Save-Output 'ipc-powershell.json' $powershellIpc

$startupPath = $null
$lifecyclePath = $null
if (Test-Path -LiteralPath $DesktopExe) {
  $startup = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'measure_startup.ps1') -Runs 3 -Exe $DesktopExe
  if ($LASTEXITCODE -ne 0) { throw 'desktop startup gate failed' }
  $startupPath = Save-Output 'desktop-startup.json' $startup

  $lifecycle = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'test_lifecycle.ps1') -Exe $DesktopExe
  if ($LASTEXITCODE -ne 0) { throw 'desktop lifecycle gate failed' }
  $lifecyclePath = Save-Output 'desktop-lifecycle.json' $lifecycle
}

$summary = [pscustomobject]@{
  python = $Python
  desktop_exe = $DesktopExe
  ipc_contract_unit = $unitPath
  ipc_pipe_integration = $integrationPath
  powershell_ipc = $powershellIpcPath
  desktop_startup = $startupPath
  desktop_lifecycle = $lifecyclePath
  passed = $true
}
$summary | ConvertTo-Json
$summary | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $EvidenceDir 'sidecar-suite-summary.json')
