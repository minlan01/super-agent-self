param(
  [string]$Source
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $Source) {
  $repository = Split-Path (Split-Path $projectRoot -Parent) -Parent
  $Source = Join-Path $repository 'services\control-core\scripts\nuitka-build\dist-final\sidecar.dist'
}
$sourcePath = [IO.Path]::GetFullPath($Source)
$resourceRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'src-tauri\resources'))
$destination = [IO.Path]::GetFullPath((Join-Path $resourceRoot 'sidecar'))

if (-not (Test-Path (Join-Path $sourcePath 'sidecar.exe'))) {
  throw "Nuitka standalone directory is missing sidecar.exe: $sourcePath"
}
if (-not $destination.StartsWith("$resourceRoot\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "refusing to replace path outside resource root: $destination"
}

New-Item -ItemType Directory -Force -Path $resourceRoot | Out-Null
if (Test-Path $destination) {
  Remove-Item -LiteralPath $destination -Recurse -Force
}
Copy-Item -LiteralPath $sourcePath -Destination $destination -Recurse

$files = Get-ChildItem $destination -Recurse -File
[pscustomobject]@{
  source = $sourcePath
  destination = $destination
  files = $files.Count
  size_mb = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 3)
  sidecar_sha256 = (Get-FileHash (Join-Path $destination 'sidecar.exe') -Algorithm SHA256).Hash
} | ConvertTo-Json
