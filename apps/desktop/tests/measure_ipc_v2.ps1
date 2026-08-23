param(
  [int]$Samples = 100,
  [int]$Warmup = 10,
  [string]$Python,
  [string]$Sidecar,
  [string]$PipeName
)

$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
if (-not $Python) { $Python = Join-Path $repository 'services\control-core\.venv-win\Scripts\python.exe' }
if (-not $Sidecar) { $Sidecar = Join-Path $repository 'services\control-core\scripts\nuitka-build\control_core_sidecar.py' }
if (-not $PipeName) { $PipeName = "zcode-control-core-v1-measure-$PID" }
if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
if (-not (Test-Path -LiteralPath $Sidecar)) { throw "Sidecar not found: $Sidecar" }

function Read-Exact {
  param([System.IO.Pipes.NamedPipeClientStream]$Client, [int]$Count)
  $buffer = New-Object byte[] $Count
  $offset = 0
  while ($offset -lt $Count) {
    $read = $Client.Read($buffer, $offset, $Count - $offset)
    if ($read -le 0) { throw 'sidecar closed the pipe' }
    $offset += $read
  }
  return $buffer
}

function Invoke-IpcRequest {
  param([System.IO.Pipes.NamedPipeClientStream]$Client, [hashtable]$Message)
  $payload = [Text.Encoding]::UTF8.GetBytes(($Message | ConvertTo-Json -Compress -Depth 8))
  if ($payload.Length -gt 1MB) { throw 'IPC request exceeds 1 MiB' }
  $header = [BitConverter]::GetBytes([uint32]$payload.Length)
  $Client.Write($header, 0, $header.Length)
  $Client.Write($payload, 0, $payload.Length)
  $Client.Flush()
  $responseHeader = Read-Exact $Client 4
  $responseLength = [BitConverter]::ToUInt32($responseHeader, 0)
  if ($responseLength -gt 1MB) { throw 'IPC response exceeds 1 MiB' }
  $response = Read-Exact $Client ([int]$responseLength)
  return [Text.Encoding]::UTF8.GetString($response) | ConvertFrom-Json
}

function Connect-Ipc {
  $client = New-Object System.IO.Pipes.NamedPipeClientStream('.', $PipeName, [System.IO.Pipes.PipeDirection]::InOut)
  $client.Connect(10000)
  $client.ReadMode = [System.IO.Pipes.PipeTransmissionMode]::Byte
  return $client
}

function Invoke-PipeRoundTrip {
  $client = Connect-Ipc
  try {
    $hello = Invoke-IpcRequest $client @{
      v = 1; id = 1; method = 'hello'; params = @{
        nonce = $env:ZCODE_RUN_NONCE; client_versions = @(1); pid = $PID
      }
    }
    if (-not $hello.ok) { throw "hello failed: $($hello.error.code)" }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $pong = Invoke-IpcRequest $client @{ v = 1; id = 2; method = 'ipc.ping'; params = @{} }
    $watch.Stop()
    if (-not $pong.ok -or -not $pong.data.pong) { throw 'invalid ping response' }
    return $watch.Elapsed.TotalMilliseconds
  } finally {
    $client.Dispose()
  }
}

$saved = @{}
foreach ($key in 'ZCODE_RUN_NONCE', 'ZCODE_LAUNCHER_PID', 'ZCODE_PIPE', 'ZCODE_DATA_DIR', 'TESTING', 'LLM_PROVIDER') {
  $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
$work = Join-Path ([IO.Path]::GetTempPath()) ("zcode-ipc-v1-" + [Guid]::NewGuid().ToString('N'))
$log = Join-Path $work 'sidecar.log'
New-Item -ItemType Directory -Path $work -Force | Out-Null
$env:ZCODE_RUN_NONCE = [Guid]::NewGuid().ToString('N')
$env:ZCODE_LAUNCHER_PID = $PID
$env:ZCODE_PIPE = "\\.\pipe\$PipeName"
$env:ZCODE_DATA_DIR = (Join-Path $work 'data')
$env:ZCODE_RESOURCE_ROOT = (Split-Path $Sidecar -Parent)
$env:TESTING = '1'
$env:LLM_PROVIDER = 'mock'
$process = $null

try {
  $isExecutable = [IO.Path]::GetExtension($Sidecar).Equals('.exe', [StringComparison]::OrdinalIgnoreCase)
  $startArgs = @{
    WorkingDirectory = (Split-Path $Sidecar -Parent)
    PassThru = $true
    RedirectStandardOutput = $log
    RedirectStandardError = "$log.err"
  }
  if ($isExecutable) {
    $process = Start-Process -FilePath $Sidecar @startArgs
  } else {
    $process = Start-Process -FilePath $Python -ArgumentList @($Sidecar) @startArgs
  }
  1..$Warmup | ForEach-Object { [void](Invoke-PipeRoundTrip) }
  $times = New-Object System.Collections.Generic.List[double]
  $failures = 0
  1..$Samples | ForEach-Object {
    try { $times.Add((Invoke-PipeRoundTrip)) }
    catch { $failures++ }
  }
  if ($times.Count -eq 0) { throw 'all IPC samples failed' }
  $sorted = @($times | Sort-Object)
  $p50 = $sorted[[Math]::Max(0, [int][Math]::Ceiling(0.50 * $sorted.Count) - 1)]
  $p95 = $sorted[[Math]::Max(0, [int][Math]::Ceiling(0.95 * $sorted.Count) - 1)]
  $max = $sorted[-1]
  $result = [pscustomobject]@{
    pipe = $env:ZCODE_PIPE
    samples = $Samples
    successes = $times.Count
    failures = $failures
    p50_ms = [math]::Round($p50, 3)
    p95_ms = [math]::Round($p95, 3)
    max_ms = [math]::Round($max, 3)
    passed = ($failures -eq 0 -and $p95 -le 100)
    log = $log
  }
  $result | ConvertTo-Json
  if (-not $result.passed) { exit 1 }
} finally {
  if ($process -and -not $process.HasExited) {
    try {
      $client = Connect-Ipc
      try {
        $hello = Invoke-IpcRequest $client @{ v = 1; id = 1; method = 'hello'; params = @{ nonce = $env:ZCODE_RUN_NONCE; client_versions = @(1); pid = $PID } }
        if ($hello.ok) { [void](Invoke-IpcRequest $client @{ v = 1; id = 2; method = 'ipc.shutdown'; params = @{} }) }
      } finally { $client.Dispose() }
      $process.WaitForExit(10000) | Out-Null
    } catch {}
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
  }
  foreach ($key in $saved.Keys) {
    [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process')
  }
}
