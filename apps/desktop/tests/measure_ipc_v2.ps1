param(
  [int]$Samples = 100,
  [int]$Warmup = 10,
  [string]$PipeName = 'zcode-sidecar-spike',
  [string]$Nonce = 'development'
)

$ErrorActionPreference = 'Stop'

function Invoke-PipeRoundTrip {
  param([string]$Message)
  $client = New-Object System.IO.Pipes.NamedPipeClientStream('.', $PipeName, [System.IO.Pipes.PipeDirection]::InOut)
  try {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $client.Connect(2000)
    $payload = [Text.Encoding]::UTF8.GetBytes((ConvertTo-Json @{ msg = $Message; nonce = $Nonce } -Compress))
    $client.Write($payload, 0, $payload.Length)
    $client.Flush()
    $buffer = New-Object byte[] 65536
    $read = $client.Read($buffer, 0, $buffer.Length)
    $watch.Stop()
    if ($read -le 0) { throw 'empty response' }
    $response = [Text.Encoding]::UTF8.GetString($buffer, 0, $read) | ConvertFrom-Json
    if ($response.echoed -ne $Message) { throw "unexpected echo: $($response.echoed)" }
    if ($response.nonce -ne $Nonce) { throw "unexpected nonce: $($response.nonce)" }
    return $watch.Elapsed.TotalMilliseconds
  } finally {
    $client.Dispose()
  }
}

1..$Warmup | ForEach-Object { [void](Invoke-PipeRoundTrip 'warmup') }
$times = New-Object System.Collections.Generic.List[double]
$failures = 0
1..$Samples | ForEach-Object {
  try { $times.Add((Invoke-PipeRoundTrip 'ping')) }
  catch { $failures++ }
}
if ($times.Count -eq 0) { throw 'all IPC samples failed' }
$sorted = @($times | Sort-Object)
$p50 = $sorted[[Math]::Max(0, [int][Math]::Ceiling(0.50 * $sorted.Count) - 1)]
$p95 = $sorted[[Math]::Max(0, [int][Math]::Ceiling(0.95 * $sorted.Count) - 1)]
$max = $sorted[-1]
$result = [pscustomobject]@{
  samples = $Samples
  successes = $times.Count
  failures = $failures
  p50_ms = [math]::Round($p50, 3)
  p95_ms = [math]::Round($p95, 3)
  max_ms = [math]::Round($max, 3)
  passed = ($failures -eq 0 -and $p95 -le 100)
}
$result | ConvertTo-Json
if (-not $result.passed) { exit 1 }
