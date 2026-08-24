param(
  # GA-1.3 (3): wrapper for the installed-release audit chain. The database
  # path is MANDATORY and must be absolute — expected value is
  # %LOCALAPPDATA%\zcode\agent_platform.db of the installing user.
  [Parameter(Mandatory = $true)]
  [string]$DatabasePath,
  [string]$EvidencePath = ''
)

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$controlCore = Join-Path $repository 'services\control-core'
$python = Join-Path $controlCore '.venv-win\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "control-core venv python not found: $python" }

$database = [IO.Path]::GetFullPath($DatabasePath)
if (-not [IO.Path]::IsPathRooted($DatabasePath)) { throw "DatabasePath must be absolute: $DatabasePath" }
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) { throw "Installed database not found: $database" }

if (-not $EvidencePath) {
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $EvidencePath = Join-Path $controlCore "artifacts\installed-audit-chain-$stamp.txt"
}
New-Item -ItemType Directory -Force -Path (Split-Path $EvidencePath -Parent) | Out-Null

$dbHash = (Get-FileHash -LiteralPath $database -Algorithm SHA256).Hash
"database: $database" | Set-Content -LiteralPath $EvidencePath -Encoding utf8
"database_sha256: $dbHash" | Add-Content -LiteralPath $EvidencePath -Encoding utf8
"verified_at: $((Get-Date).ToString('o'))" | Add-Content -LiteralPath $EvidencePath -Encoding utf8

$oldUrl = $env:DATABASE_URL
try {
  $env:DATABASE_URL = 'sqlite:///' + $database.Replace('\', '/')
  & $python (Join-Path $controlCore 'scripts\verify_audit_chain.py') 2>&1 |
    Tee-Object -FilePath $EvidencePath -Append
  $exit = $LASTEXITCODE
} finally {
  [Environment]::SetEnvironmentVariable('DATABASE_URL', $oldUrl, 'Process')
}

if ($exit -ne 0) { throw "Installed audit chain verification failed (exit $exit). Evidence: $EvidencePath" }
Write-Output "Installed audit chain OK. Evidence: $EvidencePath"
exit 0
