param(
  [string]$PythonVersion = '3.12',
  [string]$CacheDir = (Join-Path $PSScriptRoot '.cache\nuitka'),
  [string]$Source,
  [ValidateRange(1, 64)]
  [int]$Jobs = 4,
  [switch]$KeepBuild
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = Join-Path $root '.venv312'
$python = Join-Path $venv 'Scripts\python.exe'
$lock = Join-Path $root 'requirements-build.lock'
$output = Join-Path $root 'dist-final'
$controlCore = Split-Path (Split-Path $root -Parent) -Parent
$repository = Split-Path (Split-Path $controlCore -Parent) -Parent
$runtimeLock = Join-Path $controlCore 'requirements-win-locked.txt'
$bootstrapGenerator = Join-Path $root 'create_bootstrap_db.py'
$bootstrapInput = Join-Path $output 'bootstrap-input'
$reportDirectory = Join-Path $output 'reports'
$compilationReport = Join-Path $reportDirectory (
  'nuitka-compilation-{0}.xml' -f (Get-Date -Format 'yyyyMMdd-HHmmss')
)
if (-not $Source) {
  $Source = Join-Path $root 'control_core_sidecar.py'
}
$sourcePath = [IO.Path]::GetFullPath($Source)
$repositoryPath = [IO.Path]::GetFullPath($repository).TrimEnd('\')
if (-not $sourcePath.StartsWith("$repositoryPath\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "refusing to build a sidecar source outside the repository: $sourcePath"
}
if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
  throw "sidecar source does not exist: $sourcePath"
}
$outputPath = [IO.Path]::GetFullPath($output).TrimEnd('\')
$sourceStem = [IO.Path]::GetFileNameWithoutExtension($sourcePath)
if (-not $KeepBuild) {
  $stalePaths = @(
    (Join-Path $outputPath "$sourceStem.build"),
    (Join-Path $outputPath "$sourceStem.dist"),
    $bootstrapInput
  )
} else {
  $stalePaths = @($bootstrapInput)
}
foreach ($stalePath in $stalePaths) {
  $resolvedStale = [IO.Path]::GetFullPath($stalePath)
  if (-not $resolvedStale.StartsWith("$outputPath\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "refusing to remove a build path outside ${outputPath}: $resolvedStale"
  }
  if (Test-Path -LiteralPath $resolvedStale) {
    Remove-Item -LiteralPath $resolvedStale -Recurse -Force
  }
}

if (-not (Test-Path $python)) {
  & py "-$PythonVersion" -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw "failed to create Python $PythonVersion environment" }
}

& $python -m pip install --disable-pip-version-check --no-deps --retries 2 --timeout 30 --requirement $runtimeLock --requirement $lock
if ($LASTEXITCODE -ne 0) { throw 'failed to install locked sidecar runtime/build dependencies' }

$env:PYTHONPATH = $controlCore
& $python $bootstrapGenerator --resource-root $controlCore --output-dir $bootstrapInput
if ($LASTEXITCODE -ne 0) { throw 'failed to generate the Alembic-head SQLite bootstrap' }
$bootstrapDatabase = Join-Path $bootstrapInput 'agent_platform.db'
$bootstrapManifest = Join-Path $bootstrapInput 'manifest.json'
if (-not (Test-Path -LiteralPath $bootstrapDatabase -PathType Leaf)) { throw 'missing generated bootstrap database' }
if (-not (Test-Path -LiteralPath $bootstrapManifest -PathType Leaf)) { throw 'missing generated bootstrap manifest' }
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null

$env:NUITKA_CACHE_DIR = [IO.Path]::GetFullPath($CacheDir)
Push-Location $controlCore
try {
  & $python -m nuitka `
    --mode=standalone `
    --disable-cache=ccache `
    --jobs=$Jobs `
    --show-scons `
    "--report=$compilationReport" `
    --output-dir=$output `
    --output-filename=sidecar.exe `
    --include-module=apps.api_server.main `
    --include-module=apps.api_server.routes.auth `
    --include-module=apps.api_server.routes.tasks `
    --include-module=apps.api_server.routes.approvals `
    --include-module=apps.api_server.routes.gateway_approvals `
    --include-module=packages.executor.tools._auto_import `
    "--include-data-dir=$controlCore\configs=configs" `
    "--include-data-dir=$controlCore\alembic=alembic" `
    "--include-data-files=$controlCore\alembic\env.py=alembic\env.py" `
    "--include-data-files=$controlCore\alembic\versions\*.py=alembic\versions\" `
    "--include-data-file=$controlCore\alembic.ini=alembic.ini" `
    "--include-data-file=$bootstrapDatabase=bootstrap\agent_platform.db" `
    "--include-data-file=$bootstrapManifest=bootstrap\manifest.json" `
    --include-module=win32api `
    --include-module=win32con `
    --include-module=win32file `
    --include-module=win32pipe `
    --include-module=win32security `
    --nofollow-import-to=cv2 `
    --nofollow-import-to=numpy `
    --nofollow-import-to=PIL `
    --nofollow-import-to=windows_capture `
    --nofollow-import-to=tests `
    --nofollow-import-to=*.tests `
    --nofollow-import-to=*.tests.* `
    --nofollow-import-to=pytest `
    --nofollow-import-to=pytest_asyncio `
    --nofollow-import-to=playwright `
    --nofollow-import-to=pygments `
    --nofollow-import-to=strawberry `
    --nofollow-import-to=packages.graphql `
    --nofollow-import-to=redis `
    --nofollow-import-to=psycopg2 `
    --nofollow-import-to=sqlalchemy.dialects.firebird `
    --nofollow-import-to=sqlalchemy.dialects.mariadb `
    --nofollow-import-to=sqlalchemy.dialects.mssql `
    --nofollow-import-to=sqlalchemy.dialects.mysql `
    --nofollow-import-to=sqlalchemy.dialects.oracle `
    --nofollow-import-to=sqlalchemy.dialects.sybase `
    --include-windows-runtime-dlls=no `
    --assume-yes-for-downloads `
    $sourcePath
  if ($LASTEXITCODE -ne 0) { throw 'Nuitka sidecar build failed' }
}
finally {
  Pop-Location
}

$artifact = Join-Path $output "$sourceStem.dist\sidecar.exe"
if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) { throw "missing artifact: $artifact" }
$files = Get-ChildItem (Split-Path $artifact -Parent) -Recurse -File
$resourceDir = [IO.Path]::GetFullPath((Join-Path $repository 'apps\desktop\src-tauri\resources\sidecar'))
$resourceParent = [IO.Path]::GetFullPath((Split-Path $resourceDir -Parent)).TrimEnd('\')
if (-not $resourceDir.StartsWith("$resourceParent\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "refusing to replace resources outside the desktop resource directory: $resourceDir"
}
if (Test-Path -LiteralPath $resourceDir) {
  Remove-Item -LiteralPath $resourceDir -Recurse -Force
}
New-Item -ItemType Directory -Path $resourceDir -Force | Out-Null
Copy-Item -Path (Join-Path (Split-Path $artifact -Parent) '*') -Destination $resourceDir -Recurse -Force
[pscustomobject]@{
  python = (& $python --version)
  nuitka = (& $python -m nuitka --version | Select-Object -First 1)
  source = $sourcePath
  artifact = $artifact
  compilation_report = $compilationReport
  jobs = $Jobs
  keep_build = [bool]$KeepBuild
  files = $files.Count
  size_mb = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 3)
  sha256 = (Get-FileHash $artifact -Algorithm SHA256).Hash
} | ConvertTo-Json
