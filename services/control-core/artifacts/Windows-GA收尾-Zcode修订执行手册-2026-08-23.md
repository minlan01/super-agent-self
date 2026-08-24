# Windows GA 收尾：Zcode 修订执行手册

> 版本：2026-08-23 Final Review Edition  
> 项目：`D:\agent\Agents\super-agent-self`  
> 发布目标：`Zcode Desktop Agent v1.0.0 Personal/Internal GA`，仅用户本人使用  
> 原手册：`D:\Windows-GA收尾执行手册.md`，仅作历史参考，不得混用命令  
> 默认 Shell：Windows PowerShell 5.1，除非步骤明确写明其他环境

## 0. 执行原则

### 0.1 状态定义

- `PASS`：命令退出码、机器可读证据和人工观察全部满足标准。
- `PENDING`：尚未执行、等待用户敏感交互或等待 CI/VM。
- `BLOCKED`：实际失败或缺少必需实现/依赖。
- `DEFERRED P5`：本次明确不实现的自动 Updater 和自动降级。

禁止把 `PENDING`、`BLOCKED` 或 `DEFERRED P5` 写成 `PASS`。

### 0.2 禁止事项

1. 禁止 `git pull`、`git reset --hard`、`git clean`、force push。
2. 禁止 `git add -A`；提交时只暂存经用户审查的明确文件。
3. 禁止读取、输出、保存或上传私钥、PFX 密码、账户密码、token。
4. 禁止把自签证书导入宿主机 Root/TrustedPublisher。
5. 禁止创建 External VMSwitch，禁止修改宿主机启动项、现有账户和安全配置。
6. 禁止删除 ISO、VM、VHDX、临时 worktree，直到列出绝对路径并再次获得用户确认。
7. 禁止在未观察真实 UI/锁屏/安装结果时伪造人工证据。

### 0.3 已授权事项

- 可创建明确命名的临时 VM、checkpoint、临时账户并执行断网、重启、安装和卸载。
- 可从 Microsoft 官方来源下载 Windows 11 与 Windows 10 22H2 ISO。
- 可在临时 VM 的 `CurrentUser` 信任存储中导入自签公钥证书。
- 用户本人负责密码、私钥、SmartScreen/UAC 和真实 `Win+L` 锁定/解锁。
- commit、tag、push 必须在相应步骤停下再次确认；禁止 force push。

## 1. 证据目录

在项目根目录运行：

```powershell
Set-Location 'D:\agent\Agents\super-agent-self'
$Repo = (Get-Location).Path
$RunId = Get-Date -Format 'yyyyMMdd-HHmmss'
$Evidence = Join-Path $Repo "services\control-core\artifacts\windows-ga-$RunId"
New-Item -ItemType Directory -Path $Evidence -Force | Out-Null

[pscustomobject]@{
  started_at = (Get-Date).ToString('o')
  repo = $Repo
  run_id = $RunId
  release_scope = 'Personal/Internal GA'
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Evidence 'run.json') -Encoding utf8
```

每个阶段把控制台输出、JSON、JUnit、截图说明和 SHA-256 放入该目录。截图文件不得包含密码、私钥、token 或完整用户隐私数据。

## 2. Gate 0：Git 基线

### 2.1 只读检查

```powershell
Set-Location $Repo
git config core.filemode false
git status --short --branch | Tee-Object (Join-Path $Evidence 'git-status-before.txt')

$trackedChanges = @(git status --porcelain=v1 --untracked-files=no)
if ($trackedChanges.Count -gt 0) {
  throw '存在已跟踪的本地修改；停止，不得覆盖。'
}

git fetch origin --prune
if ($LASTEXITCODE -ne 0) {
  throw 'GitHub fetch 失败；Gate 0 BLOCKED。不得使用缓存 origin/main 继续发布。'
}

$local = (git rev-parse HEAD).Trim()
$remote = (git rev-parse origin/main).Trim()
$counts = (git rev-list --left-right --count HEAD...origin/main).Trim()
[pscustomobject]@{ local=$local; remote=$remote; left_right=$counts } |
  ConvertTo-Json | Set-Content (Join-Path $Evidence 'git-baseline.json') -Encoding utf8

git log --oneline --decorate --graph --max-count=20 --all |
  Tee-Object (Join-Path $Evidence 'git-graph.txt')
```

已知审查基线为本地 `c9a4796`、缓存远端 `389e43c`、关系 `0 2`。若成功 fetch 后远端不再是 `389e43c`，先执行：

```powershell
git log --oneline 389e43c..origin/main
git diff --stat 389e43c..origin/main
git diff --name-status 389e43c..origin/main
```

若新增提交触及桌面、Sidecar、IPC、数据库迁移、签名、CI、许可证或发布文档，停止并提交差异报告，不得盲目合并。

### 2.2 只允许快进

```powershell
git merge --ff-only origin/main
if ($LASTEXITCODE -ne 0) { throw 'ff-only 合并失败；Gate 0 BLOCKED。' }

git status --short --branch | Tee-Object (Join-Path $Evidence 'git-status-after-ff.txt')
git rev-parse HEAD | Set-Content (Join-Path $Evidence 'candidate-source-head.txt')
```

