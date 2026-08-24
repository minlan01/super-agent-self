$ErrorActionPreference = 'Stop'
$Repo = 'D:\agent\Agents\super-agent-self'
$Evidence = Join-Path $Repo 'services\control-core\artifacts\windows-ga-20260823-214208'

# 原生命令经 cmd /c 调用：stderr 在进程级并入 stdout，
# 避免 PS 5.1 把 npm/tauri 的进度或警告包装成 ErrorRecord 后
# 在 $ErrorActionPreference=Stop 下误杀脚本（本日已两次踩坑）。
function Invoke-Native {
  param([string]$CommandLine, [string]$LogPath, [string]$WorkingDir)
  $cmd = "cmd /c `"cd /d $WorkingDir && $CommandLine 2>&1`""
  $output = Invoke-Expression $cmd
  $output | Out-File -FilePath $LogPath -Encoding utf8
  $output | Select-Object -Last 6
  if ($LASTEXITCODE -ne 0) { throw "command failed (exit $LASTEXITCODE): $CommandLine" }
}

$Sidecar = Join-Path $Repo 'apps\desktop\src-tauri\resources\sidecar\sidecar.exe'
if (-not (Test-Path -LiteralPath $Sidecar)) { throw "Sidecar artifact missing: $Sidecar" }
$sidecarStamp = (Get-Item -LiteralPath $Sidecar).LastWriteTime
Write-Output "sidecar.exe mtime: $sidecarStamp"
if ($sidecarStamp -lt (Get-Date).AddHours(-3)) { throw "sidecar.exe is stale — build.ps1 copy step did not run" }

# 1. unsigned desktop build
Invoke-Native -CommandLine 'npm.cmd run tauri -- build --no-bundle --no-sign' `
  -LogPath (Join-Path $Evidence 'tauri-build-unsigned.txt') `
  -WorkingDir (Join-Path $Repo 'apps\desktop')

# 2. unsigned NSIS bundle
Invoke-Native -CommandLine 'npm.cmd run tauri -- bundle --bundles nsis --no-sign' `
  -LogPath (Join-Path $Evidence 'tauri-bundle-unsigned.txt') `
  -WorkingDir (Join-Path $Repo 'apps\desktop')

$Desktop = Join-Path $Repo 'apps\desktop\src-tauri\target\release\tauri-spike.exe'
if (-not (Test-Path -LiteralPath $Desktop)) { throw "desktop exe missing: $Desktop" }
$UnsignedInstaller = Get-ChildItem `
  (Join-Path $Repo 'apps\desktop\src-tauri\target\release\bundle\nsis') `
  -Filter '*1.0.0*x64-setup.exe' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $UnsignedInstaller) { throw '1.0.0 unsigned installer not found' }

# 3. 三产物摘要
$unsigned = @($Sidecar, $Desktop, $UnsignedInstaller.FullName) | ForEach-Object {
  $item = Get-Item -LiteralPath $_
  [pscustomobject]@{
    path = $item.FullName
    size = $item.Length
    sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
    authenticode = (Get-AuthenticodeSignature -LiteralPath $item.FullName).Status.ToString()
    mtime = $item.LastWriteTime.ToString('o')
  }
}
$unsigned | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Evidence 'unsigned-digests.json') -Encoding UTF8
$unsigned | ConvertTo-Json
Write-Output 'GATE4_2_OK'
