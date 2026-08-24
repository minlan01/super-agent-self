$ErrorActionPreference = 'Stop'
$Repo = 'D:\agent\Agents\super-agent-self'
$Evidence = Join-Path $Repo 'services\control-core\artifacts\windows-ga-20260823-214208'
Set-Location (Join-Path $Repo 'apps\desktop')

npm.cmd version 1.0.0 --no-git-tag-version
if ($LASTEXITCODE -ne 0) { Write-Output 'BLOCKED: npm version failed'; exit 1 }

$versions = node -e "const p=require('./package.json');const l=require('./package-lock.json');console.log(JSON.stringify({package:p.version,lock:l.version,root:l.packages[''].version}))" | ConvertFrom-Json
$versions | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Evidence 'version-check.json') -Encoding UTF8
if ($versions.package -ne '1.0.0' -or $versions.lock -ne '1.0.0' -or $versions.root -ne '1.0.0') {
  Write-Output "BLOCKED: version mismatch: $($versions | ConvertTo-Json -Compress)"
  exit 2
}

Set-Location $Repo
$rgOutput = & rg -n '^version = "1.0.0"|"version": "1.0.0"' `
  .\apps\desktop\package.json `
  .\apps\desktop\package-lock.json `
  .\apps\desktop\src-tauri\Cargo.toml `
  .\apps\desktop\src-tauri\tauri.conf.json
$rgOutput | Set-Content -LiteralPath (Join-Path $Evidence 'version-rg.txt') -Encoding UTF8
$rgOutput
$rgExit = $LASTEXITCODE
if ($rgExit -ne 0) { Write-Output 'BLOCKED: rg version check failed'; exit 3 }
Write-Output 'GATE1_1_OK'