## 3. Gate 1：先补实现，禁止直接打包

本阶段属于源码修复。任何一项未完成，禁止进入签名和 VM 阶段。

### 3.1 统一版本

```powershell
Set-Location (Join-Path $Repo 'apps\desktop')
npm.cmd version 1.0.0 --no-git-tag-version

$versions = node -e "const p=require('./package.json');const l=require('./package-lock.json');console.log(JSON.stringify({package:p.version,lock:l.version,root:l.packages[''].version}))" |
  ConvertFrom-Json
if ($versions.package -ne '1.0.0' -or $versions.lock -ne '1.0.0' -or $versions.root -ne '1.0.0') {
  throw 'package/package-lock 版本未统一。'
}

Set-Location $Repo
rg -n '^version = "1.0.0"|"version": "1.0.0"' `
  .\apps\desktop\package.json `
  .\apps\desktop\package-lock.json `
  .\apps\desktop\src-tauri\Cargo.toml `
  .\apps\desktop\src-tauri\tauri.conf.json
```

### 3.2 补齐桌面验收能力

必须实现并测试以下能力：

1. 任务详情视图调用 `GET /api/v1/tasks/{id}`，显示每个 step 的顺序、tool、脱敏 args、risk、status、result/error。
2. 审批 API 返回从对应 `TaskStep.args` 生成的脱敏参数快照；不得返回密码、token、SecretRef 实值或任意密钥。
3. 审批 UI 显示 tool、脱敏参数、risk、requester、quorum；自批准失败必须显示 403。
4. Effect 视图显示 status、before_hash、after_hash、dispatch history。
5. Unknown-outcome 队列调用 `/api/v1/effects/unknown-outcomes`，提供 confirmed/failed reconcile 操作。
6. 已 reconcile 的 Effect 再次操作必须展示 HTTP 409，终态不可修改。
7. 添加只用于一次性测试数据目录的 unknown-outcome fixture 工具；它必须拒绝操作真实 `%LOCALAPPDATA%\zcode` 目录。

实现位置应遵循现有结构，至少涉及：

```text
apps/desktop/src/main.ts
apps/desktop/index.html
apps/desktop/src/styles.css
services/control-core/apps/api_server/routes/gateway_approvals.py
services/control-core/apps/api_server/routes/effects.py
services/control-core/tests/
```

验收测试必须覆盖：参数脱敏、租户隔离、自批准 403、重复投票/重复 reconcile 409、Effect 终态不可逆。

### 3.3 修复测试与运维脚本

1. `measure_startup.ps1` 增加独立参数：
   - `ReadyTimeoutSeconds=60`：诊断等待上限。
   - `StartupSloSeconds=5`：性能 Gate。
   - 5 到 60 秒返回 `FAIL_PERFORMANCE`，不能返回 PASS。
2. `test_installed_release_1_0_0.ps1` 删除写死的 `2026-08-22`，输出当前时间、系统版本、commit、安装器 SHA-256 和唯一证据文件名。
3. 新增安装版审计链包装脚本，强制传入 `%LOCALAPPDATA%\zcode\agent_platform.db` 的绝对路径。
4. 新增第二账户存储 ACL 测试，验证 peer 账户不能读取 owner 的 DB、日志和 workspace；pipe error 5 与存储 ACL 必须分别取证。
5. 新增 SQLite 备份/校验/恢复 CLI，内部使用 `sqlite3.Connection.backup()`，恢复前验证 `PRAGMA integrity_check`，并拒绝越出指定 backup 目录。

### 3.4 修复许可证 Gate

必须修改远端新增的许可证工具：

1. CI 安装 `pip-licenses==5.5.5`，不能安装不存在的 `pip-license`。
2. Python 调用模块 `piplicenses` 或其 CLI，不得调用不存在的 `pip_license`。
3. Node 许可证必须读取实际 package manifest、SBOM 或可靠扫描器；`license` 缺失必须失败。
4. 工具不存在、JSON 无法解析、许可证为空、未知 SPDX、AGPL/SSPL 均 fail-closed。
5. 为以上失败模式添加单元测试。

### 3.5 修复签名脚本

`tools/release/sign_release.ps1` 至少增加：

- `-CertificateThumbprint`：只复用 `Cert:\CurrentUser\My` 中已存在证书。
- 拒绝同一发布中混用多个 thumbprint。
- 不接受明文密码参数完成本次自签流程。
- 输出 Subject、thumbprint、NotBefore/NotAfter、时间戳结果和每个产物 SHA-256。
- 签名失败立即退出非零。
- PFX 生产模式若保留，必须使用 `SecureString` 并有独立 Windows 测试；未经验证不得宣称可用。

### 3.6 修复 CI 独立构建

Windows release job 必须在 `npm ci` 前执行：

```powershell
& .\services\control-core\scripts\nuitka-build\build.ps1 -Jobs 4
```

并验证以下文件存在：

```text
apps/desktop/src-tauri/resources/sidecar/sidecar.exe
apps/desktop/src-tauri/resources/sidecar/bootstrap/agent_platform.db
apps/desktop/src-tauri/resources/sidecar/bootstrap/manifest.json
```

