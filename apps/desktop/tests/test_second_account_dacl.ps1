param(
  [string]$Sidecar,
  [string]$EvidenceDir
)

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$controlCore = Join-Path $repository 'services\control-core'
if (-not $Sidecar) { $Sidecar = Join-Path $repository 'apps\desktop\src-tauri\resources\sidecar\sidecar.exe' }
if (-not $EvidenceDir) { $EvidenceDir = Join-Path $controlCore 'artifacts\p4-second-account-dacl' }
if (-not (Test-Path -LiteralPath $Sidecar)) { throw "Sidecar not found: $Sidecar" }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'An elevated PowerShell session is required to create the temporary local user.'
}

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$suffix = [Guid]::NewGuid().ToString('N').Substring(0, 8)
$userName = "zcode_p4_$suffix"
$random = New-Object byte[] 24
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
  $rng.GetBytes($random)
} finally {
  $rng.Dispose()
}
$passwordText = [Convert]::ToBase64String($random) + '!aA1'
$password = ConvertTo-SecureString $passwordText -AsPlainText -Force
$credential = [PSCredential]::new("$env:COMPUTERNAME\$userName", $password)
$nonce = [Guid]::NewGuid().ToString('N')
$pipe = "\\.\pipe\zcode-control-core-v1-second-account-$suffix"
$dataDir = Join-Path ([IO.Path]::GetTempPath()) "zcode-dacl-$suffix"
$stdoutPath = Join-Path $EvidenceDir 'sidecar-stdout.log'
$stderrPath = Join-Path $EvidenceDir 'sidecar-stderr.log'
$clientOutPath = Join-Path $EvidenceDir 'second-account-client-stdout.log'
$clientErrPath = Join-Path $EvidenceDir 'second-account-client-stderr.log'
$resultPath = Join-Path $EvidenceDir 'second-account-dacl.json'
$clientScript = Join-Path $PSScriptRoot 'second_account_pipe_client.ps1'
$sidecarProcess = $null
$accountCreated = $false
$sidecarReady = $false
$accessDenied = $false
$clientExitCode = $null
$errorMessage = $null
$accountRemoved = $false
$oldEnvironment = @{}

try {
  New-LocalUser -Name $userName -Password $password -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
  $accountCreated = $true

  foreach ($name in @('ZCODE_RUN_NONCE', 'ZCODE_LAUNCHER_PID', 'ZCODE_PIPE', 'ZCODE_DATA_DIR', 'ZCODE_RESOURCE_ROOT', 'TESTING', 'LLM_PROVIDER', 'PYTHONDONTWRITEBYTECODE')) {
    $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
  }
  $env:ZCODE_RUN_NONCE = $nonce
  $env:ZCODE_LAUNCHER_PID = [string]$PID
  $env:ZCODE_PIPE = $pipe
  $env:ZCODE_DATA_DIR = $dataDir
  $env:ZCODE_RESOURCE_ROOT = Split-Path $Sidecar -Parent
  $env:TESTING = '1'
  $env:LLM_PROVIDER = 'mock'
  $env:PYTHONDONTWRITEBYTECODE = '1'

  $sidecarProcess = Start-Process -FilePath $Sidecar -WorkingDirectory (Split-Path $Sidecar -Parent) `
    -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru -WindowStyle Hidden

  $deadline = (Get-Date).AddSeconds(20)
  while ((Get-Date) -lt $deadline) {
    $sidecarProcess.Refresh()
    if ($sidecarProcess.HasExited) { break }
    $log = ''
    if (Test-Path -LiteralPath $stdoutPath) {
      $log += Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $stderrPath) {
      $log += Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
    }
    if ($log -match 'control-core sidecar ready') {
      $sidecarReady = $true
      break
    }
    Start-Sleep -Milliseconds 50
  }
  if (-not $sidecarReady) { throw 'Packaged sidecar did not become ready for the DACL test.' }

  $pipeName = $pipe.Substring('\\.\pipe\'.Length)
  $client = Start-Process -FilePath 'powershell.exe' -Credential $credential `
    -WorkingDirectory $repository -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $clientScript, '-PipeName', $pipeName) `
    -RedirectStandardOutput $clientOutPath -RedirectStandardError $clientErrPath -Wait -PassThru -WindowStyle Hidden
  $clientExitCode = $client.ExitCode
  $clientText = ''
  if (Test-Path -LiteralPath $clientOutPath) { $clientText += Get-Content -LiteralPath $clientOutPath -Raw }
  if (Test-Path -LiteralPath $clientErrPath) { $clientText += Get-Content -LiteralPath $clientErrPath -Raw }
  $accessDenied = $clientExitCode -eq 5 -and $clientText -match '"native_error"\s*:\s*5'
} catch {
  $errorMessage = $_.Exception.Message
} finally {
  if ($sidecarProcess -and -not $sidecarProcess.HasExited) {
    Stop-Process -Id $sidecarProcess.Id -Force -ErrorAction SilentlyContinue
    $sidecarProcess.WaitForExit(5000) | Out-Null
  }
  foreach ($name in $oldEnvironment.Keys) {
    [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name], 'Process')
  }
  if ($accountCreated) {
    Remove-LocalUser -Name $userName -ErrorAction SilentlyContinue
    $accountRemoved = -not [bool](Get-LocalUser -Name $userName -ErrorAction SilentlyContinue)
  }
  if (Test-Path -LiteralPath $dataDir) {
    Remove-Item -LiteralPath $dataDir -Recurse -Force -ErrorAction SilentlyContinue
  }
  $passwordText = $null
}

$result = [pscustomobject]@{
  temporary_account = $userName
  account_created = $accountCreated
  account_removed = $accountRemoved
  sidecar_ready = $sidecarReady
  client_exit_code = $clientExitCode
  access_denied = $accessDenied
  expected_win32_error = 5
  error = $errorMessage
  passed = ($accountCreated -and $accountRemoved -and $sidecarReady -and $accessDenied -and -not $errorMessage)
}
$result | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
$result | ConvertTo-Json
if (-not $result.passed) { exit 1 }
