$ErrorActionPreference = 'Stop'
# Pure-cmdlet digest script (no native calls, ASCII-only: PS 5.1 reads
# BOM-less UTF-8 ps1 files as ANSI/GBK, which corrupts non-ASCII comments).
$Repo = 'D:\agent\Agents\super-agent-self'
$Evidence = Join-Path $Repo 'services\control-core\artifacts\windows-ga-20260823-214208'

$Sidecar = Join-Path $Repo 'apps\desktop\src-tauri\resources\sidecar\sidecar.exe'
$Desktop = Join-Path $Repo 'apps\desktop\src-tauri\target\release\tauri-spike.exe'
$UnsignedInstaller = Get-ChildItem `
  (Join-Path $Repo 'apps\desktop\src-tauri\target\release\bundle\nsis') `
  -Filter '*1.0.0*x64-setup.exe' -File |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1

foreach ($p in @($Sidecar, $Desktop)) {
  if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "missing artifact: $p" }
}
if (-not $UnsignedInstaller) { throw '1.0.0 unsigned installer not found' }

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
$unsigned | Format-Table path, size, authenticode -AutoSize
Write-Output 'DIGESTS-OK'