CI 必须：

1. 固定 Python、Node/npm、Rust 和 Nuitka 版本，避免 `stable` 漂移。
2. 支持 `release/windows-v1.0.0-rc` 分支或 `workflow_dispatch`。
3. 从干净 checkout 构建 unsigned Sidecar、桌面 EXE 和 NSIS。
4. 上传三项 SHA-256、文件大小、工具版本、commit、Nuitka report 和构建日志。
5. 缺少任一产物时失败，不能静默跳过。

## 4. Gate 2：工具前置条件

### 4.1 Windows SDK / SignTool

当前宿主机没有可用 `signtool.exe`。执行：

```powershell
winget install --id Microsoft.WindowsSDK.10.0.26100 --exact --source winget `
  --accept-source-agreements --accept-package-agreements

$SignTool = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' `
  -Filter signtool.exe -File -Recurse |
  Where-Object FullName -Match '\\x64\\signtool.exe$' |
  Sort-Object FullName -Descending | Select-Object -First 1
if (-not $SignTool) { throw 'signtool.exe 仍不可用。' }
$env:Path = "$($SignTool.DirectoryName);$env:Path"
signtool.exe /?
```

### 4.2 许可证和构建工具

```powershell
$Py = Join-Path $Repo 'services\control-core\.venv-win\Scripts\python.exe'
& $Py -m pip install --disable-pip-version-check 'pip-licenses==5.5.5'

if (-not (Get-Command cargo-deny -ErrorAction SilentlyContinue)) {
  cargo install --locked cargo-deny
}

Set-Location (Join-Path $Repo 'apps\desktop')
npm.cmd ci
Set-Location $Repo

@(
  "node=$(node --version)",
  "npm=$(npm.cmd --version)",
  "cargo=$(cargo --version)",
  "rustc=$(rustc --version)",
  "python=$(& $Py --version)",
  "cargo-deny=$(cargo deny --version)"
) | Set-Content (Join-Path $Evidence 'tool-versions.txt')
```

如果本地与 CI 工具版本不一致，先统一版本；否则不得要求 bit-for-bit 摘要一致。

## 5. Gate 3：自动回归

```powershell
Set-Location $Repo
$env:TESTING = '1'
$env:LLM_PROVIDER = 'mock'

& $Py -m pytest `
  .\services\control-core\tests\unit\test_ipc_contract.py `
  .\services\control-core\tests\integration\test_sidecar_pipe_windows.py `
  -q --junitxml (Join-Path $Evidence 'ipc.xml') |
  Tee-Object (Join-Path $Evidence 'ipc.txt')
if ($LASTEXITCODE -ne 0) { throw 'IPC Gate 失败。' }

& $Py -m pytest `
  .\services\control-core\packages\platform\windows\tests `
  -q --junitxml (Join-Path $Evidence 'windows-platform.xml') |
  Tee-Object (Join-Path $Evidence 'windows-platform.txt')
if ($LASTEXITCODE -ne 0) { throw 'Windows platform Gate 失败。' }

& $Py -m pytest `
  .\services\control-core\tests `
  -q --junitxml (Join-Path $Evidence 'control-core.xml') |
  Tee-Object (Join-Path $Evidence 'control-core.txt')
if ($LASTEXITCODE -ne 0) { throw 'Control-core 全量测试失败。' }

Set-Location (Join-Path $Repo 'apps\desktop')
npm.cmd run build 2>&1 | Tee-Object (Join-Path $Evidence 'desktop-build.txt')
if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }

Set-Location .\src-tauri
cargo check 2>&1 | Tee-Object (Join-Path $Evidence 'cargo-check.txt')
if ($LASTEXITCODE -ne 0) { throw 'cargo check 失败。' }
Set-Location $Repo

Remove-Item Env:TESTING -ErrorAction SilentlyContinue
Remove-Item Env:LLM_PROVIDER -ErrorAction SilentlyContinue
```

跳过项必须逐条解释。依赖真实人工、硬件或外部服务的测试可保持 PENDING，但不能被“总体 passed”掩盖。

## 6. Gate 4：unsigned 本地候选构建

### 6.1 构建 Sidecar

```powershell
Set-Location (Join-Path $Repo 'services\control-core\scripts\nuitka-build')
& .\build.ps1 -Jobs 4 2>&1 | Tee-Object (Join-Path $Evidence 'nuitka-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Nuitka build 失败。' }

$Sidecar = Join-Path $Repo 'apps\desktop\src-tauri\resources\sidecar\sidecar.exe'
if (-not (Test-Path -LiteralPath $Sidecar)) { throw 'Sidecar 产物不存在。' }
```

`build.ps1` 已负责复制完整 Sidecar 目录，禁止再使用原手册中的重复 `Copy-Item` 覆盖步骤。

### 6.2 构建 unsigned 桌面与 NSIS

