# 项目共享上下文与不可违反不变量

## 项目定位

`super-agent-self` 是一个 Agent 控制中心项目。系统协调任务、运行、步骤、Worker、工具调用、审批、授权、Artifact 和审计，并需要在多租户环境中安全执行可能产生真实外部副作用的动作。

本文件不是某个功能的详细设计，而是所有 Agent 的最低共同约束。任务包、ADR 或当前发布决策可以收紧这些约束，但不能在没有显式裁决的情况下放宽它们。

## 真相源优先级

发生冲突时按以下顺序判断，但不能静默覆盖冲突：

1. 当前用户确认的 Work Order 和验收条件。
2. 已接受 ADR、当前发布决策和安全例外记录。
3. 当前规范性的高层架构、系统设计、安全设计、部署设计和 UserStory。
4. 数据库约束、代码、测试、迁移和运行配置所表现的实际行为。
5. 历史报告、生成副本、汇总文档和过期示例。

Agent发现第 2 至第 4 层互相矛盾时，必须报告 `DECISION_REQUIRED`，列出冲突位置、行为差异、风险和推荐裁决，不得自行保留两套路径。

## 规范执行链

外部副作用必须只有一条规范执行链。抽象顺序为：

1. 服务端 ActorScope 确认调用主体、tenant、workspace 和 workload identity。
2. Policy 或不可变 Approval Resolution 产生授权依据。
3. GrantIssuer 创建短期、受 scope 约束、可撤销的 CapabilityGrant。
4. ExecutionControl 在事务中登记 Effect 和 dispatch intent。
5. WorkerBroker 依据有效 Lease 和 fencing token 调度 Worker。
6. ToolGateway验证 Grant、Effect、租户、资源、audience、Lease 和 fencing 后才允许 Adapter执行。
7. Adapter返回结构化结果；ToolGateway和 EffectJournal记录不可歧义的终态或待对账状态。
8. ExecutionControl协调 Run、Step 和 Lease 的完成，不允许旁路直接关闭其他模块拥有的状态。

仓库中不得同时保留“WorkerBroker直接调用 ToolGateway并消费 nonce”的旧规范路径。历史说明必须明确标记为非规范且不能被实现或测试引用。

## 状态与所有权不变量

- ExecutionControl拥有跨 Run、Step、Effect 的协调完成事务。
- WorkerBroker拥有 Lease 的创建、续租、释放和 fencing token 单调性。
- EffectJournal拥有 Effect 与 dispatch attempt 的状态历史，但不能越权关闭 Lease。
- Policy/Approval拥有授权决策；ToolGateway只验证并执行，不自行提升权限。
- ArtifactStore拥有 Artifact 元数据、quarantine、完整性和访问句柄。
- 一个状态只能有一个写入 Owner；其他模块通过 Interface 请求状态转换。
- 终态不可回退到可执行态。
- 所有状态转换必须带 tenant、workspace、actor/workload、关联 ID 和审计时间。

## 外部副作用与恢复不变量

- “没有 ToolReceipt”不能推导“工具没有执行”。
- 网络超时、进程崩溃或 ACK 丢失后，只有 Effect 状态和工具幂等契约能决定是否重试。
- 状态不确定时进入 reconciliation 或人工处置，默认不重放非幂等副作用。
- 每次 dispatch attempt必须持久化 Effect ID、attempt ID、Lease ID、fencing token、Grant digest、security context digest、Worker identity、目标 Adapter和时间。
- 旧 fencing token、过期或撤销 Grant、scope 不匹配和未知 Effect必须 fail closed。
- 幂等键必须由服务端生成并绑定 tenant、workspace、Effect 和具体操作语义。

## 授权与审批不变量

- 生产 Grant推荐使用 256-bit opaque handle，数据库只保存 digest，由 ToolGateway回表验证；如使用签名，只能让 GrantIssuer持有签名私钥。
- Adapter不得持有可签发 Grant 的密钥。
- Grant签名或摘要密钥、审计链密钥、会话密钥和 Artifact句柄密钥必须分域。
- Grant必须绑定 audience、tenant、workspace、资源、动作、Effect、Lease或等价执行上下文、security digest、过期时间和撤销状态。
- Approval至少包含不可变 Request、Vote、Resolution 和 Invalidation。
- 即使 quorum 为 1，也必须禁止发起人自审；审批身份来自服务端 ActorScope，不接受客户端自报。
- Approval必须绑定 plan、资源、Policy版本和 security digest；关键内容改变后旧 Resolution失效。
- 批准事务内部持久化唯一续跑命令；不得暴露可重复调用的通用 `resume` 接口。
- break-glass若未实现，必须明确禁止人工 DB/CLI 绕过；若实现，必须是独立授权依据并带 MFA、短时 Grant、理由、告警和事后复核。

## 多租户与内部身份不变量

- tenant 和 workspace 由认证上下文在服务端注入，调用者不能通过普通参数提升或切换 scope。
- 跨进程调用使用 mTLS 或等价 workload identity，并验证 audience。
- SQLAlchemy自动过滤不构成唯一隔离层。生产数据层应使用 PostgreSQL RLS、tenant-qualified 复合主外键/唯一约束或经批准的等强控制。
- 缓存、队列、WebSocket、Artifact、Export、备份和恢复必须进入同一 scope matrix。
- ExternalReference的唯一性至少覆盖 tenant、workspace、provider、reference type和外部标识。

## Artifact 不变量

- 风险取决于内容，不取决于文件数量。
- Artifact必须有 tenant/workspace scope、服务端生成的存储 key、大小和 MIME限制、checksum、quarantine状态和恶意内容处理。
- 未通过检查的 Artifact不能被工具执行、展示为可信内容或下发给其他租户。
- 访问使用短期受限句柄，不能暴露永久本地路径或对象存储主凭据。
- 如果 MVP没有这些控制，必须禁用上传、下载和产生可执行 Artifact 的工具能力。

## 数据迁移与切换不变量

- shadow read只证明某一时间窗口的一致性，不能替代冻结后的 final delta。
- 标准切换包含：预检查、双写或变更捕获、shadow验证、drain、数据库级硬 write fence、终止旧连接和未提交事务、final delta、计数与摘要校验、原子路由切换、观察窗口和可执行回滚。
- 应用层开关不能单独充当数据库硬 write fence。
- 运行中 Run不能在缺少 Lease、Grant、Effect和幂等状态迁移协议时转移到新系统。
- 所有迁移脚本可重复运行或具有明确断点，并记录批次、游标、校验和与耗时。

## Profile 与部署不变量

- Enterprise安全能力不能由租户数据库字段动态降级。
- Shell、Desktop、PTY等高风险能力若不在 Enterprise MVP中，应从构建产物、Worker pool和部署配置中物理移除。
- Personal与 Enterprise采用独立发布轨或签名部署 Profile；数据库配置不能装载部署中不存在或禁止的能力。
- 密钥来自专用 secret manager，禁止写入仓库、日志、任务包或测试快照。

## 验证与证据不变量

- 章节、关键词、行数和占位符检查只属于文档格式验证。
- 架构正确性需要状态机、事务所有权、并发、崩溃恢复、授权绕过和迁移故障测试。
- 每个验证证据至少包含：命令、工作目录、退出码、测试数量、关键输出摘要和时间。
- 测试跳过、环境不可用或无法运行必须明确报告，不得换成“静态检查通过”。
- 所有 P0 和 P1 发现关闭后，Independent Release Reviewer才可以评估生产放行。

