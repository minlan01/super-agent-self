param(
  [string]$PythonVersion = '3.12',
  [string]$CacheDir = (Join-Path $PSScriptRoot '.cache\nuitka')
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = Join-Path $root '.venv312'
$python = Join-Path $venv 'Scripts\python.exe'
$lock = Join-Path $root 'requirements-build.lock'
$source = Join-Path (Split-Path $root -Parent) 'tauri-spike\sidecar.py'
$output = Join-Path $root 'dist-final'

if (-not (Test-Path $python)) {
  & py "-$PythonVersion" -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw "failed to create Python $PythonVersion environment" }
}

& $python -m pip install --disable-pip-version-check --no-deps --retries 2 --timeout 30 --requirement $lock
if ($LASTEXITCODE -ne 0) { throw 'failed to install locked sidecar build dependencies' }

$env:NUITKA_CACHE_DIR = [IO.Path]::GetFullPath($CacheDir)
& $python -m nuitka --mode=standalone --output-dir=$output --output-filename=sidecar.exe --assume-yes-for-downloads $source
if ($LASTEXITCODE -ne 0) { throw 'Nuitka sidecar build failed' }

$artifact = Join-Path $output 'sidecar.dist\sidecar.exe'
if (-not (Test-Path $artifact)) { throw "missing artifact: $artifact" }
$files = Get-ChildItem (Split-Path $artifact -Parent) -Recurse -File
[pscustomobject]@{
  python = (& $python --version)
  nuitka = (& $python -m nuitka --version | Select-Object -First 1)
  artifact = $artifact
  files = $files.Count
  size_mb = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 3)
  sha256 = (Get-FileHash $artifact -Algorithm SHA256).Hash
} | ConvertTo-Json
