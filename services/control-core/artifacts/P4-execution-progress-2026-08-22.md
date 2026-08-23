# P4 执行进度

- 日期：2026-08-22
- 项目：`D:\agent\Agents\super-agent-self`
- 手册：`D:\P4-真Sidecar与IPC契约实现手册.md`
- Git 操作：不 commit、不 push
- 当前结论：**NO-GO**

## 当前阶段

正在处理安装版生产模式 Sidecar 启动性能 Gate。

## 已确认

- 安装包中的是真实 control-core Sidecar，不是 spike demo。
- IPC 契约、Windows Named Pipe、DACL、peer PID 与生命周期代码已存在。
- 当前生产模式 Sidecar 使用全新数据库时约 `13.807s` 才输出 ready。
- 手册要求壳启动到 Sidecar ready 不超过 `5s`。
- 当前启动顺序会在 Named Pipe ready 前运行迁移，并完整导入 `apps.api_server.main` 及全部 API 路由。

## 正在执行

1. 已确认桌面端只调用 `/health`、认证、任务和 gateway approvals 路由。
2. 已实现 `ZCODE_API_PROFILE=desktop` 最小路由装配；完整 API 仍是默认入口。
3. Sidecar 强制选择 desktop profile，并跳过桌面不使用的模板、指标、WebSocket 和 GraphQL 初始化。
4. 完整 P4 定向回归已通过，正在进行第二轮 Nuitka 构建前检查。

最新回归：`22 passed`，包括 desktop profile 1、IPC 契约 15、Windows
Named Pipe 集成 6。此前发现的 `/api/v1/approvals` 兼容缺口已修复。

第一轮优化构建结果：`92` 个文件、`132.172 MB`，SHA-256 为
`2B36D065CB79CCEEA3BD909C9B2BACE387D6D25A0FCFE7E16006CDEE8BD2509B`。
全新数据库三次完整 ready 为 `9.554s / 9.576s / 8.383s`，仍失败，
因此没有继续打包。

第二轮已增加：

- 由正式 Alembic 生成并校验的空白 head SQLite 模板；现有旧库仍走标准迁移。
- `packages.platform.windows` 公共 API 惰性导入，Sidecar 模块导入由约
  `1.856s` 降到 `0.659s`。
- Sidecar transport 与完整 desktop API 两阶段初始化；`sidecar ready`
  仍只在 Named Pipe 和完整 API lifespan 都完成后记录，不降低 Gate 语义。
- Nuitka 仅显式包含桌面实际需要的认证、任务和两类审批路由。

最新定向回归：`30 passed`。源码 transport ready 三次最大 `2.356s`，
完整 API ready 最大 `8.149s`；最终是否通过只以新 Nuitka 安装产物为准。

第二轮构建前检查：新增 Python 文件 Ruff 通过、`py_compile` 通过、桌面
`npm.cmd run build` 通过。当前开始第二轮 Nuitka standalone 构建。

第二轮第一次构建尝试在模板生成阶段停止：构建虚拟环境找不到项目
`packages`，原因是 `PYTHONPATH` 设置顺序晚于模板生成器。已保留失败日志
`nuitka-rebuild-2.log`，正在修正构建脚本后重试。

## 当前测量

- 安装版旧构建、已迁移数据库：`6.811s`，仍失败。
- 修改前完整 `apps.api_server.main` 源码导入：约 `7.6s`。
- 最小桌面路由原型源码导入：`1.805s`。
- 修改后桌面 profile 契约测试：`1 passed`。
- 修改后源码生产模式、全新数据库 ready：`10.280s`；该次包含冷解释器、迁移框架、18 次迁移和 API 导入。
- 缓存预热后的“迁移 + 桌面 API 导入”：`1.765s`。

## 待验证假设

1. 全量 API 路由导入是主要耗时来源；最小路由装配应显著缩短启动。**已验证。**
2. `tasks` 路由自身提前导入执行器、LLM 或 Windows 自动化链；若成立，需要进一步延迟加载该链。
3. 启动期模板和 RBAC seed 是主要耗时来源；若成立，同一已迁移、已 seed 数据库应明显更快。**不是主因；模板已从桌面 profile 移除，RBAC 保留。**
4. Nuitka 安装产物的模块加载成本是主要来源；若成立，源码优化不会等比例反映到安装版。

## 待验证

- 源码生产模式 ready 不超过 `5s`。
- Nuitka 重新构建后的安装版 ready 不超过 `5s`。
- 所有 P4 契约、管道、审批与生命周期回归测试通过。
- 重建 Tauri 和 NSIS 后重新记录体积、哈希与签名状态。
