$ErrorActionPreference = 'Continue'
$Repo = 'D:\agent\Agents\super-agent-self'
$Evidence = Join-Path $Repo 'services\control-core\artifacts\windows-ga-20260823-214208'
$Py = Join-Path $Repo 'services\control-core\.venv-win\Scripts\python.exe'
Set-Location $Repo
$env:TESTING = '1'
$env:LLM_PROVIDER = 'mock'

# 1. IPC contract + sidecar pipe
& $Py -m pytest `
  .\services\control-core\tests\unit\test_ipc_contract.py `
  .\services\control-core\tests\integration\test_sidecar_pipe_windows.py `
  -q --junitxml (Join-Path $Evidence 'ipc.xml') *>&1 |
  Tee-Object -FilePath (Join-Path $Evidence 'ipc.txt')
$ipcExit = $LASTEXITCODE
Write-Output "IPC_EXIT=$ipcExit"

# 2. Windows platform tests
& $Py -m pytest `
  .\services\control-core\packages\platform\windows\tests `
  -q --junitxml (Join-Path $Evidence 'windows-platform.xml') *>&1 |
  Tee-Object -FilePath (Join-Path $Evidence 'windows-platform.txt')
$platformExit = $LASTEXITCODE
Write-Output "PLATFORM_EXIT=$platformExit"

# 3. control-core full suite
Set-Location (Join-Path $Repo 'services\control-core')
& $Py -m pytest .\tests -q --junitxml (Join-Path $Evidence 'control-core.xml') *>&1 |
  Tee-Object -FilePath (Join-Path $Evidence 'control-core.txt')
$fullExit = $LASTEXITCODE
Write-Output "FULL_EXIT=$fullExit"

# 4. cargo check
Set-Location (Join-Path $Repo 'apps\desktop\src-tauri')
cargo check 2>&1 | Tee-Object -FilePath (Join-Path $Evidence 'cargo-check.txt')
$cargoExit = $LASTEXITCODE
Write-Output "CARGO_EXIT=$cargoExit"

Remove-Item Env:TESTING -ErrorAction SilentlyContinue
Remove-Item Env:LLM_PROVIDER -ErrorAction SilentlyContinue
Write-Output "GATE3_DONE ipc=$ipcExit platform=$platformExit full=$fullExit cargo=$cargoExit"
