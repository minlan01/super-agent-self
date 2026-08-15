# P3 Windows 后续执行与人工验收指南

**更新日期：** 2026-08-14  
**执行目录：** `D:\agent\Agents\super-agent-self\services\control-core`  
**适用 Shell：** Windows PowerShell 5.1  
**Git 约束：** 不要求 commit 或 push

## 1. 当前状态

| 项目 | 状态/证据 |
|---|---|
| P3.9 核心代码和当前管理员真机 | PASS |
| P3.10B 核心代码和当前管理员真机 | PASS |
| P3.10B 原生真机测试 | `7 passed` |
| P3.10B 定向组合 | `13 passed` |
| Shared + Windows platform | `158 passed, 5 skipped` |
| 执行/ToolGateway/security 回归 | `127 passed` |
| 标准用户、第二账户、Windows 10 | PENDING |
| P3.11 UIA、P3.12 WGC、Windows CI | PENDING |
| 整份 P3 手册 | **NO-GO** |

完成证据：

- `artifacts\p3.9-completion-report.md`
- `artifacts\p3.10b-completion-report.md`

## 2. 准备 PowerShell 环境

在 Windows PowerShell 5.1 中执行：

```powershell
cd D:\agent\Agents\super-agent-self\services\control-core
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$env:PYTHONUTF8 = "1"
.\.venv-win\Scripts\Activate.ps1
python --version
```

当前验证版本为 Python `3.12.10`。命令必须使用服务目录内的 `.venv-win`。

## 3. 重跑 P3.10B

### 3.1 原生 ConPTY 真机测试

```powershell
python -m pytest `
  packages\platform\windows\tests\test_conpty_windows.py `
  -q --junitxml=artifacts\p310b-native-conpty-tests.xml 2>&1 | `
  Tee-Object artifacts\p310b-native-conpty-tests-console.txt
```

当前基线：

```text
7 passed
```

这些用例必须在 Windows 真机执行，不得 skip。覆盖 UTF-8、resize、Ctrl-C、EOF、
heartbeat、disconnect/attach、断连回收、timeout、输出上限、scope 和 session 上限。

### 3.2 P3.10B 定向组合

```powershell
python -m pytest `
  packages\platform\windows\tests\test_conpty_windows.py `
  tests\unit\test_terminal_tools.py `
  -q --junitxml=artifacts\p310b-targeted-tests.xml 2>&1 | `
  Tee-Object artifacts\p310b-targeted-tests-console.txt
```

当前基线：

```text
13 passed
```

### 3.3 Shared + Windows platform

```powershell
python -m pytest `
  packages\platform\tests `
  packages\platform\windows\tests `
  -q --junitxml=artifacts\p310b-windows-platform-tests.xml 2>&1 | `
  Tee-Object artifacts\p310b-windows-platform-tests-console.txt
```

当前基线：

```text
158 passed, 5 skipped
```

5 个 skip 是 off-Windows/host-dependent fail-closed 测试。若原生 ConPTY 用例被
skip，不能验收。

### 3.4 执行和安全回归

```powershell
python -m pytest `
  tests\unit\test_terminal_tools.py `
  tests\unit\test_bash_tool.py `
  tests\unit\test_delegate_tool.py `
  tests\unit\test_executor.py `
  tests\unit\test_orchestrator.py `
  tests\unit\test_task_workspace_security.py `
  tests\unit\test_no_bypass.py `
  tests\unit\test_security_hardening.py `
  tests\test_tool_gateway.py `
  tests\test_orchestrator.py `
  tests\security\test_rbac_security.py `
  tests\security\test_security.py `
  -q --junitxml=artifacts\p310b-related-regression.xml 2>&1 | `
  Tee-Object artifacts\p310b-related-regression-console.txt
