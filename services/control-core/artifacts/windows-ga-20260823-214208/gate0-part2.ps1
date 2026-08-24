$ErrorActionPreference = 'Stop'
$Repo = 'D:\agent\Agents\super-agent-self'
$Evidence = Join-Path $Repo 'services\control-core\artifacts\windows-ga-20260823-214208'
Set-Location $Repo

git merge --ff-only origin/main | Tee-Object -FilePath (Join-Path $Evidence 'ff-merge.txt')
if ($LASTEXITCODE -ne 0) { Write-Output 'BLOCKED: ff-only merge failed'; exit 1 }

git status --short --branch | Tee-Object -FilePath (Join-Path $Evidence 'git-status-after-ff.txt')
$head = (git rev-parse HEAD).Trim()
$head | Set-Content -LiteralPath (Join-Path $Evidence 'candidate-source-head.txt') -Encoding ASCII
Write-Output "HEAD=$head"

# 合并后新增的两个提交内容概览（证据）
git log --oneline --decorate --max-count=5 | Tee-Object -FilePath (Join-Path $Evidence 'git-log-after-ff.txt')
Write-Output 'GATE0_PART2_OK'
