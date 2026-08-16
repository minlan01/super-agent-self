param(
  [string]$PythonVersion = '3.12',
  [string]$CacheDir = (Join-Path $PSScriptRoot '.cache\nuitka'),
  [string]$Source
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = Join-Path $root '.venv312'
$python = Join-Path $venv 'Scripts\python.exe'
$lock = Join-Path $root 'requirements-build.lock'
$output = Join-Path $root 'dist-final'
$controlCore = Split-Path (Split-Path $root -Parent) -Parent
$repository = Split-Path (Split-Path $controlCore -Parent) -Parent
if (-not $Source) {
  $Source = Join-Path $repository 'apps\desktop\sidecar.py'
}
$sourcePath = [IO.Path]::GetFullPath($Source)
$repositoryPath = [IO.Path]::GetFullPath($repository).TrimEnd('\')
if (-not $sourcePath.StartsWith("$repositoryPath\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "refusing to build a sidecar source outside the repository: $sourcePath"
}
if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
  throw "sidecar source does not exist: $sourcePath"
}

if (-not (Test-Path $python)) {
  & py "-$PythonVersion" -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw "failed to create Python $PythonVersion environment" }
}

& $python -m pip install --disable-pip-version-check --no-deps --retries 2 --timeout 30 --requirement $lock
if ($LASTEXITCODE -ne 0) { throw 'failed to install locked sidecar build dependencies' }

$env:NUITKA_CACHE_DIR = [IO.Path]::GetFullPath($CacheDir)
& $python -m nuitka --mode=standalone --output-dir=$output --output-filename=sidecar.exe --assume-yes-for-downloads $sourcePath
if ($LASTEXITCODE -ne 0) { throw 'Nuitka sidecar build failed' }

$artifact = Join-Path $output 'sidecar.dist\sidecar.exe'
if (-not (Test-Path $artifact)) { throw "missing artifact: $artifact" }
$files = Get-ChildItem (Split-Path $artifact -Parent) -Recurse -File
[pscustomobject]@{
  python = (& $python --version)
  nuitka = (& $python -m nuitka --version | Select-Object -First 1)
  source = $sourcePath
  artifact = $artifact
  files = $files.Count
  size_mb = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 3)
  sha256 = (Get-FileHash $artifact -Algorithm SHA256).Hash
} | ConvertTo-Json
