# Windows GA 收尾手册最终审查报告

- 审查日期：2026 年 8 月 23 日
- 原手册：`D:\Windows-GA收尾执行手册.md`
- 项目：`D:\agent\Agents\super-agent-self`
- 发布定位：`Personal/Internal GA`，仅用户本人使用
- 审查方式：源码、脚本、配置、现有产物、Git 状态和定向回归交叉核对

## 1. 最终结论

### 1.1 原手册

**NO-GO，不可原样交给 Zcode 执行。**

原手册的总体方向可用，但存在会产生虚假 `PASS`、错误签名顺序、验证错误数据库、无法由当前 UI 完成的验收项，以及 CI 没有真正重建 Sidecar 等问题。原样执行后即使所有复选框被勾选，也不能证明 Windows GA 条件成立。

### 1.2 修订手册

**CONDITIONAL-GO。**

可以把同目录的 `Windows-GA收尾-Zcode修订执行手册-2026-08-23.md` 交给 Zcode。Zcode 必须按顺序执行，先关闭源码和测试工具缺口，再构建、签名和做 VM 验收；不得跳过实现阶段直接进入人工清单。

## 2. 当前核实事实

### 2.1 Git

- 本地 `HEAD`：`c9a4796`
- 本地缓存的 `origin/main`：`389e43c`
- 关系：本地落后 2 个提交，无分叉，`git rev-list` 为 `0 2`
- 2026 年 8 月 23 日再次执行 `git fetch` 和 `git ls-remote` 时，GitHub 443 连接失败
- 因此，`389e43c` 只是本机已缓存的远端状态，不是本轮成功联网核实的最新状态
- 当前项目中存在本次审查生成的未跟踪 Markdown 和测试证据；不得用 `git clean` 删除

结论：禁止执行原手册中的直接 `git pull`。必须先成功 `fetch`，检查提交关系，再使用 `git merge --ff-only origin/main`。

### 2.2 当前环境

| 项目 | 当前值 |
|---|---|
| 宿主系统 | Windows 11 Pro，Build `26200`，64 位 |
| 内存 | 总计约 `15.85 GB`，审查时可用约 `7.92 GB` |
| Hyper-V | 已启用，`Get-VM`/`New-VM` 可用 |
| 已有 VM/虚拟交换机 | 审查时未列出 |
| C 盘可用 | 约 `60.32 GB` |
| D 盘可用 | 约 `28.48 GB` |
| Node/npm | `v24.18.0` / `11.16.0` |
| Rust | `cargo 1.97.1`、`rustc 1.97.1` |
| 项目 Windows Python | Python `3.12.10` |
| `signtool.exe` | 未安装或不在 `PATH` |
| `cargo-deny` | 未安装 |
| Python 许可证工具 | `pip-licenses 5.5.5` 已存在；不存在 `pip-license`/`pip_license` |

资源只适合**顺序**运行 Windows 11 与 Windows 10 VM。不得同时保留两台完整测试 VM。

### 2.3 当前代码与产物

- `apps/desktop/package.json` 和 `package-lock.json` 仍为 `0.1.0`
- Cargo 和 Tauri 配置为 `1.0.0`
- 当前 Sidecar、桌面 EXE、1.0.0 NSIS 安装器均为 `NotSigned`
- 当前 1.0.0 安装器约 `31 MB`，不是包含离线 WebView2 的最终候选体积
- 2026 年 8 月 23 日定向回归：`21 passed, 2 warnings`，证据为 `services/control-core/artifacts/windows-ga-review-targeted-tests-2026-08-23.txt`
- 定向回归只覆盖 IPC 契约与 Windows Named Pipe，不代表完整 GA
- 本机发现 `D:\迅雷下载\Win11_25H2_Chinese_Simplified_x64_v2.iso`，但没有可核验的官方下载来源记录，不能直接作为 Gate 证据

## 3. 严重问题

### P0-1：签名顺序错误

原手册先运行完整 `tauri build` 生成安装器，再签 Sidecar、桌面 EXE 和安装器。这样最终安装器内部很可能仍包含未签名的 Sidecar 和桌面 EXE。

正确顺序必须是：