```powershell
Set-Location (Join-Path $Repo 'apps\desktop')
npm.cmd ci
npm.cmd run tauri -- build --no-bundle --no-sign 2>&1 |
  Tee-Object (Join-Path $Evidence 'tauri-build-unsigned.txt')
if ($LASTEXITCODE -ne 0) { throw 'unsigned desktop build 失败。' }

npm.cmd run tauri -- bundle --bundles nsis --no-sign 2>&1 |
  Tee-Object (Join-Path $Evidence 'tauri-bundle-unsigned.txt')
if ($LASTEXITCODE -ne 0) { throw 'unsigned NSIS bundle 失败。' }

$Desktop = Join-Path $Repo 'apps\desktop\src-tauri\target\release\tauri-spike.exe'
$UnsignedInstaller = Get-ChildItem `
  (Join-Path $Repo 'apps\desktop\src-tauri\target\release\bundle\nsis') `
  -Filter '*1.0.0*x64-setup.exe' -File | Select-Object -First 1
if (-not $UnsignedInstaller) { throw '1.0.0 unsigned installer 不存在。' }

$unsigned = @($Sidecar, $Desktop, $UnsignedInstaller.FullName) | ForEach-Object {
  $item = Get-Item -LiteralPath $_
  [pscustomobject]@{
    path = $item.FullName
    size = $item.Length
    sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
    authenticode = (Get-AuthenticodeSignature -LiteralPath $item.FullName).Status.ToString()
  }
}
$unsigned | ConvertTo-Json | Set-Content (Join-Path $Evidence 'unsigned-digests.json') -Encoding utf8
```

不要用安装器体积单独证明 WebView2 已离线嵌入。体积只记录，最终以断网 VM 实测为准。

## 7. Gate 5：创建并保管自签发布身份

本阶段必须停下，由用户本人在安全提示中输入 PFX 密码，并完成两个离线备份。Zcode 不读取密码和 PFX 内容。

### 7.1 用户本人执行

```powershell
$Cert = New-SelfSignedCertificate `
  -Subject 'CN=Zcode Personal Release' `
  -Type CodeSigningCert `
  -KeyAlgorithm RSA -KeyLength 3072 `
  -HashAlgorithm SHA256 `
  -KeyExportPolicy Exportable `
  -CertStoreLocation 'Cert:\CurrentUser\My' `
  -NotAfter (Get-Date).AddYears(3)

$PublicDir = Join-Path $env:USERPROFILE 'Documents\ZcodeReleasePublic'
New-Item -ItemType Directory -Path $PublicDir -Force | Out-Null
$CerPath = Join-Path $PublicDir 'zcode-personal-release.cer'
Export-Certificate -Cert $Cert -FilePath $CerPath | Out-Null

# PFX 路径由用户选择在仓库之外；密码只在 SecureString 提示中输入。
$PfxPath = Read-Host '输入仓库之外的 PFX 绝对路径'
$PfxPassword = Read-Host '输入 PFX 密码' -AsSecureString
Export-PfxCertificate -Cert $Cert -FilePath $PfxPath -Password $PfxPassword | Out-Null
Remove-Variable PfxPassword

$Cert | Select-Object Subject,Thumbprint,NotBefore,NotAfter
Get-FileHash -LiteralPath $CerPath -Algorithm SHA256
```

用户完成两个离线备份后，只把以下非秘密值交给 Zcode：

- certificate Subject
- SHA-1 thumbprint
- 公钥 `.cer` 的 SHA-256
- 两份离线备份已完成的人工确认

### 7.2 禁止操作

- 不得把 PFX 放入项目、Desktop、artifact 或云盘同步目录。
- 不得把 PFX 密码写入命令参数、环境变量、Markdown 或 GitHub Secret。
- 不得把证书导入宿主机 Root/TrustedPublisher。

## 8. Gate 6：按正确顺序签名和打包

假设修订后的签名脚本支持 `-CertificateThumbprint`：

```powershell
Set-Location $Repo
$Thumbprint = Read-Host '输入已登记的非秘密证书 thumbprint'

# 1. Sidecar 先签。
& .\tools\release\sign_release.ps1 `
  -CertificateThumbprint $Thumbprint `
  -Artifacts @($Sidecar) 2>&1 |
  Tee-Object (Join-Path $Evidence 'sign-sidecar.txt')
if ($LASTEXITCODE -ne 0) { throw 'Sidecar 签名失败。' }

# 2. 重新构建桌面二进制但暂不 bundle。
Set-Location (Join-Path $Repo 'apps\desktop')
npm.cmd run tauri -- build --no-bundle --no-sign 2>&1 |
  Tee-Object (Join-Path $Evidence 'tauri-build-final.txt')
if ($LASTEXITCODE -ne 0) { throw 'final desktop build 失败。' }

# 3. 桌面 EXE 先签。
Set-Location $Repo
& .\tools\release\sign_release.ps1 `
  -CertificateThumbprint $Thumbprint `
  -Artifacts @($Desktop) 2>&1 |
  Tee-Object (Join-Path $Evidence 'sign-desktop.txt')
if ($LASTEXITCODE -ne 0) { throw 'Desktop 签名失败。' }

