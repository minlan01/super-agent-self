param(
  [string]$Sidecar,
  [string]$EvidenceDir
)

# GA-1.3 (4): second-account STORAGE ACL test — a peer local account must not
# be able to read the owner's DB, logs, or workspace. Pipe error 5 is proven
# separately by test_second_account_dacl.ps1; this script proves storage ACL
# denial with its own evidence.

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$controlCore = Join-Path $repository 'services\control-core'
if (-not $Sidecar) { $Sidecar = Join-Path $repository 'apps\desktop\src-tauri\resources\sidecar\sidecar.exe' }
if (-not $EvidenceDir) { $EvidenceDir = Join-Path $controlCore 'artifacts\p4-second-account-storage-acl' }
if (-not (Test-Path -LiteralPath $Sidecar)) { throw "Sidecar not found: $Sidecar" }

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'An elevated PowerShell session is required to create the temporary local user.'
}

New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$suffix = [Guid]::NewGuid().ToString('N').Substring(0, 8)
$userName = "zcode_p4s_$suffix"
$random = New-Object byte[] 24
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($random) } finally { $rng.Dispose() }
$passwordText = [Convert]::ToBase64String($random) + '!aA1'
$password = ConvertTo-SecureString $passwordText -AsPlainText -Force
$credential = [PSCredential]::new("$env:COMPUTERNAME\$userName", $password)
$nonce = [Guid]::NewGuid().ToString('N')
$pipe = "\\.\pipe\zcode-control-core-storage-acl-$suffix"
$dataDir = Join-Path ([IO.Path]::GetTempPath()) "zcode-storage-acl-$suffix"
$stdoutPath = Join-Path $EvidenceDir 'sidecar-stdout.log'
$stderrPath = Join-Path $EvidenceDir 'sidecar-stderr.log'
$peerOutPath = Join-Path $EvidenceDir 'peer-probe-stdout.log'
$peerErrPath = Join-Path $EvidenceDir 'peer-probe-stderr.log'
$resultPath = Join-Path $EvidenceDir 'second-account-storage-acl.json'
$sidecarProcess = $null
$accountCreated = $false
$sidecarReady = $false
$accountRemoved = $false
$errorMessage = $null
$peerExitCode = $null
$probeResults = @()
$oldEnvironment = @{}

try {
  New-LocalUser -Name $UserName -Password $password -PasswordNeverExpires -UserMayNotChangePassword | Out-Null
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
    if (Test-Path -LiteralPath $stdoutPath) { $log += Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $stderrPath) { $log += Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue }
    if ($log -match 'control-core sidecar ready') { $sidecarReady = $true; break }
    Start-Sleep -Milliseconds 50
  }
  if (-not $sidecarReady) { throw 'Packaged sidecar did not become ready for the storage ACL test.' }

  # Owner sanity: the elevating owner must be able to read what the peer is
  # about to be denied (otherwise the probe proves nothing).
  $dbPath = Join-Path $dataDir 'agent_platform.db'
  $logsDir = Join-Path $dataDir 'logs'
  $workspaceDir = Join-Path $dataDir 'workspace'
  if (-not (Test-Path -LiteralPath $dbPath)) { throw "Owner database not found at $dbPath — data layout changed?" }
  Get-Item -LiteralPath $dbPath -ErrorAction Stop | Out-Null
  $ownerCanRead = $true

  $targets = @($dbPath, $logsDir)
  $workspacePresent = Test-Path -LiteralPath $workspaceDir
  if ($workspacePresent) { $targets += $workspaceDir }

  $targetList = ($targets | ForEach-Object { "'$_'" }) -join ','
  $peerScript = @"
`$ErrorActionPreference = 'Continue'
`$out = @()
foreach (`$t in @($targetList)) {
  `$entry = [ordered]@{ path = `$t; readable = `$false; error = `$null }
  try {
    `$item = Get-Item -LiteralPath `$t -ErrorAction Stop
    if (`$item -is [IO.FileInfo]) { Get-Content -LiteralPath `$t -TotalCount 1 -ErrorAction Stop | Out-Null }
    else { Get-ChildItem -LiteralPath `$t -ErrorAction Stop | Select-Object -First 1 | Out-Null }
    `$entry.readable = `$true
  } catch { `$entry.error = `$_.Exception.Message }
  `$out += `$entry
}
[pscustomobject]@{ results = `$out } | ConvertTo-Json -Depth 4
"@
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($peerScript))
  $peer = Start-Process -FilePath 'powershell.exe' -Credential $credential `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded) `
    -RedirectStandardOutput $peerOutPath -RedirectStandardError $peerErrPath -Wait -PassThru -WindowStyle Hidden
  $peerExitCode = $peer.ExitCode
  $peerText = ''
  if (Test-Path -LiteralPath $peerOutPath) { $peerText += Get-Content -LiteralPath $peerOutPath -Raw }
  if (Test-Path -LiteralPath $peerErrPath) { $peerText += Get-Content -LiteralPath $peerErrPath -Raw }
  try { $probeResults = ($peerText | ConvertFrom-Json).results } catch { $probeResults = @() }
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

function Get-Probe($results, $path) {
  return @($results | Where-Object { $_.path -eq $path })[0]
}
$dbProbe = Get-Probe $probeResults $dbPath
$logsProbe = Get-Probe $probeResults $logsDir
$workspaceProbe = Get-Probe $probeResults $workspaceDir

$dbDenied = ($null -ne $dbProbe -and $dbProbe.readable -eq $false -and $dbProbe.error -notmatch 'not find')
$logsDenied = ($null -ne $logsProbe -and ($logsProbe.readable -eq $false -or $logsProbe.error -match 'denied|not find'))
$workspaceDenied = if ($workspacePresent) { ($null -ne $workspaceProbe -and ($workspaceProbe.readable -eq $false -or $workspaceProbe.error -match 'denied|not find')) } else { $null }

$result = [pscustomobject]@{
  temporary_account = $userName
  account_created = $accountCreated
  account_removed = $accountRemoved
  sidecar_ready = $sidecarReady
  owner_can_read = $ownerCanRead
  peer_exit_code = $peerExitCode
  db = $dbProbe
  logs = $logsProbe
  workspace_present = $workspacePresent
  workspace = $workspaceProbe
  db_denied = $dbDenied
  logs_denied = $logsDenied
  workspace_denied = $workspaceDenied
  error = $errorMessage
  passed = ($accountCreated -and $accountRemoved -and $sidecarReady -and $ownerCanRead -and $dbDenied -and $logsDenied -and ($null -eq $workspaceDenied -or $workspaceDenied) -and -not $errorMessage)
}
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $resultPath -Encoding utf8
$result | ConvertTo-Json -Depth 6
if (-not $result.passed) { exit 1 }