1. 构建 Sidecar。
2. 使用同一证书签 Sidecar。
3. `tauri build --no-bundle` 构建桌面 EXE。
4. 签桌面 EXE。
5. `tauri bundle` 把已签内部文件装入 NSIS。
6. 最后签 NSIS 安装器。
7. 在干净 VM 中安装后，再验证安装目录内副本的签名。

### P0-2：现有签名脚本不满足秘密边界和稳定身份要求

`tools/release/sign_release.ps1` 当前存在以下问题：

- 每次 `-SelfSigned` 都新建证书，会改变发布身份。
- `-Password` 是普通字符串，可能进入命令历史或日志。
- PFX 只以 `EphemeralKeySet` 加载，但随后用 `signtool /sha1` 从证书存储查找，生产 PFX 路径需要实际验证。
- 脚本没有“按已登记 thumbprint 复用证书”的模式。
- 没有导出公钥证书和受控 PFX 备份流程。

本次应改为用户本人创建/导出一次证书，Zcode 只接收公钥指纹，并通过 `-CertificateThumbprint` 使用证书存储中的现有证书。密码和私钥不得进入对话、仓库、artifact 或命令参数。

### P0-3：CI 的“可复现构建”没有从源码构建 Sidecar

远端 `.github/workflows/ci.yml` 的 Windows release job 只执行：

```text
npm ci
npm run tauri build
```

但 `apps/desktop/src-tauri/resources/sidecar/` 被 `.gitignore` 忽略，远端只残留少量历史 `.pyd`，没有 `sidecar.exe`、bootstrap DB 和完整运行时。CI 没有调用 `services/control-core/scripts/nuitka-build/build.ps1`，因此该 job 不能证明完整安装包由同一源码重建。

此外，CI 只能构建已提交内容，而当前规则要求 Gate 全绿后才 commit，形成循环依赖。修订流程必须拆成“候选提交”和“最终 tag”两个批准点。

### P0-4：原 UI 验收清单包含当前产品无法展示的内容

当前桌面 UI：

- 任务表只显示 goal、status、created time，不显示步骤详情、Effect 状态或 before/after hash。
- 审批卡只显示 tool、step、risk 和 requester，不显示工具参数。
- Gateway approval API 返回参数哈希，不返回可供操作员审查的脱敏参数。
- 没有 unknown-outcome 队列和 reconcile UI。

因此原手册中的“参数可见”“时间线显示 CONFIRMED”“UI reconcile”“Effect before/after hash 可见”不能靠人工操作完成，必须先实现并测试。

### P0-5：Updater 文档不是客户端实现

仓库没有真正接入 `tauri-plugin-updater`，没有客户端检查、下载、签名验证、渠道、降级授权或断电恢复代码。已确认本次 Personal/Internal GA 不把自动 Updater/N-1 自动回退作为硬 Gate；该工作移入后续 P5。

本次必须用版本化安装包、SQLite 一致性备份和人工恢复演练替代，不能把自动 Updater Gate 写成 `PASS`。

## 4. 其他重要问题

### P1-1：审计链命令会验证错误数据库

原手册没有设置 `DATABASE_URL`，会使用默认相对路径，而不是安装版的 `%LOCALAPPDATA%\zcode\agent_platform.db`。必须显式传入安装版 DB 的绝对路径，并记录 DB SHA-256、审计链 head 和脚本退出码。

### P1-2：冷启动判定互相矛盾

- 原手册写“60 秒内 ready 即 PASS”。
- `measure_startup.ps1` 的等待超时在远端已改为 60 秒。
- 但脚本最终仍以 `<=5s` 判断 `all_passed`。

修订标准：60 秒是诊断等待上限；`<=5s` 才是既有性能 Gate。5 到 60 秒之间应标记 `FAIL_PERFORMANCE`，不能写成 PASS。

### P1-3：安装测试证据日期写死

`test_installed_release_1_0_0.ps1` 默认证据名和 JSON 内日期仍写死为 `2026-08-22`。必须改为运行时 UTC/本地时间、commit、安装器哈希和系统版本，防止新证据覆盖旧文件。

### P1-4：第二账户命令写法错误

`test_second_account_dacl.ps1` 本身要求提升权限、创建随机临时账户、以该账户运行 `second_account_pipe_client.ps1`，最后删除账户。原手册要求登录 tester2 后分别运行两个脚本，会绕过包装器的生命周期和证据逻辑。