# 4. 将已签 Sidecar 和 Desktop 装入 NSIS。
Set-Location (Join-Path $Repo 'apps\desktop')
npm.cmd run tauri -- bundle --bundles nsis --no-sign 2>&1 |
  Tee-Object (Join-Path $Evidence 'tauri-bundle-final.txt')
if ($LASTEXITCODE -ne 0) { throw 'final NSIS bundle 失败。' }

$Installer = Get-ChildItem `
  (Join-Path $Repo 'apps\desktop\src-tauri\target\release\bundle\nsis') `
  -Filter '*1.0.0*x64-setup.exe' -File | Select-Object -First 1
if (-not $Installer) { throw 'final installer 不存在。' }

# 5. 最后签安装器。
Set-Location $Repo
& .\tools\release\sign_release.ps1 `
  -CertificateThumbprint $Thumbprint `
  -Artifacts @($Installer.FullName) 2>&1 |
  Tee-Object (Join-Path $Evidence 'sign-installer.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installer 签名失败。' }
```

记录签名后摘要：

```powershell
$signed = @($Sidecar, $Desktop, $Installer.FullName) | ForEach-Object {
  $item = Get-Item -LiteralPath $_
  $sig = Get-AuthenticodeSignature -LiteralPath $item.FullName
  if (-not $sig.SignerCertificate) { throw "没有签名：$($item.FullName)" }
  if ($sig.SignerCertificate.Thumbprint -ne $Thumbprint) {
    throw "签名身份不一致：$($item.FullName)"
  }
  [pscustomobject]@{
    path = $item.FullName
    size = $item.Length
    sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
    status = $sig.Status.ToString()
    signer = $sig.SignerCertificate.Subject
    thumbprint = $sig.SignerCertificate.Thumbprint
  }
}
$signed | ConvertTo-Json | Set-Content (Join-Path $Evidence 'signed-digests.json') -Encoding utf8
```

宿主机没有信任自签证书时，链状态可能不是 `Valid`；但必须存在签名、thumbprint 一致且时间戳成功。真正的 `Valid` 验证放在临时 VM 信任导入后执行。

## 9. Gate 7：当前宿主机自动安装/生命周期

修复后的安装测试必须使用临时安装目录和临时 `ZCODE_DATA_DIR`，不得覆盖用户真实数据：

```powershell
Set-Location $Repo
& powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\apps\desktop\tests\test_installed_release_1_0_0.ps1 `
  -Installer $Installer.FullName `
  -EvidencePath (Join-Path $Evidence 'installed-release.json')
if ($LASTEXITCODE -ne 0) { throw '当前宿主机安装/启动/卸载 Gate 失败。' }
```

PASS 条件：

- 安装退出码 0。
- 冷启动 ready `<=5s`；60 秒只用于诊断。
- 热启动明显快于冷启动。
- 强杀 Sidecar 后最多自动重启 3 次，第 4 次熔断。
- 正常退出后无 desktop/sidecar/子进程残留。
- 静默卸载退出码 0，临时安装根目录被移除。

## 10. Gate 8：官方 ISO 与顺序 VM

### 10.1 ISO 来源

只允许以下 Microsoft 官方入口或它们当前重定向出的 Microsoft 下载地址：

- [Windows 11 Enterprise Evaluation](https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise)
- [Windows 10 Enterprise Evaluation](https://www.microsoft.com/en-us/evalcenter/download-windows-10-enterprise)

下载后记录：URL、文件名、版本/edition、语言、大小、SHA-256 和下载时间。来源无法核实的 `D:\迅雷下载\Win11_25H2_Chinese_Simplified_x64_v2.iso` 不得直接使用。

### 10.2 资源规则

- ISO 可放 D 盘，VM/VHDX 放 C 盘。
- 每次只运行一台 VM。
- 动态 VHDX 上限 `48 GB`，启动内存 `4 GB`，最大 `6 GB`，CPU `4`。
- 不创建 External VMSwitch；VM 初始不连接网络。

### 10.3 创建 VM

以下示例每次只替换 `$VmName` 和 `$IsoPath`：

```powershell
$VmName = 'ZCODE-GA-W11-20260823'
$IsoPath = Read-Host '输入已核验的 Microsoft 官方 ISO 绝对路径'
$VmRoot = Join-Path 'C:\HyperV\Zcode-GA-20260823' $VmName
$VhdPath = Join-Path $VmRoot "$VmName.vhdx"

if (-not (Test-Path -LiteralPath $IsoPath -PathType Leaf)) { throw 'ISO 不存在。' }
New-Item -ItemType Directory -Path $VmRoot -Force | Out-Null

New-VM -Name $VmName -Generation 2 `
  -MemoryStartupBytes 4GB `
  -NewVHDPath $VhdPath -NewVHDSizeBytes 48GB `
  -Path $VmRoot
Set-VMProcessor -VMName $VmName -Count 4
Set-VMMemory -VMName $VmName -DynamicMemoryEnabled $true `
  -MinimumBytes 2GB -StartupBytes 4GB -MaximumBytes 6GB
