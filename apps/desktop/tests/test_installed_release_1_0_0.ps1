param(
  [string]$Installer = (Join-Path $PSScriptRoot '..\src-tauri\target\release\bundle\nsis\Zcode Desktop Agent_1.0.0_x64-setup.exe'),
  [string]$EvidencePath = (Join-Path $PSScriptRoot '..\..\services\control-core\artifacts\p4-installed-1.0.0-install-uninstall-2026-08-22.json')
)

$ErrorActionPreference = 'Stop'
$installer = [IO.Path]::GetFullPath($Installer)
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
  throw "1.0.0 installer not found: $installer"
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("zcode-p4-install-v100-" + [Guid]::NewGuid().ToString('N'))
$evidence = [IO.Path]::GetFullPath($EvidencePath)
New-Item -ItemType Directory -Force -Path (Split-Path $evidence -Parent) | Out-Null

$install = Start-Process -FilePath $installer -ArgumentList @('/S', "/D=$tempRoot") -Wait -PassThru -WindowStyle Hidden
$installRootPresent = Test-Path -LiteralPath $tempRoot -PathType Container
$uninstaller = Get-ChildItem -LiteralPath $tempRoot -Filter 'uninstall.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$desktop = Get-ChildItem -LiteralPath $tempRoot -Filter 'tauri-spike.exe' -File -Recurse -ErrorAction SilentlyContinue |
  Select-Object -First 1
$sidecar = Get-ChildItem -LiteralPath $tempRoot -Filter 'sidecar.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1

$startupPassed = $false
$startupOutput = $null
if ($desktop) {
  $startupScript = Join-Path $PSScriptRoot 'measure_startup.ps1'
  $startupOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startupScript -Runs 1 -Exe $desktop.FullName | Out-String
  $startupPassed = $LASTEXITCODE -eq 0
}

$uninstall = $null
if ($uninstaller) {
  $uninstall = Start-Process -FilePath $uninstaller.FullName -ArgumentList @('/S') -Wait -PassThru -WindowStyle Hidden
}
Start-Sleep -Milliseconds 500
$rootAbsent = -not (Test-Path -LiteralPath $tempRoot)
$processCount = @(Get-Process -Name 'tauri-spike','sidecar' -ErrorAction SilentlyContinue).Count

$result = [ordered]@{
  date = '2026-08-22'
  installer = $installer
  installer_version = (Get-Item $installer).VersionInfo.ProductVersion
  install_exit_code = $install.ExitCode
  install_root_present = $installRootPresent
  desktop_present = [bool]$desktop
  sidecar_present = [bool]$sidecar
  startup_passed = $startupPassed
  startup_output = $startupOutput
  uninstall_present = [bool]$uninstaller
  uninstall_exit_code = if ($uninstall) { $uninstall.ExitCode } else { $null }
  install_root_absent_after_uninstall = $rootAbsent
  residual_process_count = $processCount
  passed = ($install.ExitCode -eq 0 -and $installRootPresent -and $desktop -and $sidecar -and $startupPassed -and $uninstaller -and $uninstall.ExitCode -eq 0 -and $rootAbsent -and $processCount -eq 0)
}
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $evidence -Encoding utf8
$result | ConvertTo-Json -Depth 8
if (-not $result.passed) { exit 1 }