```

当前基线：

```text
127 passed
```

测试数量会随代码变化。验收条件是实际收集结果无 failure/error，并保存 JUnit、
控制台日志和执行环境，不是只比较写死数字。

## 4. 静态检查

```powershell
python -m ruff check `
  apps\api_server\routes\tasks.py `
  apps\personal_shell\executor.py `
  packages\executor\tools\_auto_import.py `
  packages\executor\tools\base.py `
  packages\executor\tools\bash_tool.py `
  packages\executor\tools\delegate_tool.py `
  packages\platform\shared\contracts.py `
  packages\platform\shared\terminal.py `
  packages\platform\tests\test_contracts.py `
  packages\platform\windows\adapter.py `
  packages\platform\windows\conpty.py `
  packages\platform\windows\process_sandbox.py `
  packages\platform\windows\process_tools.py `
  packages\platform\windows\terminal_tools.py `
  packages\platform\windows\tests\test_contract_integration.py `
  packages\platform\windows\tests\test_conpty_windows.py `
  packages\platform\windows\tests\test_process_conpty.py `
  packages\platform\windows\tests\test_windows_api.py `
  packages\protocol\schemas\enums.py `
  tests\unit\test_bash_tool.py `
  tests\unit\test_task_workspace_security.py `
  tests\unit\test_terminal_tools.py

git -C D:\agent\Agents\super-agent-self `
  -c core.filemode=false diff --check
```

当前结果为 PASS。`diff --check` 的 LF/CRLF 转换提示不是空白错误。

全变更文件 Ruff 另有 4 个既有 backlog：

- `packages\agent_core\orchestrator.py` 的 3 个 `E501`；
- `packages\execution\orchestrator.py:503` 的 `F841`。

后者涉及 policy re-check 结果未消费，应在 P3.0 安全修复中单独处理。

## 5. 残留检查

### 5.1 进程和编译产物

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq "cmd.exe" -and (
    $_.CommandLine -eq "cmd.exe /d /q" -or
    $_.CommandLine -eq "cmd.exe /d /q /k"
  )
} | Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine

Get-CimInstance Win32_Process | Where-Object {
  $_.Name -in @("python.exe", "pythonw.exe") -and
  $_.CommandLine -like "*super-agent-self*"
} | Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine

Get-ChildItem artifacts -File | Where-Object {
  $_.Extension -in @(".exe", ".obj", ".pdb")
}
```

当前三项均为空。

### 5.2 AppContainer profile

```powershell
$mapping = "Registry::HKEY_CURRENT_USER\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppContainer\Mappings"

Get-ChildItem -LiteralPath $mapping -ErrorAction SilentlyContinue |
  ForEach-Object {
    $value = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
    if (
      $value.Moniker -like "zcode.p39.*" -or
      $value.DisplayName -like "ZCode.P39.*"
    ) {
      [pscustomobject]@{
        Sid = $_.PSChildName
        Moniker = $value.Moniker
        DisplayName = $value.DisplayName
      }
    }
  }
```

当前结果为空。不要直接删除注册表 key；残留 profile 应通过
`DeleteAppContainerProfile` API 删除。

### 5.3 删除已确认的空调试目录

当前剩余目录均为空，是 2026-08-12 至 2026-08-14 的早期调试 workspace。
Codex 命令策略拒绝执行删除。人工执行前先完整检查：

```powershell
$targets = @(
  "$env:TEMP\p310b-debug-9x6qk02a",
  "$env:TEMP\p310b-debug-u85acykm",
  "$env:TEMP\p310b-mui-82s2bfy7",
  "$env:TEMP\p310b-systemcmd-gb4lpn3z",
  "$env:TEMP\p310b-systemcmd-k-kc0mj5d_",
  "$env:TEMP\p310b-systemcmd-k2-jzb9t2fh",
  "$env:TEMP\p3_verify_kaog19_w",
  "$env:TEMP\p3_verify_v6oadrdz",
  "$env:TEMP\p3_verify_vfvq3to1"
)

