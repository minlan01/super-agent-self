param(
  [int]$Runs = 3,
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

function Get-SidecarChild {
  param([int]$ParentPid)
  return Get-CimInstance Win32_Process | Where-Object {
    $_.ParentProcessId -eq $ParentPid -and $_.CommandLine -match 'control_core_sidecar|sidecar\.exe'
  } | Select-Object -First 1
}

function Wait-Ready {
  param(
    [System.Diagnostics.Process]$Parent,
    [string]$LogPath,
    [Diagnostics.Stopwatch]$StartupWatch,
    [int]$TimeoutSeconds = 60  # cold install (fresh DB + migrations + first import) can exceed 15s
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    # HasExited performs the required state check. Calling Refresh() on every
    # 20 ms poll performs an extra Windows process query and can add seconds to
    # the measured launch time on a GUI process.
    if ($Parent.HasExited) { return $null }
    if (Test-Path -LiteralPath $LogPath) {
      $log = Get-Content -LiteralPath $LogPath -Raw -ErrorAction SilentlyContinue
      if ($log -match 'control-core sidecar ready') {
        # Stop the clock at the readiness signal. WMI process-tree lookup is
        # intentionally outside the measured interval because it is slow and
        # can add several seconds of noise on a busy Windows host.
        # Freeze the end-to-end launch clock before the WMI process-tree lookup.
        $StartupWatch.Stop()
        $elapsed = [math]::Round($StartupWatch.Elapsed.TotalSeconds, 3)
        $child = $null
        for ($attempt = 0; $attempt -lt 20 -and -not $child; $attempt++) {
          $child = Get-SidecarChild $Parent.Id
          if (-not $child) { Start-Sleep -Milliseconds 25 }
        }
        if (-not $child) { throw "Sidecar PID was not visible after readiness for parent $($Parent.Id)" }
        return [pscustomobject]@{ sidecar_pid = [int]$child.ProcessId; elapsed_s = $elapsed }
      }
    }
    Start-Sleep -Milliseconds 20
  }
  return $null
}

$measurements = New-Object System.Collections.Generic.List[double]
for ($run = 1; $run -le $Runs; $run++) {
  $dataDir = Join-Path ([IO.Path]::GetTempPath()) ("zcode-startup-" + [Guid]::NewGuid().ToString('N'))
  $logPath = Join-Path $dataDir 'logs\sidecar.log'
  $env:ZCODE_DATA_DIR = $dataDir
  $parent = $null
  $ready = $null
  try {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $parent = Start-Process -FilePath $Exe -PassThru
    $ready = Wait-Ready $parent $logPath $watch
    if (-not $ready) { throw "Desktop did not complete sidecar startup during run $run" }
    # Wait-Ready stops its own clock at the readiness log line before doing
    # the WMI process-tree lookup, so PID discovery cannot inflate startup.
    $measurements.Add([double]$ready.elapsed_s)
  } finally {
    if ($parent -and -not $parent.HasExited) {
      Stop-Process -Id $parent.Id -Force -ErrorAction SilentlyContinue
    }
    $cleanupDeadline = (Get-Date).AddSeconds(5)
    while ($ready -and (Get-Process -Id $ready.sidecar_pid -ErrorAction SilentlyContinue) -and (Get-Date) -lt $cleanupDeadline) {
      Start-Sleep -Milliseconds 50
    }
    if ($ready -and (Get-Process -Id $ready.sidecar_pid -ErrorAction SilentlyContinue)) {
      throw "Job Object cleanup left sidecar PID $($ready.sidecar_pid) after run $run"
    }
  }
}

$sorted = @($measurements | Sort-Object)
$result = [pscustomobject]@{
  runs = $Runs
  seconds = @($measurements | ForEach-Object { [math]::Round($_, 3) })
  min_s = [math]::Round($sorted[0], 3)
  median_s = [math]::Round($sorted[[int][math]::Floor($sorted.Count / 2)], 3)
  max_s = [math]::Round($sorted[-1], 3)
  all_passed = (($sorted | Where-Object { $_ -gt 5 }).Count -eq 0)
}
$result | ConvertTo-Json
if (-not $result.all_passed) { exit 1 }
