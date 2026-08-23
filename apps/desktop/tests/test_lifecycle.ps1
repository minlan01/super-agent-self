param(
  [string]$Exe,
  [string]$Python,
  [string]$Sidecar
)

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
if (-not $Exe) { $Exe = Join-Path $repository 'apps\desktop\src-tauri\target\release\tauri-spike.exe' }
if (-not (Test-Path -LiteralPath $Exe)) { throw "Desktop executable not found: $Exe" }
if ($Python) { $env:ZCODE_PYTHON = $Python }
if ($Sidecar) { $env:ZCODE_SIDECAR = $Sidecar }
$activeParents = New-Object System.Collections.Generic.List[System.Diagnostics.Process]

function Get-SidecarChild {
  param([int]$ParentPid)
  return Get-CimInstance Win32_Process | Where-Object {
    $_.ParentProcessId -eq $ParentPid -and $_.CommandLine -match 'control_core_sidecar|sidecar\.exe'
  } | Select-Object -First 1
}

function Get-ReadyCount {
  param([string]$LogPath)
  if (-not (Test-Path -LiteralPath $LogPath)) { return 0 }
  return @((Get-Content -LiteralPath $LogPath -ErrorAction SilentlyContinue) | Where-Object { $_ -match 'control-core sidecar ready' }).Count
}

function Wait-Ready {
  param([System.Diagnostics.Process]$Parent, [string]$LogPath, [int]$PreviousPid = 0, [int]$PreviousReadyCount = 0, [int]$TimeoutSeconds = 15)
  $watch = [Diagnostics.Stopwatch]::StartNew()
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    $Parent.Refresh()
    if ($Parent.HasExited) { return $null }
    if (Test-Path -LiteralPath $LogPath) {
      $log = Get-Content -LiteralPath $LogPath -Raw -ErrorAction SilentlyContinue
      $readyCount = @($log -split "`r?`n" | Where-Object { $_ -match 'control-core sidecar ready' }).Count
      if ($readyCount -gt $PreviousReadyCount) {
        # Readiness is the timing boundary. Resolve the child PID only after
        # stopping the clock so WMI latency cannot distort startup evidence.
        $watch.Stop()
        $elapsed = [math]::Round($watch.Elapsed.TotalSeconds, 3)
        $child = $null
        for ($attempt = 0; $attempt -lt 20 -and -not $child; $attempt++) {
          $child = Get-SidecarChild $Parent.Id
          if (-not $child) { Start-Sleep -Milliseconds 25 }
        }
        if (-not $child) { throw "Sidecar PID was not visible after readiness for parent $($Parent.Id)" }
        if ($child.ProcessId -eq $PreviousPid) {
          throw "Readiness advanced but sidecar PID did not change (PID $PreviousPid)"
        }
        return [pscustomobject]@{ pid = [int]$child.ProcessId; elapsed_s = $elapsed; ready_count = $readyCount }
      }
    }
    Start-Sleep -Milliseconds 20
  }
  return $null
}

function Wait-Gone {
  param([int]$ProcessId, [int]$TimeoutSeconds = 8)
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return $true }
    Start-Sleep -Milliseconds 50
  }
  return (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue))
}

function Start-TestParent {
  $dataDir = Join-Path ([IO.Path]::GetTempPath()) ("zcode-lifecycle-" + [Guid]::NewGuid().ToString('N'))
  $env:ZCODE_DATA_DIR = $dataDir
  $process = Start-Process -FilePath $Exe -PassThru
  $activeParents.Add($process)
  return [pscustomobject]@{ parent = $process; log = (Join-Path $dataDir 'logs\sidecar.log') }
}

$results = [ordered]@{}
try {
  # Forced parent termination must close the Job Object and kill the child.
  $phase1 = Start-TestParent
  $ready = Wait-Ready $phase1.parent $phase1.log
  if (-not $ready) { throw "Desktop did not become ready; parent exited=$($phase1.parent.HasExited)" }
  $results.startup_s = [math]::Round($ready.elapsed_s, 3)
  $results.parent_pid = $phase1.parent.Id
  $results.sidecar_pid = $ready.pid
  Stop-Process -Id $phase1.parent.Id -Force
  $results.forced_parent_cleanup = Wait-Gone $ready.pid

  # Normal close asks Rust to send ipc.shutdown before the Job Object fallback.
  $phase2 = Start-TestParent
  $ready = Wait-Ready $phase2.parent $phase2.log
  if (-not $ready) { throw 'Desktop did not start for normal-close test' }
  $windowDeadline = (Get-Date).AddSeconds(10)
  while ($phase2.parent.MainWindowHandle -eq 0 -and (Get-Date) -lt $windowDeadline) {
    Start-Sleep -Milliseconds 100
    $phase2.parent.Refresh()
  }
  $closeRequested = $phase2.parent.MainWindowHandle -ne 0 -and $phase2.parent.CloseMainWindow()
  $closeDeadline = (Get-Date).AddSeconds(10)
  while (-not $phase2.parent.HasExited -and (Get-Date) -lt $closeDeadline) {
    Start-Sleep -Milliseconds 100
    $phase2.parent.Refresh()
  }
  $results.normal_close_cleanup = ($closeRequested -and $phase2.parent.HasExited -and (Wait-Gone $ready.pid))

  # The monitor restarts exactly three child crashes and leaves the shell open
  # without a fourth replacement.
  $phase3 = Start-TestParent
  $ready = Wait-Ready $phase3.parent $phase3.log
  if (-not $ready) { throw 'Desktop did not start for restart test' }
  $restartPids = New-Object System.Collections.Generic.List[int]
  $restartPids.Add($ready.pid)
  $readyCount = $ready.ready_count
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    $oldPid = $restartPids[-1]
    Stop-Process -Id $oldPid -Force
    $replacement = Wait-Ready $phase3.parent $phase3.log $oldPid $readyCount 12
    if (-not $replacement) { throw "sidecar did not restart after crash $attempt" }
    $restartPids.Add($replacement.pid)
    $readyCount = $replacement.ready_count
  }
  $fourthPid = $restartPids[-1]
  Stop-Process -Id $fourthPid -Force
  Start-Sleep -Seconds 3
  $phase3.parent.Refresh()
  $results.restart_pids = @($restartPids)
  $results.first_three_restarted = ($restartPids.Count -eq 4 -and (@($restartPids | Select-Object -Unique).Count -eq 4))
  $results.fourth_crash_stopped = (-not (Get-SidecarChild $phase3.parent.Id) -and -not $phase3.parent.HasExited)
  Stop-Process -Id $phase3.parent.Id -Force -ErrorAction SilentlyContinue
  $results.final_sidecar_released = Wait-Gone $fourthPid
  $results.passed = ($results.forced_parent_cleanup -and $results.normal_close_cleanup -and $results.first_three_restarted -and $results.fourth_crash_stopped -and $results.final_sidecar_released)
} finally {
  foreach ($process in $activeParents) {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
  }
}

$result = [pscustomobject]$results
$result | ConvertTo-Json
if (-not $result.passed) { exit 1 }
