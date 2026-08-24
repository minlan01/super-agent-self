$ErrorActionPreference = 'Stop'
$Repo = 'D:\agent\Agents\super-agent-self'
$RunId = '20260823-214208'
$Evidence = Join-Path $Repo "services\control-core\artifacts\windows-ga-$RunId"
Set-Location $Repo

# 手册 §1：run.json
[pscustomobject]@{
  started_at   = (Get-Date).ToString('o')
  repo         = $Repo
  run_id       = $RunId
  release_scope = 'Personal/Internal GA'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Evidence 'run.json') -Encoding UTF8

# 手册 §2.1：只读检查
git config core.filemode false
git status --short --branch | Tee-Object -FilePath (Join-Path $Evidence 'git-status-before.txt')

$trackedChanges = @(git status --porcelain=v1 --untracked-files=no)
if ($trackedChanges.Count -gt 0) {
  $trackedChanges | Set-Content -LiteralPath (Join-Path $Evidence 'BLOCKED-tracked-changes.txt') -Encoding UTF8
  Write-Output 'BLOCKED: tracked local modifications exist'
  exit 1
}

git fetch origin --prune
$fetchExit = $LASTEXITCODE
"fetch exit code: $fetchExit  time: $((Get-Date).ToString('o'))" |
  Set-Content -LiteralPath (Join-Path $Evidence 'git-fetch.txt') -Encoding UTF8
if ($fetchExit -ne 0) { Write-Output 'BLOCKED: git fetch failed'; exit 2 }

$local  = (git rev-parse HEAD).Trim()
$remote = (git rev-parse origin/main).Trim()
$counts = (git rev-list --left-right --count HEAD...origin/main).Trim()
[pscustomobject]@{ local = $local; remote = $remote; left_right = $counts } |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Evidence 'git-baseline.json') -Encoding UTF8

git log --oneline --decorate --graph --max-count=20 --all |
  Tee-Object -FilePath (Join-Path $Evidence 'git-graph.txt')

Write-Output "LOCAL=$local"
Write-Output "REMOTE=$remote"
Write-Output "COUNTS=$counts"
Write-Output 'GATE0_PART1_OK'
