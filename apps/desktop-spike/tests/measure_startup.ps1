param(
  [int]$Runs = 3,
  [string]$Exe = 'D:\agent\tauri-spike\src-tauri\target\release\tauri-spike.exe',
  [string]$Python = 'D:\agent\sidecar-demo\.venv312\Scripts\python.exe',
  [string]$Sidecar = 'D:\agent\tauri-spike\sidecar.py'
)

$ErrorActionPreference = 'Stop'
$env:ZCODE_PYTHON = $Python
$env:ZCODE_SIDECAR = $Sidecar
$measurements = New-Object System.Collections.Generic.List[double]

for ($run = 1; $run -le $Runs; $run++) {
  if (Get-NetTCPConnection -LocalPort 9876 -State Listen -ErrorAction SilentlyContinue) {
    throw "port 9876 occupied before run $run"
  }
  $parent = $null
  try {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $parent = Start-Process -FilePath $Exe -PassThru
    $healthy = $false
    while (-not $healthy -and $watch.Elapsed.TotalSeconds -lt 15) {
      if ($parent.HasExited) { throw "Tauri exited during run $run" }
      try {
        $response = Invoke-RestMethod 'http://127.0.0.1:9876/health' -TimeoutSec 1 -ErrorAction Stop
        $healthy = ($response.status -eq 'ready' -and $response.nonce -and [int]$response.pid -gt 0)
      } catch {
        Start-Sleep -Milliseconds 50
      }
    }
    $watch.Stop()
    if (-not $healthy) { throw "health timeout during run $run" }
    $measurements.Add($watch.Elapsed.TotalSeconds)
  } finally {
    if ($parent -and -not $parent.HasExited) {
      Stop-Process -Id $parent.Id -Force -ErrorAction SilentlyContinue
    }
    $deadline = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline -and (Get-NetTCPConnection -LocalPort 9876 -State Listen -ErrorAction SilentlyContinue)) {
      Start-Sleep -Milliseconds 50
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
