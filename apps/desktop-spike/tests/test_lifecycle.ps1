param(
  [string]$Exe = 'D:\agent\tauri-spike\src-tauri\target\release\tauri-spike.exe',
  [string]$Python = 'D:\agent\sidecar-demo\.venv312\Scripts\python.exe',
  [string]$Sidecar = 'D:\agent\tauri-spike\sidecar.py'
)

$ErrorActionPreference = 'Stop'
$env:ZCODE_PYTHON = $Python
$env:ZCODE_SIDECAR = $Sidecar
$activeParents = New-Object System.Collections.Generic.List[System.Diagnostics.Process]

function Get-SidecarPid {
  $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 9876 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($listener) { return [int]$listener.OwningProcess }
  return 0
}

function Wait-Healthy {
  param([int]$TimeoutSeconds = 10, [int]$PreviousPid = 0)
  $start = Get-Date
  while (((Get-Date) - $start).TotalSeconds -lt $TimeoutSeconds) {
    $pidValue = Get-SidecarPid
    if ($pidValue -ne 0 -and $pidValue -ne $PreviousPid) {
      try {
        $response = Invoke-RestMethod 'http://127.0.0.1:9876/health' -TimeoutSec 1 -ErrorAction Stop
        if ($response.status -eq 'ready' -and $response.nonce -and [int]$response.pid -eq $pidValue) {
          return [pscustomobject]@{ pid = $pidValue; elapsed_s = ((Get-Date) - $start).TotalSeconds }
        }
      } catch {}
    }
    Start-Sleep -Milliseconds 50
  }
  return $null
}

function Start-TestParent {
  $process = Start-Process -FilePath $Exe -PassThru
  $activeParents.Add($process)
  return $process
}

if (Get-SidecarPid) { throw 'port 9876 is already occupied before lifecycle test' }
$results = [ordered]@{}

try {
  # Phase 1: a forced parent termination must close the Job Object and kill the child.
  $parent = Start-TestParent
  $ready = Wait-Healthy 12
  if (-not $ready) { throw "Tauri failed to become healthy; parent exited=$($parent.HasExited)" }
  $phase1SidecarPid = $ready.pid
  $results.startup_s = [math]::Round($ready.elapsed_s, 3)
  $results.parent_pid = $parent.Id
  $results.sidecar_pid = $phase1SidecarPid
  Stop-Process -Id $parent.Id -Force
  Start-Sleep -Seconds 2
  $results.forced_parent_cleanup = (-not (Get-Process -Id $phase1SidecarPid -ErrorAction SilentlyContinue) -and (Get-SidecarPid) -eq 0)

  # Phase 2: a normal window close must also stop the child and release the port.
  $parent = Start-TestParent
  $ready = Wait-Healthy 12
  if (-not $ready) { throw 'Tauri failed to start for normal-close test' }
  $normalSidecarPid = $ready.pid
  $windowDeadline = (Get-Date).AddSeconds(10)
  while ($parent.MainWindowHandle -eq 0 -and (Get-Date) -lt $windowDeadline) {
    Start-Sleep -Milliseconds 100
    $parent.Refresh()
  }
  $closeRequested = $parent.MainWindowHandle -ne 0 -and $parent.CloseMainWindow()
  $closeDeadline = (Get-Date).AddSeconds(10)
  while (-not $parent.HasExited -and (Get-Date) -lt $closeDeadline) {
    Start-Sleep -Milliseconds 100
    $parent.Refresh()
  }
  Start-Sleep -Seconds 1
  $results.normal_close_cleanup = ($closeRequested -and $parent.HasExited -and -not (Get-Process -Id $normalSidecarPid -ErrorAction SilentlyContinue) -and (Get-SidecarPid) -eq 0)

  # Phase 3: restart three times, then stop after the configured crash limit.
  $parent = Start-TestParent
  $ready = Wait-Healthy 12
  if (-not $ready) { throw 'Tauri failed to start for restart test' }
  $restartPids = New-Object System.Collections.Generic.List[int]
  $restartPids.Add($ready.pid)
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    $oldPid = $restartPids[-1]
    Stop-Process -Id $oldPid -Force
    $replacement = Wait-Healthy 8 $oldPid
    if (-not $replacement) { throw "sidecar did not restart after crash $attempt" }
    $restartPids.Add($replacement.pid)
  }
  $fourthPid = $restartPids[-1]
  Stop-Process -Id $fourthPid -Force
  Start-Sleep -Seconds 3
  $results.restart_pids = @($restartPids)
  $results.first_three_restarted = ($restartPids.Count -eq 4 -and (@($restartPids | Select-Object -Unique).Count -eq 4))
  $results.fourth_crash_stopped = ((Get-SidecarPid) -eq 0 -and -not $parent.HasExited)
  Stop-Process -Id $parent.Id -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 1
  $results.final_port_released = ((Get-SidecarPid) -eq 0)
  $results.passed = ($results.forced_parent_cleanup -and $results.normal_close_cleanup -and $results.first_three_restarted -and $results.fourth_crash_stopped -and $results.final_port_released)
} finally {
  foreach ($process in $activeParents) {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
  }
}

$result = [pscustomobject]$results
$result | ConvertTo-Json
if (-not $result.passed) { exit 1 }