$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd("\") + "\"

foreach ($target in $targets) {
  $resolved = [IO.Path]::GetFullPath($target)
  $leaf = [IO.Path]::GetFileName($resolved)
  if (-not $resolved.StartsWith(
    $tempRoot,
    [StringComparison]::OrdinalIgnoreCase
  )) {
    throw "拒绝删除 TEMP 外路径: $resolved"
  }
  if ($leaf -notlike "p310b-*" -and $leaf -notlike "p3_verify_*") {
    throw "拒绝删除未知前缀: $leaf"
  }
  if (Test-Path -LiteralPath $resolved) {
    $files = @(Get-ChildItem -LiteralPath $resolved -Recurse -Force -File)
    [pscustomobject]@{
      Path = $resolved
      Files = $files.Count
    }
  }
}
```

只有所有目标仍在 `%TEMP%` 且 `Files=0` 时，执行：

```powershell
foreach ($target in $targets) {
  if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
  }
}

$targets | Where-Object { Test-Path -LiteralPath $_ }
```

最后一条命令应无输出。

## 6. 标准用户验收

必须登录一个非管理员账户，并在非提升 PowerShell 中执行第 2、3、5 节。

先记录环境：

```powershell
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)

[pscustomobject]@{
  Time = Get-Date -Format o
  User = $identity.Name
  Elevated = $principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
  )
  OS = [Environment]::OSVersion.VersionString
  PowerShell = $PSVersionTable.PSVersion.ToString()
  Python = python --version
}
```

通过条件：

- `Elevated=False`；
- 7 个原生 ConPTY 测试全部执行并通过；
- 无 shell、Python、AppContainer profile 或 native build artifact 残留；
- workspace ACL 在 close 后恢复。

## 7. 第二账户和客户端验收

当前 owner/workspace scope 已有自动化防篡改证据，但以下仍需人工完成：

1. 账户 A 启动 API/sidecar 和一个保持运行的终端 session。
2. 账户 B 使用自己的认证上下文尝试 read/write/attach 账户 A 的 session ID。
3. 三项必须返回权限拒绝，不能泄露输出或改变 session。
4. 账户 A 关闭客户端，等待断连宽限期结束。
5. 验证 shell、Job、profile 和 ACL 被回收。

实际 Tauri/sidecar 客户端尚未完成该矩阵，所以此项保持 PENDING。

## 8. Windows 10 22H2 验收

在隔离 VM 快照中安装同一依赖并执行第 2、3、5 节。报告必须记录：

- Windows edition、version 和 build；
- 标准用户/管理员身份；
- Python、Node、Rust 版本；
- collected/passed/failed/skipped；
- JUnit 和控制台日志路径；
- 残留检查结果。

未执行 Windows 10 22H2 前，不得把 P3.10B 人工矩阵标记为完整 PASS。

## 9. P3.9 重跑入口

P3.9 的 AppContainer/restricted-token 探针、定向命令和期望字段见：

```text
artifacts\p3.9-completion-report.md
artifacts\p3.9-appcontainer-probe-report.md
artifacts\p39_appcontainer_probe.py
```

标准用户、第二账户和 Windows 10 验收应同时覆盖 P3.9 与 P3.10B。

## 10. 整份 P3 后续顺序

1. 完成标准用户、第二账户和 Windows 10 的 P3.9/P3.10B 人工矩阵。
2. 修复 P3.0 policy re-check 和全仓历史测试基线。
3. 实现 P3.11 UI Automation 和 stale-state 门禁。
4. 实现 P3.12 Windows Graphics Capture。
5. 建立 Windows CI、Tauri/sidecar、打包、签名和回滚证据。
6. 完成 DPI、多屏、锁屏、UAC 和辅助功能矩阵。

在上述项目完成前，整份 P3 状态保持 **NO-GO**。

## 11. Git 操作边界

只读检查：

```powershell
cd D:\agent\Agents\super-agent-self
git -c core.filemode=false status --short
git -c core.filemode=false diff --check
```

本指南不要求执行 `git commit`、`git push`、`git reset` 或 `git checkout`。
