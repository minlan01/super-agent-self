# Zcode 剩余阶段执行审查报告

> 执行日期: 2026-08-16
> 项目: `D:\agent\Agents\super-agent-self`
> 手册: `D:\Zcode剩余阶段完整执行手册.md`
> 基线: `main @ 0f2fb34fac42e00a6233139f4be0222ffb89a52f`
> Git 操作: 未执行 `git commit`，未执行 `git push`
> 最终源码复验: 2026-08-16 11:41 +08:00 后重新生成核心与集成证据
> 最终结论: **Windows v1.0 NO-GO**

## 1. 本轮完成内容

1. 修复 Windows 对 `/etc/passwd`、`\etc\passwd` 这类当前盘根路径的分类，稳定返回 `outside workspace`，且继续 fail closed。
2. 修复 Personal API 用户隔离: 提醒列表、上下文、偏好和提醒删除全部绑定认证用户。
3. 增加跨用户回归: 不返回其他用户提醒，不允许删除其他用户提醒。
4. 将 ORM `_now()` 改为线程安全、严格递增的 UTC 时间源，修复 Windows 粗粒度时钟导致的消息、会话、通知和 edition 排序不稳定。
5. 将 DOCX 工作区逃逸检查前置到可选依赖导入之前。
6. 补齐 Redis 测试依赖并锁定 `redis==6.4.0`；安装 Playwright Chromium 运行时。
7. 修复 Authenticode 自动测试的隐藏安全提示问题，改为非交互签名存在性、篡改拒绝和原件不变验证。
8. 生成 Rust Windows CycloneDX SBOM，消除原 Rust SBOM 缺失项。
9. 刷新 Python、Node、Rust 漏洞审计、Python 许可证和 Bandit 证据。
10. 完成当前主机静默安装、已安装生命周期和静默卸载复验。
11. 清理 `personal.py` 的尾随空格；25 个本轮 Python 文件的 Ruff `F/I` 检查通过。
12. 在最终源码上严格重跑完整核心和集成测试，并覆盖刷新 JUnit 与控制台证据。
13. 复核八份 JUnit、三类 SBOM、漏洞审计、安装包哈希、签名状态和报告链接。

## 2. 手册执行状态

| 手册项 | 状态 | 结论 |
|---|---|---|
| P3.1 标准用户人工矩阵 | PENDING | 当前会话不是独立标准用户登录态，不能代替人工矩阵 |
| P3.2 第二本地账户越界 | PENDING | 未获得第二账户交互登录环境 |
| P3.3 Windows 10 22H2 | BLOCKED | 当前没有干净 Win10 22H2 VM/设备 |
| P3.4 WGC | PASS | 原生 WGC、保密水印、会话释放和拒绝 fail closed 已验证 |
| P3.5 核心回归 | PASS | 核心、集成、unit、Windows 和桌面批次均为 0 failed |
| P3.5 真实桌面到 control-core E2E | BLOCKED | 安装器仍打包 health/echo spike，不是真实 control-core |
| P4.1 NSIS 安装器 | PASS | 当前主机静默安装、启动、生命周期和卸载通过 |
| P4.1 生产签名/时间戳 | BLOCKED | 所有最终二进制仍为 `NotSigned` |
| P4.1 干净 VM 十分钟首任务 | PENDING | 无干净 VM，且当前包不含真实 control-core |
| P4.2 签名更新与 N-1 回退 | BLOCKED | updater、CDN、版本协商和原子回退未实现 |
| P4.3 锁文件 | PASS | Python、Node、Rust 均有锁定输入 |
| P4.3 同机可重复构建 | PASS | 两次完整 Tauri 构建的桌面和安装器哈希一致 |
| P4.3 隔离构建机复现 | PENDING | 尚未在全新 CI/构建机复现 |
| P4.3 Python/Node/Rust SBOM | PASS | 三类 CycloneDX 文件均已生成 |
| P4.4 企业静默安装 | PARTIAL | 当前用户 NSIS 通过；企业 per-machine、代理和真离线未闭环 |
| P4.5 五份 Runbook | PASS | 五份文件均已创建并纠正不支持命令 |
| P4.6 Gate Record | PASS | 已生成 `docs/releases/v1.0-gate.md` |
| P4.6 实际 staged rollout | BLOCKED | 无签名 updater、渠道和批准人 |
| P5 Linux | BLOCKED | 当前 Windows 会话无法完成 Linux 真机验收 |
| P6 macOS | BLOCKED | 无 macOS/Developer ID/公证环境 |
| P7 受控进化 | PENDING | 必须在 Windows GA 基础门禁完成后进入 |

## 3. 最终测试证据

| 批次 | 结果 | 证据 |
|---|---:|---|
| 核心执行链和平台合约 | `357 passed, 5 skipped` | [p4-final-core.xml](p4-final-core.xml) |
| 集成测试 | `343 passed` | [p4-final-integration.xml](p4-final-integration.xml) |
| unit 第 1 批 | `600 passed, 4 skipped` | [p4-final-unit-batch1.xml](p4-final-unit-batch1.xml) |
| unit 第 2 批 | `820 passed` | [p4-final-unit-batch2.xml](p4-final-unit-batch2.xml) |
| unit 第 3 批 | `500 passed` | [p4-final-unit-batch3.xml](p4-final-unit-batch3.xml) |
| shared fixtures 隔离自检 | `13 passed` | [p4-final-shared-fixtures.xml](p4-final-shared-fixtures.xml) |
| Windows 原生平台 | `168 passed, 5 skipped` | [p4-final-windows.xml](p4-final-windows.xml) |
| Desktop + UIA/WGC follow-up | `52 passed, 4 skipped` | [p4-final-desktop.xml](p4-final-desktop.xml) |

