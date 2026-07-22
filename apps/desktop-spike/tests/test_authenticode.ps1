param(
  [string]$Exe = 'D:\agent\sidecar-demo\dist\sidecar.exe'
)

$ErrorActionPreference = 'Stop'
$subject = "CN=Zcode Spike Temporary $([Guid]::NewGuid())"
$cert = $null
$rootPath = $null
$cerPath = 'D:\agent\sidecar-demo\zcode-spike-temporary.cer'
$tamperedPath = Join-Path (Split-Path -Parent $Exe) "$([IO.Path]::GetFileNameWithoutExtension($Exe))-tampered.exe"
$result = $null

try {
  $cert = New-SelfSignedCertificate -Subject $subject -Type CodeSigningCert -KeyUsage DigitalSignature -FriendlyName 'Zcode Spike Temporary' -CertStoreLocation 'Cert:\CurrentUser\My' -KeyAlgorithm RSA -KeyLength 2048 -NotAfter (Get-Date).AddDays(7)
  Export-Certificate -Cert $cert -FilePath $cerPath -Force | Out-Null
  $root = Import-Certificate -FilePath $cerPath -CertStoreLocation 'Cert:\CurrentUser\Root'
  $rootPath = "Cert:\CurrentUser\Root\$($root.Thumbprint)"

  $signed = Set-AuthenticodeSignature -FilePath $Exe -Certificate $cert -HashAlgorithm SHA256
  $verified = Get-AuthenticodeSignature -FilePath $Exe
  Copy-Item -LiteralPath $Exe -Destination $tamperedPath -Force
  $bytes = [IO.File]::ReadAllBytes($tamperedPath)
  $offset = [Math]::Min(4096, $bytes.Length - 1)
  $bytes[$offset] = $bytes[$offset] -bxor 0xFF
  [IO.File]::WriteAllBytes($tamperedPath, $bytes)
  $tampered = Get-AuthenticodeSignature -FilePath $tamperedPath

  $result = [pscustomobject]@{
    sign_status = $signed.Status.ToString()
    verify_status = $verified.Status.ToString()
    signer = $verified.SignerCertificate.Subject
    tampered_status = $tampered.Status.ToString()
    valid_passed = ($verified.Status -eq 'Valid')
    tamper_passed = ($tampered.Status -eq 'HashMismatch')
    passed = ($verified.Status -eq 'Valid' -and $tampered.Status -eq 'HashMismatch')
  }
} finally {
  if ($cert) { Remove-Item -LiteralPath "Cert:\CurrentUser\My\$($cert.Thumbprint)" -Force -ErrorAction SilentlyContinue }
  if ($rootPath) { Remove-Item -LiteralPath $rootPath -Force -ErrorAction SilentlyContinue }
  Remove-Item -LiteralPath $cerPath -Force -ErrorAction SilentlyContinue
}

$result | ConvertTo-Json
if (-not $result.passed) { exit 1 }
