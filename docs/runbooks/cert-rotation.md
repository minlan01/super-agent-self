# Code-Signing Certificate Rotation Runbook

> Updated: 2026-08-16
> Scope: Windows Authenticode signing for desktop, sidecar and NSIS installer
> Current status: test signing is verified; production certificate and trusted timestamp are `BLOCKED`

## 1. Rotation Trigger

Begin rotation at least 30 days before certificate expiry, or immediately after suspected key compromise, signer-policy change or timestamp-service failure.

Never store a PFX password, private key, token or certificate secret in the repository, CI logs, command history or release Markdown.

## 2. Inventory the Current Certificate

Use the Windows certificate store or a managed signing service. Prefer a non-exportable private key.

```powershell
$thumbprint = $env:ZCODE_SIGNING_CERT_THUMBPRINT
$cert = Get-Item "Cert:\CurrentUser\My\$thumbprint"

$cert | Select-Object Subject, Thumbprint, NotBefore, NotAfter, HasPrivateKey,
  @{n='EnhancedKeyUsage';e={$_.EnhancedKeyUsageList.FriendlyName -join ', '}}
```

Required properties:

- Code Signing enhanced key usage.
- Private key available to the isolated signer identity.
- Expiry beyond the planned support window.
- Approved issuer and chain policy.

## 3. Sign in the Correct Order

All executable payloads must be signed before they are compressed into the installer, and the final installer must be signed afterward.

1. Build the complete Nuitka sidecar directory.
2. Sign the sidecar PE files that will be distributed.
3. Build and sign the Tauri desktop executable through a protected `signCommand` or equivalent pipeline step.
4. Build the NSIS package.
5. Sign and timestamp the final installer.

Example signer invocation using a certificate-store thumbprint:

```powershell
$signtool = (Get-Command signtool.exe -ErrorAction Stop).Source
$timestampUrl = $env:ZCODE_TIMESTAMP_URL
$thumbprint = $env:ZCODE_SIGNING_CERT_THUMBPRINT

& $signtool sign /sha1 $thumbprint /fd SHA256 /tr $timestampUrl /td SHA256 `
  '.\src-tauri\target\release\tauri-spike.exe'

& $signtool sign /sha1 $thumbprint /fd SHA256 /tr $timestampUrl /td SHA256 `
  '.\src-tauri\target\release\bundle\nsis\Zcode Desktop Agent_<version>_x64-setup.exe'
```

The production pipeline must also sign `resources\sidecar\sidecar.exe` and any distributed PE library required by organizational policy before running the Tauri bundle step.

## 4. Verify Signatures and Timestamp

```powershell
$artifacts = @(
  '.\src-tauri\target\release\tauri-spike.exe',
  '.\src-tauri\resources\sidecar\sidecar.exe',
  '.\src-tauri\target\release\bundle\nsis\Zcode Desktop Agent_<version>_x64-setup.exe'
)

$results = foreach ($artifact in $artifacts) {
  $sig = Get-AuthenticodeSignature -LiteralPath $artifact
  [pscustomobject]@{
    Path = $artifact
    Status = $sig.Status
    Signer = $sig.SignerCertificate.Subject
    Thumbprint = $sig.SignerCertificate.Thumbprint
    CertificateExpiry = $sig.SignerCertificate.NotAfter
    TimestampSigner = $sig.TimeStamperCertificate.Subject
  }
}

$results | Format-Table -AutoSize
if ($results.Status -contains 'NotSigned' -or $results.Status -contains 'HashMismatch') {
  throw 'release signature verification failed'
}
```

Run the repository tamper test against a temporary copy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File '.\tests\test_authenticode.ps1' `
  -Exe '.\src-tauri\target\release\bundle\nsis\Zcode Desktop Agent_<version>_x64-setup.exe'
```

This test proves local Authenticode and tamper detection mechanics. It does not replace verification of the production issuer or trusted timestamp.

## 5. Rotation Rollout

- Publish the new signer thumbprint in the release gate and endpoint allowlist before the first new-signed release.
- Keep the old public certificate trusted during an overlap window that covers N-1 rollback.
- Sign new releases only with the new key after cutover.
- Revoke the old certificate after the overlap window, or immediately if compromised.
- Retain timestamp evidence so already-issued binaries remain verifiable after certificate expiry.

## 6. Compromise Procedure

1. Stop signing immediately and disable the signing identity.
2. Request issuer revocation.
3. Freeze rollout and preserve signing logs.
4. Generate a new key under a separate signer identity.
5. Rebuild from the approved revision; do not re-sign an unverified old binary.
6. Publish new package digests and signer metadata through the release gate.

## 7. Exit Criteria

- Desktop, sidecar and installer all report `Status = Valid`.
- Signer thumbprint matches the approved certificate.
- Trusted timestamp is present.
- Tampered-copy verification returns `HashMismatch`.
- N-1 remains verifiable during the overlap window.
- No private-key material or passwords appear in repository files or logs.
