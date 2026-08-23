param(
  [Parameter(Mandatory = $true)]
  [string]$PipeName,
  [int]$TimeoutMilliseconds = 5000
)

$ErrorActionPreference = 'Stop'
$client = $null
try {
  $client = [IO.Pipes.NamedPipeClientStream]::new(
    '.',
    $PipeName,
    [IO.Pipes.PipeDirection]::InOut,
    [IO.Pipes.PipeOptions]::None
  )
  $client.Connect($TimeoutMilliseconds)
  [pscustomobject]@{
    connected = $true
    exception_type = $null
    hresult = $null
    native_error = 0
    message = $null
  } | ConvertTo-Json
  exit 0
} catch {
  $exception = $_.Exception
  while ($exception.InnerException) {
    $exception = $exception.InnerException
  }
  $hresult = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int32]$exception.HResult), 0)
  $nativeError = [int]($hresult -band 0xFFFF)
  [pscustomobject]@{
    connected = $false
    exception_type = $exception.GetType().FullName
    hresult = ('0x{0:X8}' -f $hresult)
    native_error = $nativeError
    message = $exception.Message
  } | ConvertTo-Json
  if ($nativeError -eq 5) { exit 5 }
  exit 1
} finally {
  if ($client) { $client.Dispose() }
}