全部 JUnit 和控制台输出位于:

`D:\agent\Agents\super-agent-self\services\control-core\artifacts`

八份 JUnit 均为 `0 failures / 0 errors`。最终核心测试开始时间为 `2026-08-16 11:41:31 +08:00`，最终集成测试开始时间为 `2026-08-16 11:41:58 +08:00`。核心测试有 3 条 warning，集成测试有 141 条 warning，主要来自测试环境默认 `SECRET_KEY` 提示、Starlette/httpx 弃用提示和 Pydantic class-based config 弃用提示。

静态检查口径:

- 25 个本轮修改或新增 Python 文件的 Ruff `F/I` 检查通过。
- `git diff --check` 无空白错误，仅有 Git 的 LF 转 CRLF 提示。
- 完整 Ruff 规则仍有 61 项非门禁样式/现代化技术债: `E501` 39 项、`UP042` 19 项、`N817` 1 项、`UP017` 2 项；未在收尾阶段做跨模型层重构。

## 4. 安装包验收

| 项目 | 结果 |
|---|---|
| 安装器 | `apps\desktop\src-tauri\target\release\bundle\nsis\Zcode Desktop Agent_0.1.0_x64-setup.exe` |
| 大小 | `7,753,711` bytes |
| SHA-256 | `616F7AC540A45289CD38863FC47F92A97C233E0959ACFBBEA3B40EFAE73938E5` |
| Desktop SHA-256 | `8D6197870693C4733467C54E19BFB5003A53DD46E4F4E75B5CCE041F6D44A292` |
| 原件签名 | `NotSigned` |
| 非交互签名副本 | 签名存在，签名者匹配；自签证书未受信任，因此不是生产 `Valid` |
| 篡改测试 | `HashMismatch` |
| 原件保护 | 原安装包哈希不变 |
| 静默安装 | `2.273s`，exit `0` |
| 已安装启动 | `1.743s` |
| 崩溃恢复 | 前三次重启，第四次停止重启 |
| 父进程/正常关闭清理 | PASS |
| 静默卸载 | `0.906s`，注册表、目录、进程、端口均清理 |

卸载后现场已复核: 临时证书 `0`、签名临时目录 `0`、安装注册表 `0`、监听端口 `0`。

## 5. 供应链结果

| 项目 | 结果 |
|---|---|
| Python SBOM | CycloneDX 1.6，72 个锁定组件 |
| Node SBOM | CycloneDX 1.5，19 个组件 |
| Rust Windows SBOM | CycloneDX 1.5，253 个组件、254 条依赖记录 |
| Python 漏洞 | 71 个可审计依赖，0 已知漏洞；`packaging` 被 pip-audit 排除 |
| Node 漏洞 | 78 个依赖，0 漏洞 |
| Rust 漏洞 | 0 vulnerability advisories |
| Rust 警告 | 16 unmaintained，2 unsound |
| Rust Windows 目标 | 两个 unsound 包均不在 `x86_64-pc-windows-msvc` 依赖图 |
| Bandit | 生产代码 0 Medium，0 High |
| Python 许可证 | 72 条锁记录中返回 71 条元数据；`wcwidth` 待人工核对 |

## 6. 阻止 Windows v1.0 GA 的硬条件

1. 桌面安装包仍启动 health/echo spike，而不是真实 control-core。
2. IPC 仍使用 `\\.\pipe\zcode-sidecar-spike`，没有正式协议迁移和版本协商。
3. 产品版本仍是 `0.1.0`，当前修改也没有不可变 release commit/tag。
4. 桌面、sidecar、内层可执行文件和安装器没有生产 Authenticode 证书及可信时间戳。
5. 自动更新、签名 manifest、CDN 渠道、断电恢复和 N-1 原子回退未实现。
6. WebView2 使用 `downloadBootstrapper`，无法证明真正离线安装。
7. 标准用户、第二账户、干净 Win10 22H2 和干净 Win11 VM 矩阵未完成。
8. 只证明了同机同路径可重复构建，未证明隔离 CI 构建一致。
9. Node/Rust 许可证策略尚未在 CI 强制执行，N-1 安装包也未归档批准。

## 7. 完成剩余项的执行顺序

1. 先把真实 control-core 接入 `ExecutionOrchestrator -> ToolGateway`，替换 spike sidecar 和 Named Pipe。
2. 在标准用户登录态重跑 Windows、terminal 和 workspace 安全测试，并保存人工 findings。
3. 使用第二本地账户验证 workspace ACL、AppContainer SID 和租户数据零交叉。
4. 在干净 Win10 22H2、Win11 标准用户 VM 验证安装、WebView2、首任务、升级、回退和卸载。
5. 配置生产证书，在打包前签所有内层 PE，打包后签安装器，并验证可信时间戳。
6. 实现 Tauri signed updater、internal/invited/10%/50%/100% 渠道及 N-1 回退。
7. 在隔离 CI 从同一 commit 和 lockfile 重建，核对桌面、sidecar 和安装器 SHA-256。
8. 添加 Node/Rust 许可证 allow/deny 策略、批准人和 N-1 回滚点后重新签发 Gate Record。

## 8. 最终裁决

当前主机可执行的 P3/P4 工程验证已完成，代码回归、Windows 原生能力、SBOM、安全审计和本机安装生命周期均通过。Gate Record 见 [docs/releases/v1.0-gate.md](../../../docs/releases/v1.0-gate.md)。

但产品集成、生产签名、更新回退、真离线和受支持系统/账户矩阵仍缺失，因此不得发布为 Windows v1.0 GA。正式裁决为 **NO-GO**。
