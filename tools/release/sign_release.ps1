# sign_release.ps1 — 统一签名入口(自签/生产证书同一脚本)
#
# 用法 A(自签,ADR-0023 v1.0 姿态):
#   .\sign_release.ps1 -SelfSigned `
#       -Subject "CN=Zcode Personal Release" `
#       -Artifacts @("path\to\installer.exe", "path\to\tauri-spike.exe", "path\to\sidecar.exe")
#
# 用法 B(将来对外,生产证书):
#   .\sign_release.ps1 -PfxPath D:\certs\zcode-ov.pfx -Password $pwd `
#       -Artifacts @(...) -TimestampUrl http://timestamp.digicert.com
#
# 升级路径(ADR-0023):换参数即可,流程零改动。

param(
  [Parameter(Mandatory=$true)][string[]]$Artifacts,
  [switch]$SelfSigned,
  [string]$Subject = "CN=Zcode Personal Release",
  [string]$PfxPath,
  [string]$Password,
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = 'Stop'

function Get-Cert([byte[]]$der) {
  $r = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(,$der)
  return $r
}

$cert = $null

if ($SelfSigned) {
  Write-Host "[sign] self-signed mode (ADR-0023) — personal-use posture"
  $cert = New-SelfSignedCertificate -Subject $Subject -Type CodeSigningCert `
            -KeyUsage DigitalSignature -FriendlyName "Zcode self-sign" `
            -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddYears(3)
} elseif ($PfxPath) {
  Write-Host "[sign] production PFX mode"
  $secure = ConvertTo-SecureString $Password -AsPlainText -Force
  $cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new(
            $PfxPath, $secure, [System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
} else {
  throw "provide -SelfSigned or -PfxPath"
}

Write-Host ("[sign] cert: {0}`n        thumbprint: {1}" -f $cert.Subject, $cert.Thumbprint)

foreach ($artifact in $Artifacts) {
  if (-not (Test-Path $artifact)) { throw "artifact not found: $artifact" }
}

foreach ($artifact in $Artifacts) {
  $args = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $TimestampUrl,
            "/sha1", $cert.Thumbprint, $artifact)
  & signtool @args
  if ($LASTEXITCODE -ne 0) { throw "signtool failed for $artifact" }

  & signtool verify /pa $artifact
  if ($LASTEXITCODE -ne 0) {
    # 自签证书未加入机器信任时 verify /pa 预期失败 — 属正常,给出说明
    Write-Warning "chain verify failed (expected for untrusted self-signed): $artifact"
    Write-Warning "installers: verify the SHA-256 against docs/releases/RELEASES.md instead"
  }

  $hash = (Get-FileHash $artifact -Algorithm SHA256).Hash
  Write-Host ("[sign] {0}`n        SHA-256 {1}" -f (Split-Path $artifact -Leaf), $hash)
}

Write-Host ""
Write-Host "NEXT: paste the SHA-256 lines above into docs/releases/RELEASES.md"
if ($SelfSigned) {
  Write-Host ("      self-sign cert SHA-1 thumbprint (register in RELEASES.md): {0}" -f $cert.Thumbprint)
}
