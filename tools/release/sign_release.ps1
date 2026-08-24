# sign_release.ps1 -- unified signing entry (v1.0.0 GA: thumbprint reuse mode)
#
# Usage (the only supported path for this GA -- ADR-0023 self-sign posture):
#   .\sign_release.ps1 -CertificateThumbprint <SHA1> `
#       -Artifacts @("path\to\sidecar.exe", "path\to\tauri-spike.exe", "path\to\setup.exe")
#
# The certificate must already exist in Cert:\CurrentUser\My (created and
# registered by the user in Gate 5). This script NEVER creates certificates
# and NEVER accepts a plaintext password.
#
# Future production mode (PFX -- UNVERIFIED in this GA, do not claim usable):
#   .\sign_release.ps1 -PfxPath D:\certs\zcode-ov.pfx -PfxPassword $secure -Artifacts @(...)
#
# NOTE: this file is ASCII-only on purpose. PowerShell 5.1 reads BOM-less
# UTF-8 .ps1 files as ANSI/GBK, which corrupts non-ASCII comments and can
# break parsing. Native signtool output is merged at the process level via
# cmd /c so informational stderr cannot terminate this script.

param(
  [Parameter(Mandatory = $true, Position = 0)]
  [string[]]$Artifacts,

  [Parameter(ParameterSetName = 'Thumbprint', Mandatory = $true)]
  [ValidatePattern('^[0-9A-Fa-f]{40}$')]
  [string]$CertificateThumbprint,

  [Parameter(ParameterSetName = 'Pfx', Mandatory = $true)]
  [string]$PfxPath,

  [Parameter(ParameterSetName = 'Pfx')]
  [SecureString]$PfxPassword,

  [string]$TimestampUrl = 'http://timestamp.digicert.com'
)

$ErrorActionPreference = 'Stop'
$store = 'Cert:\CurrentUser\My'
$signTool = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe'
if (-not (Test-Path -LiteralPath $signTool)) {
  $signTool = (Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' -Filter signtool.exe -File -Recurse |
    Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
    Sort-Object FullName -Descending | Select-Object -First 1).FullName
}
if (-not $signTool) { throw 'signtool.exe not found' }

$importedThumbprint = $null

if ($PSCmdlet.ParameterSetName -eq 'Thumbprint') {
  Write-Host "[sign] thumbprint mode (ADR-0023) -- reusing existing cert, never creating one"
  $cert = Get-Item -LiteralPath (Join-Path $store $CertificateThumbprint) -ErrorAction SilentlyContinue
  if (-not $cert) {
    throw "REFUSED: certificate $CertificateThumbprint not found in $store. Gate 5 must create and register it first; this script never creates certificates."
  }
}
else {
  Write-Warning "[sign] PFX mode is UNVERIFIED for this GA -- do not claim it works without an independent test."
  if (-not (Test-Path -LiteralPath $PfxPath)) { throw "PFX not found: $PfxPath" }
  if (-not $PfxPassword) { throw 'REFUSED: -PfxPassword must be a SecureString (never plaintext).' }
  $imported = Import-PfxCertificate -FilePath $PfxPath -CertStoreLocation $store -Password $PfxPassword
  $importedThumbprint = $imported.Thumbprint
  $CertificateThumbprint = $imported.Thumbprint
  $cert = Get-Item -LiteralPath (Join-Path $store $CertificateThumbprint)
}

try {
  if ($cert.NotAfter -lt (Get-Date)) { throw "certificate expired at $($cert.NotAfter)" }
  if ($cert.NotBefore -gt (Get-Date)) { throw "certificate not valid before $($cert.NotBefore)" }

  Write-Host ("[sign] Subject    : {0}" -f $cert.Subject)
  Write-Host ("[sign] Thumbprint : {0}" -f $cert.Thumbprint)
  Write-Host ("[sign] Validity   : {0} -> {1}" -f $cert.NotBefore, $cert.NotAfter)

  foreach ($artifact in $Artifacts) {
    if (-not (Test-Path -LiteralPath $artifact)) { throw "artifact not found: $artifact" }
  }

  $results = @()
  foreach ($artifact in $Artifacts) {
    $leaf = Split-Path $artifact -Leaf
    Write-Host ""
    Write-Host "[sign] signing $leaf"
    # Merge stderr at the process level (cmd /c) so PS never sees ErrorRecords.
    $quoted = '"' + $signTool + '" sign /fd SHA256 /td SHA256 /tr ' + $TimestampUrl +
              ' /v /sha1 ' + $CertificateThumbprint + ' "' + $artifact + '" 2>&1'
    $output = cmd /c $quoted
    $output | Write-Host
    if ($LASTEXITCODE -ne 0) { throw "signtool failed for $artifact (exit $LASTEXITCODE)" }
    $text = $output -join "`n"
    $timestamped = ($text -match 'successfully|RFC3161')

    # Fail-closed identity check: signer must be exactly the registered
    # thumbprint -- mixing certificates in one release aborts.
    $sig = Get-AuthenticodeSignature -LiteralPath $artifact
    if (-not $sig.SignerCertificate) { throw "no signature present after signing: $artifact" }
    if ($sig.SignerCertificate.Thumbprint -ne $CertificateThumbprint) {
      throw ("REFUSED: signer identity mismatch for {0}: expected {1}, got {2}" -f $artifact, $CertificateThumbprint, $sig.SignerCertificate.Thumbprint)
    }

    $hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash
    $results += [pscustomobject]@{
      artifact    = $artifact
      sha256      = $hash
      signer      = $sig.SignerCertificate.Subject
      thumbprint  = $sig.SignerCertificate.Thumbprint
      timestamped = [bool]$timestamped
    }
  }

  Write-Host ""
  Write-Host ("[sign] summary Subject={0} thumbprint={1} NotBefore={2} NotAfter={3}" -f $cert.Subject, $CertificateThumbprint, $cert.NotBefore, $cert.NotAfter)
  $results | ConvertTo-Json | Write-Host
  $notTimestamped = @($results | Where-Object { -not $_.timestamped })
  if ($notTimestamped.Count -gt 0) {
    Write-Warning ("[sign] timestamp result not confirmed for: {0} -- review the signtool output above" -f (($notTimestamped | ForEach-Object { $_.artifact }) -join ', '))
  }
  Write-Host 'NEXT: register the SHA-256 values above in docs/releases/RELEASES.md'
  exit 0
}
finally {
  if ($importedThumbprint) {
    Remove-Item -LiteralPath (Join-Path $store $importedThumbprint) -ErrorAction SilentlyContinue
  }
}