$Dvd = Add-VMDvdDrive -VMName $VmName -Path $IsoPath -PassThru
Set-VMFirmware -VMName $VmName -FirstBootDevice $Dvd
Enable-VMIntegrationService -VMName $VmName -Name 'Guest Service Interface'
Start-VM -Name $VmName
```

用户本人完成 Windows 安装、本地账户密码和必要的安全桌面操作。OS 安装完成后：

```powershell
Checkpoint-VM -Name $VmName -SnapshotName 'clean-os-before-zcode'
```

Windows 11 完成全部测试并保存证据后，必须先关机、列出 VM/VHDX 绝对路径并让用户确认删除，再创建 Windows 10 VM。

## 11. Gate 9：VM 内验收矩阵

### 11.1 复制测试材料

宿主机准备一个不含 `.git`、私钥、token 和用户数据库的测试包，包括：

- 最终安装器。
- 公钥 `.cer`。
- 必需的测试脚本和脱敏源码。
- Windows Python 3.12 官方安装器及离线 wheelhouse；若要在 VM 跑 pytest，不得临时依赖未知下载源。

使用已启用的 Guest Service Interface 复制到 `C:\ZcodeGA`。不得把 PFX 复制进 VM。

### 11.2 Windows 11 标准用户

在未导入信任证书前先运行一次安装器。用户本人处理 SmartScreen/UAC，并记录真实显示结果。随后卸载，再导入公钥到当前临时 VM 用户：

```powershell
$CerPath = 'C:\ZcodeGA\zcode-personal-release.cer'
Import-Certificate -FilePath $CerPath -CertStoreLocation 'Cert:\CurrentUser\Root'
Import-Certificate -FilePath $CerPath -CertStoreLocation 'Cert:\CurrentUser\TrustedPublisher'
```

再次安装并验证：

```powershell
$InstallRoot = Join-Path $env:LOCALAPPDATA 'Zcode Desktop Agent'
$DesktopInstalled = Get-ChildItem $InstallRoot -Filter 'tauri-spike.exe' -File -Recurse | Select-Object -First 1
$SidecarInstalled = Get-ChildItem $InstallRoot -Filter 'sidecar.exe' -File -Recurse | Select-Object -First 1

Get-AuthenticodeSignature $DesktopInstalled.FullName | Format-List *
Get-AuthenticodeSignature $SidecarInstalled.FullName | Format-List *
```

PASS 条件：安装无需管理员提升、应用 ready `<=5s`、安装目录内两个 EXE 的 signer thumbprint 与登记值一致。自签证书即使受信任，SmartScreen 仍可能基于信誉提示；应如实记录，不能把信任链与 SmartScreen 信誉混为一谈。

### 11.3 Windows 平台测试

在 VM 的隔离测试副本中安装离线 Python 依赖，再运行：

```powershell
$env:TESTING='1'
$env:LLM_PROVIDER='mock'
& C:\ZcodeGA\.venv\Scripts\python.exe -m pytest `
  C:\ZcodeGA\repo\services\control-core\packages\platform\windows\tests `
  -q --junitxml C:\ZcodeGA\evidence\windows-platform.xml
```

AppContainer、workspace ACL、ConPTY、UIA 枚举逐项记录。设计上需要管理员的能力必须明确标为受限能力，不能用“预期失败”笼统通过。

### 11.4 第二账户边界

从 VM 内的提升 PowerShell 只运行包装器：

```powershell
& powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File C:\ZcodeGA\repo\apps\desktop\tests\test_second_account_dacl.ps1 `
  -Sidecar $SidecarInstalled.FullName `
  -EvidenceDir C:\ZcodeGA\evidence\second-account-dacl