正确方式是从提升的测试 VM PowerShell 只运行包装脚本。文件系统/DB 越界还需要独立的存储 ACL 测试，不能由 pipe error 5 推导。

### P1-5：许可证 Gate 当前会失败或误报通过

- CI 安装 `pip-license`，但 PyPI 没有该发行包；正确项目是 `pip-licenses`。
- 脚本调用不存在的模块 `pip_license`；本机实际模块为 `piplicenses`。
- Node 扫描依赖 `npm ls --json` 中的 `license` 字段，但本机输出的依赖项没有该字段；当前逻辑会把缺失许可证当成通过。
- `cargo-deny` 当前未安装。

许可证检查必须改成 fail-closed，并为“工具不存在、许可证为空、无法解析、未知 SPDX”添加失败测试。

### P1-6：版本号不一致

必须同时把以下文件更新为 `1.0.0`：

- `apps/desktop/package.json`
- `apps/desktop/package-lock.json`
- `apps/desktop/src-tauri/Cargo.toml`
- `apps/desktop/src-tauri/tauri.conf.json`

### P1-7：VM 与 ISO 需要更严格的资源和来源控制

- 只允许 Microsoft 官方 ISO。
- 当前来源不明的 Win11 ISO 不得直接使用。
- VM 必须顺序创建和删除，动态 VHDX，删除前再次核对绝对路径。
- 不得创建 External VMSwitch 或修改宿主机现有网络、启动和安全配置。

## 5. 已确认授权和边界

1. 发布仅供本人使用，名称为 `Personal/Internal GA`。
2. 自动 Updater 与自动 N-1 回退移入 P5。
3. 本次采用版本化安装包、数据库备份与人工回退。
4. 允许创建/删除明确命名的临时 Hyper-V VM、临时账户、快照，并执行断网、重启、安装和卸载测试。
5. 允许从 Microsoft 官方来源下载 Windows 10 22H2 与 Windows 11 ISO，并记录来源、大小和 SHA-256。
6. 允许在临时测试 VM 的 `CurrentUser` 信任存储中导入自签公钥证书；禁止修改宿主机信任存储。
7. 用户本人处理密码、私钥、SmartScreen/UAC 安全桌面和真实 `Win+L` 锁定/解锁。
8. Zcode 负责普通 UI 操作、构建、安装和不含秘密的证据收集。
9. 所有 Git commit/tag/push 前必须再次确认，禁止 force push。

## 6. 最终 GO 条件

| Gate | PASS 条件 |
|---|---|
| G0 源码身份 | 成功 fetch；提交关系明确；只用 `ff-only`；版本四处一致 |
| G1 自动回归 | 定向、Windows 平台、相关 unit/integration、前端 build、Cargo check 全绿 |
| G2 产品 UI | 步骤、审批参数、Effect hash、unknown-outcome 和 reconcile 在 UI 中真实可操作 |
| G3 安装生命周期 | 冷启动 `<=5s`；热启动更快；自动重启、正常退出、静默卸载无残留 |
| G4 离线安装 | VM 断网后完成安装和启动；安装器包含离线 WebView2 |
| G5 身份隔离 | Win11 标准用户、第二账户 pipe error 5、存储 ACL、真实锁屏 Grant 撤销均有证据 |
| G6 OS 矩阵 | Windows 11 与 Windows 10 22H2 顺序 VM 验收完成 |
| G7 签名 | 同一自签身份；内部文件先签；安装后副本验签；证书和产物指纹登记 |
| G8 供应链 | Rust/Python/Node fail-closed 许可证检查全绿；工具和输出留证 |
| G9 回退 | N-1 来源可追溯；升级前 SQLite 备份通过 integrity check；人工恢复演练通过 |
| G10 独立构建 | 候选 commit 在 CI 从源码重建 Sidecar+桌面+安装器；记录并解释摘要差异 |
| G11 发布身份 | Gate Record 无虚假 PASS；用户批准最终 commit/tag/push；无 force push |

任一项没有实际证据时，最终 Decision 必须是 `NO-GO`。

## 7. 审查决定

原手册应保留为历史草案，不修改、不执行。使用修订手册后，任务在工程上可完成；预计工期应从原来的 2 到 2.5 天调整为 **3 到 5 个工作日**，其中 VM 安装、Nuitka/离线 WebView2 构建、CI 重建和人工交互可能增加等待时间。
