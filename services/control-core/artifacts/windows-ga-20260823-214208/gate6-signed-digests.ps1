$ErrorActionPreference = 'Stop'
# Pure-cmdlet verification of signed digests (ASCII-only).
$Repo = 'D:\agent\Agents\super-agent-self'
$Evidence = Join-Path $Repo 'services\control-core\artifacts\windows-ga-20260823-214208'
$Thumbprint = '8F430FFBFE152E18D58A0E9A4ECEBC7C9E8F4E1B'

$Sidecar = Join-Path $Repo 'apps\desktop\src-tauri\resources\sidecar\sidecar.exe'
$Desktop = Join-Path $Repo 'apps\desktop\src-tauri\target\release\tauri-spike.exe'
$Installer = Join-Path $Repo 'apps\desktop\src-tauri\target\release\bundle\nsis\Zcode Desktop Agent_1.0.0_x64-setup.exe'

$signed = @($Sidecar, $Desktop, $Installer) | ForEach-Object {
  $item = Get-Item -LiteralPath $_
  $sig = Get-AuthenticodeSignature -LiteralPath $item.FullName
  if (-not $sig.SignerCertificate) { throw "no signature: $($item.FullName)" }
  if ($sig.SignerCertificate.Thumbprint -ne $Thumbprint) {
    throw "signer identity mismatch: $($item.FullName) -> $($sig.SignerCertificate.Thumbprint)"
  }
  [pscustomobject]@{
    path = $item.FullName
    size = $item.Length
    sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
    status = $sig.Status.ToString()
    signer = $sig.SignerCertificate.Subject
    thumbprint = $sig.SignerCertificate.Thumbprint
    time_stamped = [bool]$sig.TimeStamperCertificate
    mtime = $item.LastWriteTime.ToString('o')
  }
}
$signed | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Evidence 'signed-digests.json') -Encoding UTF8
$signed | Format-Table path, size, status, time_stamped -AutoSize
Write-Output 'SIGNED-DIGESTS-OK'
