param(
  [Parameter(Mandatory = $true)]
  [string]$Exe
)

$ErrorActionPreference = 'Stop'
$sourcePath = [IO.Path]::GetFullPath($Exe)
if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
  throw "artifact does not exist: $sourcePath"
}
$sourceHashBefore = (Get-FileHash $sourcePath -Algorithm SHA256).Hash
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) "zcode-authenticode-$([Guid]::NewGuid())"
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
$workingPath = Join-Path $tempRoot ([IO.Path]::GetFileName($sourcePath))
Copy-Item -LiteralPath $sourcePath -Destination $workingPath
$subject = "CN=Zcode Spike Temporary $([Guid]::NewGuid())"
$cert = $null
$tamperedPath = Join-Path $tempRoot "$([IO.Path]::GetFileNameWithoutExtension($sourcePath))-tampered.exe"
$result = $null

function Remove-CertificateFromStore {
  param([string]$Thumbprint, [string]$StoreName)
  $store = [Security.Cryptography.X509Certificates.X509Store]::new($StoreName, 'CurrentUser')
  try {
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    $matches = $store.Certificates.Find(
      [Security.Cryptography.X509Certificates.X509FindType]::FindByThumbprint,
      $Thumbprint,
      $false
    )
    foreach ($match in $matches) { $store.Remove($match) }
  } finally {
    $store.Close()
  }
}

try {
  $cert = New-SelfSignedCertificate -Subject $subject -Type CodeSigningCert -KeyUsage DigitalSignature -FriendlyName 'Zcode Spike Temporary' -CertStoreLocation 'Cert:\CurrentUser\My' -KeyAlgorithm RSA -KeyLength 2048 -NotAfter (Get-Date).AddDays(7)

  $signed = Set-AuthenticodeSignature -FilePath $workingPath -Certificate $cert -HashAlgorithm SHA256
  $verified = Get-AuthenticodeSignature -FilePath $workingPath
  Copy-Item -LiteralPath $workingPath -Destination $tamperedPath -Force
  $bytes = [IO.File]::ReadAllBytes($tamperedPath)
  $offset = [Math]::Min(4096, $bytes.Length - 1)
  $bytes[$offset] = $bytes[$offset] -bxor 0xFF
  [IO.File]::WriteAllBytes($tamperedPath, $bytes)
  $tampered = Get-AuthenticodeSignature -FilePath $tamperedPath
  $signaturePresent = (
    $verified.SignerCertificate -and
    $verified.SignerCertificate.Thumbprint -eq $cert.Thumbprint -and
    $verified.Status -ne 'NotSigned' -and
    $verified.Status -ne 'HashMismatch'
  )
  $sourceUnchanged = ((Get-FileHash $sourcePath -Algorithm SHA256).Hash -eq $sourceHashBefore)

  $result = [pscustomobject]@{
    sign_status = $signed.Status.ToString()
    verify_status = $verified.Status.ToString()
    signer = if ($verified.SignerCertificate) { $verified.SignerCertificate.Subject } else { $null }
    tampered_status = $tampered.Status.ToString()
    signature_present = [bool]$signaturePresent
    valid_passed = ($verified.Status -eq 'Valid')
    tamper_passed = ($tampered.Status -eq 'HashMismatch')
    source_unchanged = $sourceUnchanged
    passed = ($signaturePresent -and $tampered.Status -eq 'HashMismatch' -and $sourceUnchanged)
  }
} finally {
  if ($cert) {
    Remove-CertificateFromStore -Thumbprint $cert.Thumbprint -StoreName 'My'
    Remove-CertificateFromStore -Thumbprint $cert.Thumbprint -StoreName 'Root'
  }
  Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}

$result | ConvertTo-Json
if (-not $result.passed) { exit 1 }
