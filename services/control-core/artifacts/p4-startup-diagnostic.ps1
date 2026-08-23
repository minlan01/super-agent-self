param(
  [int]$Runs = 5,
  [Parameter(Mandatory = $true)][string]$Exe,
  [Parameter(Mandatory = $true)][string]$Sidecar,
  [string]$Output,
  [switch]$NoWindowStyle
)

$ErrorActionPreference = 'Stop'
if (-not $Output) { $Output = Join-Path $PSScriptRoot 'p4-startup-diagnostic.json' }
$results = @()

function Get-FirstLogTimestamp {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  $line = Get-Content -LiteralPath $Path -TotalCount 1 -ErrorAction SilentlyContinue
  if (-not $line) { return $null }
  if ($line -match '^(?<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})') {
    return [DateTime]::ParseExact($Matches.stamp, 'yyyy-MM-dd HH:mm:ss,fff', [Globalization.CultureInfo]::InvariantCulture)
  }
  return $null
}

for ($run = 1; $run -le $Runs; $run++) {
  $dataDir = Join-Path ([IO.Path]::GetTempPath()) ("zcode-startup-diag-" + [Guid]::NewGuid().ToString('N'))
  $logPath = Join-Path $dataDir 'logs\sidecar.log'
  $env:ZCODE_DATA_DIR = $dataDir
  $env:ZCODE_SIDECAR = $Sidecar
  $parent = $null
  $watch = [Diagnostics.Stopwatch]::StartNew()
  $startedAt = Get-Date
  try {
    if ($NoWindowStyle) {
      $parent = Start-Process -FilePath $Exe -PassThru
    } else {
      $parent = Start-Process -FilePath $Exe -PassThru -WindowStyle Hidden
    }
    $startReturnedAt = Get-Date
    $readyAt = $null
    while ($watch.Elapsed.TotalSeconds -lt 20) {
      if ($parent.HasExited) { break }
      if (Test-Path -LiteralPath $logPath) {
        $log = Get-Content -LiteralPath $logPath -Raw -ErrorAction SilentlyContinue
        if ($log -match 'control-core sidecar ready') {
          $readyAt = Get-Date
          break
        }
      }
      Start-Sleep -Milliseconds 20
    }
    $firstLogAt = Get-FirstLogTimestamp $logPath
    $readyElapsed = if ($readyAt) { [math]::Round(($readyAt - $startedAt).TotalSeconds, 3) } else { $null }
    $preSidecar = if ($firstLogAt) { [math]::Round(($firstLogAt - $startedAt).TotalSeconds, 3) } else { $null }
    $results += [pscustomobject]@{
      run = $run
      parent_pid = if ($parent) { $parent.Id } else { $null }
      parent_exited = if ($parent) { $parent.HasExited } else { $true }
      start_return_s = [math]::Round(($startReturnedAt - $startedAt).TotalSeconds, 3)
      first_sidecar_log_s = $preSidecar
      ready_s = $readyElapsed
      log_path = $logPath
      log_tail = if (Test-Path -LiteralPath $logPath) { @(Get-Content -LiteralPath $logPath -Tail 12) } else { @() }
    }
  } finally {
    if ($parent -and -not $parent.HasExited) {
      Stop-Process -Id $parent.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 200
  }
}

$payload = [pscustomobject]@{
  generated_at = (Get-Date).ToString('o')
  exe = $Exe
  sidecar = $Sidecar
  exe_sha256 = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash
  sidecar_sha256 = (Get-FileHash -LiteralPath $Sidecar -Algorithm SHA256).Hash
  runs = @($results)
}
$payload | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Output -Encoding utf8
$payload | ConvertTo-Json -Depth 5