```

不要另行手工执行 `second_account_pipe_client.ps1`。随后执行新增的存储 ACL 包装器，分别验证 DB、logs、workspace 均为 access denied。临时账户必须在 finally 中删除。

### 11.5 离线 WebView2

确认 VM 没有虚拟网卡或已断开：

```powershell
Get-VMNetworkAdapter -VMName $VmName
```

在完全断网状态卸载后重新安装：

- 安装全过程成功。
- 应用正常渲染并 ready。
- 不提示下载 WebView2。
- 保存安装日志、截图和系统 WebView2 runtime 状态。

### 11.6 Windows 10 22H2

删除或归档 Windows 11 VM 后，用独立 VM 重复：标准用户安装、签名、离线 WebView2、启动、生命周期、第二账户 DACL/存储 ACL、ConPTY/Job Object 和卸载。

Windows 10 22H2 仅作为兼容性矩阵，不得扩展为长期安全支持承诺。

## 12. Gate 10：人工 UI 与真实会话验收

所有 UI 验收使用一次性 `ZCODE_DATA_DIR` 和 `LLM_PROVIDER=mock`。用户本人输入应用账户密码。

### 12.1 认证和任务

1. 注册 requester，登录、登出、再登录。
2. 创建 goal `file.read acceptance`，执行。
3. 打开任务详情，确认 step、args、risk、status 可见，最终 Effect 为 `CONFIRMED`。
4. 创建 goal `file.delete approval smoke`，执行到 `awaiting_approval`。
5. requester 自批准必须返回 403。
6. 登出，注册/登录第二个不同 principal，批准并 resolve。
7. 返回 requester，确认删除执行、Effect before/after hash 和审计事件存在。
8. 新建 delete 流程并走 reject，确认无删除 Effect。
9. 创建任务并中途 cancel，确认后续步骤不执行。

“另一管理员”不是当前 API 的硬要求；硬要求是第二个不同 principal，且服务端拒绝 self-approval。若产品要求管理员角色，必须先补 RBAC 权限校验和管理员创建流程。

### 12.2 Unknown outcome

1. 关闭应用。
2. 对一次性测试 DB 使用受保护的 fixture 工具生成一个 `UNKNOWN_OUTCOME`。
3. 启动应用，确认队列出现。
4. UI reconcile 为 `confirmed` 或 `failed`。
5. 再次 reconcile 返回 409，终态不变。
6. 记录 Effect、dispatch history 和审计事件，不保存 token。

### 12.3 安装版审计链

```powershell
$InstalledDb = Join-Path $env:LOCALAPPDATA 'zcode\agent_platform.db'
if (-not (Test-Path -LiteralPath $InstalledDb)) { throw '安装版 DB 不存在。' }
$env:DATABASE_URL = 'sqlite:///' + $InstalledDb.Replace('\','/')

Set-Location (Join-Path $Repo 'services\control-core')
& .\.venv-win\Scripts\python.exe .\scripts\verify_audit_chain.py 2>&1 |
  Tee-Object (Join-Path $Evidence 'installed-audit-chain.txt')
$auditExit = $LASTEXITCODE
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
if ($auditExit -ne 0) { throw '安装版审计链失败。' }
```

输出必须包含 `OK: audit chain intact`，并记录 DB SHA-256 和 chain head。

### 12.4 锁屏与 Grant 撤销

1. 准备一个可观察的待执行/活动 Grant。
2. 用户本人按 `Win+L` 锁屏，再解锁。
3. Zcode 继续读取新鲜日志和状态，不复用锁屏前 UI 索引。
4. 验证旧 session/Grant 已撤销，旧 token/Grant 不能继续执行。
5. 没有真实锁屏和拒绝证据时保持 `PENDING`。

## 13. Gate 11：许可证与供应链

在修复工具后执行：

```powershell
Set-Location (Join-Path $Repo 'apps\desktop\src-tauri')
cargo deny --config (Join-Path $Repo 'tools\license-policy\deny.toml') check licenses 2>&1 |
  Tee-Object (Join-Path $Evidence 'licenses-rust.txt')
if ($LASTEXITCODE -ne 0) { throw 'Rust license Gate 失败。' }

Set-Location $Repo
& $Py .\tools\license-policy\check_licenses.py `
  --requirements .\services\control-core\requirements-win-locked.txt `
  --npm-dir .\apps\desktop 2>&1 |
  Tee-Object (Join-Path $Evidence 'licenses-python-node.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python/Node license Gate 失败。' }
```

机器可读结果必须包含扫描组件数量。0 个组件、许可证空值或工具缺失都必须失败。

## 14. Gate 12：人工 N-1 回退

自动 Updater 为 `DEFERRED P5`。本次回退必须证明：版本化安装包可追溯、升级前备份有效、恢复后应用可用。

### 14.1 N-1 选择

候选 N-1 为历史 commit `9fc774d` 对应的 `0.1.0`，但只能在以下条件全部满足后采用：

- commit 可读取且是当前历史祖先。
- 从该 commit 的独立 worktree 重建成功，或已有安装器能证明对应 commit。
- 安装、启动、卸载通过。
- 安装器 SHA-256 和签名身份已登记。

仅凭现有文件名 `Zcode Desktop Agent_0.1.0_x64-setup.exe` 不得判定 N-1 合格。

### 14.2 数据备份与恢复

使用新增的 SQLite CLI：

```powershell
# 应用退出并确认无残留进程后执行。
Get-Process tauri-spike,sidecar -ErrorAction SilentlyContinue

& $Py .\tools\release\sqlite_release_backup.py backup `
  --database "$env:LOCALAPPDATA\zcode\agent_platform.db" `
  --backup-dir "$env:LOCALAPPDATA\zcode\backups" `
  --json-out (Join-Path $Evidence 'pre-upgrade-backup.json')

& $Py .\tools\release\sqlite_release_backup.py validate `
  --backup (Get-Content (Join-Path $Evidence 'pre-upgrade-backup.json') -Raw |
    ConvertFrom-Json).backup_path
```

演练顺序：

1. 安装并验证 N-1。
2. 创建可识别测试数据并做一致性备份。
3. 安装 1.0.0，验证迁移和测试数据。
4. 停止所有进程，卸载 1.0.0。
5. 安装 N-1。
6. 从升级前备份恢复，不做数据库向下迁移。
7. 执行 `PRAGMA integrity_check`、审计链验证和 UI 登录/读取验收。

任何数据丢失、schema 不兼容或恢复失败均为 `BLOCKED`。

## 15. Gate 13：候选 commit 与 CI

这是第一个 Git 人工批准点。除 CI 独立构建外，前述本地和 VM Gate 必须已通过。

### 15.1 停下并展示

```powershell
Set-Location $Repo
git status --short
git diff --check
git diff --stat
git diff --name-status
git diff
```

扫描并确认没有 PFX、key、password、token、VM 密码、用户 DB 或 ISO。然后向用户请求“创建并推送 RC 分支”的明确批准。

### 15.2 获得批准后

```powershell
git switch -c release/windows-v1.0.0-rc

# 只添加用户审查通过的源码、测试、CI 和文档路径；禁止 git add -A。
git add -- <approved-path-1> <approved-path-2> <approved-path-N>
git diff --cached --check
git diff --cached --stat
git diff --cached

git commit -m "release: prepare Windows v1.0.0 personal GA candidate"
git push -u origin release/windows-v1.0.0-rc
```

### 15.3 CI 判定

Zcode 通过 GitHub 已登录浏览器监控 RC workflow。不能使用或索取用户 token。

比较同一 commit 的本地 `unsigned-digests.json` 与 CI：

- Sidecar 和桌面 EXE 必须精确一致。
- NSIS 应精确一致；若仅 NSIS wrapper 不一致，必须解包比较内部 payload 清单。
- 只有内部 payload 全部一致，且差异被证明只来自 NSIS 非功能元数据时，Personal GA 才可记 `CONDITIONAL PASS`；不得写“可复现 PASS”。
- 任意业务二进制或资源摘要不同均为 BLOCKED。

## 16. Gate 14：发布记录和最终 Git

### 16.1 更新记录

更新：

```text
docs/releases/RELEASES.md
docs/releases/v1.0-gate.md
```

要求：

- 登记最终 installer/desktop/sidecar SHA-256、大小、thumbprint、commit。
- 自动 Updater/N-1 自动降级明确写 `DEFERRED P5`，不能写 PASS。
- 登记人工 N-1 安装器和 pre-upgrade backup 摘要。
- 附 Windows 11、Windows 10、第二账户、离线 WebView2、锁屏、许可证、CI 证据路径。
- Decision 只能是 `GO - Personal/Internal GA`，不得宣称公开 GA。

### 16.2 第二个 Git 人工批准点

展示最终 diff、Gate 表和待提交文件。获得用户明确批准后：

```powershell
# 仍然只暂存明确文件。
git add -- docs/releases/RELEASES.md docs/releases/v1.0-gate.md <approved-evidence-files>
git diff --cached --check
git diff --cached
git commit -m "release: finalize Windows v1.0.0 personal GA evidence"
git push origin release/windows-v1.0.0-rc
```

等待最终 RC CI 全绿。随后再次展示：

```powershell
git status --short --branch
git log --oneline --decorate -5
git tag --list v1.0.0
```

确认 tag 不存在且用户批准后：

```powershell
git switch main
git merge --ff-only release/windows-v1.0.0-rc
git push origin main
git tag -a v1.0.0 -m "Windows v1.0.0 Personal/Internal GA"
git push origin v1.0.0
```

禁止 `git push --force`，也不使用可能附带推送其他 tag 的宽泛命令。

## 17. 清理

发布证据确认完成后，先列出：

```powershell
Get-VM | Where-Object Name -Like 'ZCODE-GA-*' | Select-Object Name,State,Path
Get-ChildItem 'C:\HyperV\Zcode-GA-20260823' -Recurse -Force |
  Select-Object FullName,Length
Get-ChildItem 'D:\' -Filter '*.iso' -File -Recurse -Depth 3 |
  Select-Object FullName,Length
git worktree list
```

把拟删除的 VM、VHDX、checkpoint、ISO 和 N-1 worktree 绝对路径交给用户确认。未确认前不删除。

保留：

- 宿主机 `Cert:\CurrentUser\My` 中的代码签名证书。
- 两份用户离线 PFX 备份。
- 公钥 `.cer`、thumbprint、发布 SHA-256。
- 最终安装器、N-1 安装器、数据库备份和 Gate 证据。

临时 VM 删除后，VM 内导入的受信任证书随 VM 一并清理；宿主机信任存储应保持未修改。

## 18. 最终报告模板

```markdown
# Windows v1.0.0 Personal/Internal GA 执行报告

- Source commit:
- Tag:
- Installer SHA-256:
- Desktop SHA-256:
- Sidecar SHA-256:
- Certificate thumbprint:
- N-1 installer/digest:
- Pre-upgrade backup/digest:

| Gate | Status | Evidence |
|---|---|---|
| Git/source identity | | |
| Automated regression | | |
| UI/approval/effect | | |
| Cold start/lifecycle | | |
| Offline WebView2 | | |
| Win11 standard user | | |
| Second account/lock | | |
| Win10 22H2 | | |
| Signing | | |
| License policy | | |
| Manual N-1 rollback | | |
| Independent CI build | | |

## Deferred

- Automatic updater: P5
- Automatic downgrade: P5

## Decision

- GO - Personal/Internal GA / NO-GO
- Approver:
- Approval time:
```

只有表中所有本次硬 Gate 为 PASS，且用户完成最终 Git 批准，才允许输出 `GO - Personal/Internal GA`。
