# Agent Control Center 单一控制面迁移与修复计划 v2.0

创建日期：2026-07-18  
原始方案：`C:\Users\Administrator\Desktop\agent-control-center-design-and-fix-plan.md`  
目标：将 `F:\Agents` 下现有 Agent 资产收敛为一个可控、可审计、可恢复的 Agent Control Center。

## 1. 执行摘要

现有项目不应继续以“三套系统互相调用”的方式集成。推荐目标是：

> 一个任务与执行控制面，一个操作者控制台，一组可替换 Adapter，一套版本化 Workflow，以及一个由事件重建的可视化世界。

核心决策：

1. `myself-agent` 是唯一任务、策略、审批、执行、审计、记忆和技能写模型。
2. `agent_tianshu` 不再拥有独立任务生命周期，转为版本化 Workflow Definition。
3. `more_agents/unified-admin` 是唯一前端候选，Express 仅保留无状态 BFF 和协议代理职责。
4. `ClawLibrary` 作为可视化包接入，UI 只消费稳定的读模型，不直接解释各后端原始事件。
5. `agent_contorl` 作为上游源码快照归档，不再成为新的开发主线。
6. `more_agents/backend` 只提取 AgentProfile、Worker 心跳、容量、Snapshot 等概念，不部署第二套 Orchestrator。
7. `super-agent-self` 可作为最终迁移仓库，但不得创建第四套任务后端。

在完成唯一执行入口、真实审批、租户隔离、持久任务和幂等副作用之前，冻结新增终端、桌面、插件和自进化功能。

## 2. 现有资产与最终归属

| 资产 | 当前状态 | 最终角色 | 处理方式 |
|---|---|---|---|
| `myself-agent` | 功能最完整，但执行链、安全和文档存在分叉 | Core Control Plane | 原地加固或迁入新主仓，保留唯一写模型 |
| `agent_tianshu` | 主题化多 Agent 流程原型 | Workflow Catalog | 提取角色、阶段、审核门、路由与停滞策略 |
| `more_agents/unified-admin` | 已融合 OpenClaw、Hermes、Myself Agent 和 Museum | Operator Console | 保留前端壳，收缩 Express BFF |
| `more_agents/backend` | 第二套 Agent/Task/Queue 原型，测试不足 | Reference Only | 只提取模型和运行指标概念 |
| `more_agents/clawlibrary` | 可视化运行世界和资产空间 | Visualization Package | 打包接入，建立 Telemetry Adapter |
| `more_agents/frontend` | 独立 Next.js 控制中心原型 | UI Component Source | 迁移少量有价值视图后退役 |
| `agent_contorl` | OpenClaw Admin 与 ClawLibrary 下载快照 | Archive | 记录上游来源后只读归档 |
| `super-agent-self` | 空目录 | Migration Target | 仅在迁移 ADR 批准后初始化 |

### 2.1 明确不做的事情

- 不再新建一套独立 Orchestrator。
- 不让天枢与 `myself-agent` 双向创建任务。
- 不让 Express BFF 保存任务、审批或队列状态。
- 不继续复制 ClawLibrary 源码到多个前端。
- 不让 CLI、Cron、SubAgent、插件直接调用 Tool 实例。
- 不用共享 `.env` 向所有进程暴露全部凭据。
- 不把 mock 数据伪装成在线遥测。

## 3. 架构原则

### 3.1 唯一写入者

每类状态只能有一个权威写入者：

| 状态 | 唯一写入者 |
|---|---|
| Task、Run、StepRun | Core Control Plane |
| ApprovalRequest、CapabilityGrant | Policy/Approval 模块 |
| WorkflowRun、WorkflowPhase | Workflow 模块，通过 Control Plane 事务写入 |
| Worker、Lease、Heartbeat | WorkerBroker |
| DomainEvent | EventLog/Outbox |
| UI Snapshot | Projection 模块 |
| OpenClaw/Hermes 外部状态 | 对应 Adapter，只能写外部引用和观测结果 |

### 3.2 所有副作用走同一 Interface

HTTP、CLI、Chat、Cron、SubAgent、Workflow、插件必须调用同一个 `ExecutionControl` interface。

禁止出现以下旁路：

- `tool_registry.get_tool_instance(...).execute(...)`
- CLI 直接调用 `tool.execute()`
- SubAgent 自行签发上下文并执行工具
- BFF 直接执行文件删除、终端、桌面或备份操作
- Workflow Adapter 绕过 Policy 调用外部命令

### 3.3 观察与控制分离

Control Center 分成三类 Module：

1. Query/Telemetry：只读 Snapshot、Timeline、Health、Metrics。
2. Command Gateway：接收类型化命令，统一转入 `ExecutionControl`。
3. Privileged Adapter：PTY、文件、桌面、浏览器和备份，运行在隔离进程或容器。

UI 中的风险提示不能替代服务端 Policy、审批、作用域令牌和审计。

### 3.4 Audit、Domain Event、Telemetry 分离

- Domain Event：业务状态变化，可用于重建读模型。
- Audit Record：安全与合规证据，采用更严格保留和完整性保护。
- Metric/Log：性能、健康和排障数据，不作为业务事实源。

## 4. 规范领域模型

### 4.1 身份与作用域

```text
ActorScope
  tenant_id
  workspace_id
  principal_id
  principal_type: user | service | agent
  roles
  permissions
  auth_context
```

约束：

- `ActorScope` 只能由服务端认证模块生成。
- 请求体不得接受可伪造的 `user_id`、`tenant_id` 或管理员身份。
- Repository interface 必须显式接收 `ActorScope` 或受约束 Scope。
- 缓存键、事件、文件路径和审计记录必须包含租户/工作区作用域。

### 4.2 任务与执行

```text
Task
  稳定的用户意图和业务身份

Run
  Task 的一次执行尝试

PlanVersion
  不可变计划版本

StepRun
  某个计划步骤的一次执行尝试

ToolReceipt
  工具执行的规范结果和副作用证据
```

重试创建新的 `Run` 或 `StepRun attempt`，不得覆盖历史执行证据。

### 4.3 状态拆分

不得把所有状态合并成一个 `task.state: string`。

```text
TaskLifecycle
  submitted | queued | running | waiting_approval
  completed | failed | cancelled

WorkflowPhase
  receiving | planning | reviewing | dispatching
  executing | aggregating | completed

WorkerStatus
  offline | idle | leased | busy | degraded

SessionState
  connecting | active | disconnected | expired
```

### 4.4 审批与授权

```text
ApprovalRequest
  approval_id
  actor_scope
  run_id
  step_run_id
  tool_name
  normalized_args_hash
  resource_scope
  policy_digest
  requested_at
  expires_at
  status

CapabilityGrant
  grant_id
  tenant_id
  run_id
  step_run_id
  attempt
  tool_name
  normalized_args_hash
  resource_scope
  nonce
  issued_at
  expires_at
  key_id
```

只有审批完成且 Policy 再验证通过后才能创建 `CapabilityGrant`。

### 4.5 Workflow 与 Agent

```text
WorkflowDefinition
  version
  roles
  phases
  transitions
  review_gates
  routing_rules
  stall_policy
  output_contract

WorkflowRun
  workflow_definition_version
  task_id
  current_phase
  phase_history

AgentProfile
  role
  capabilities
  allowed_tools
  model_profile
  concurrency_limit

Worker
  runtime process or remote agent instance

Lease
  Worker 对 StepRun 的限时所有权
```

天枢的部门名称属于 WorkflowPhase/Role，不属于 TaskLifecycle。

### 4.6 自进化模型

```text
MemoryRecord
  scope + source + retention + confidence + content

SkillVersion
  immutable definition + source evidence + policy compatibility

SkillEvaluation
  sample size + baseline + quality delta + failure rate + cost delta
```

Skill 只有在达到最小样本量、质量提升和安全回归门槛后才能晋升。

## 5. 目标架构

```text
Operator Console: unified-admin
  |
  |-- Query API ---------------------> Projection / Read Model
  |
  |-- Command API -------------------> ExecutionControl
  |
  `-- Provider Views ----------------> OpenClaw/Hermes Adapters

Core Control Plane: myself-agent
  |
  |-- ExecutionControl
  |-- Policy + Approval
  |-- Workflow Runtime
  |-- WorkerBroker
  |-- ToolGateway
  |-- Memory + Skill Evaluation
  |-- EventLog + Transactional Outbox
  `-- Audit Store

Adapters
  |-- OpenClaw Adapter
  |-- Hermes Adapter
  |-- Tianshu Workflow Adapter
  |-- Browser Adapter
  |-- Desktop Adapter
  |-- PTY Adapter
  `-- Plugin Host Adapter

Projection
  |-- AgentSnapshot
  |-- TaskTimeline
  |-- ApprovalQueue
  |-- WorldDelta
  `-- SourceHealth/Freshness
```

## 6. 核心 Module Interface

### 6.1 ExecutionControl

```text
submit(actor_scope, task_request) -> task_id
execute(actor_scope, task_id, idempotency_key) -> command_receipt
resume(actor_scope, approval_id, idempotency_key) -> command_receipt
cancel(actor_scope, task_id, expected_revision) -> command_receipt
```

Interface 不暴露 DB Session、Memory 列表、Skill 列表、Tool 实例或内部 Context。

### 6.2 Policy

```text
decide(actor_scope, action_request) ->
  DENY(reason)
  WAIT_APPROVAL(approval_spec)
  GRANT(grant_spec)
```

不允许用 `allowed=true + requires_approval=true` 表达等待审批。

### 6.3 Approval

```text
request(approval_spec) -> approval_id
resolve(actor_scope, approval_id, decision, expected_revision) -> resolution
expire(approval_id) -> resolution
```

批准动作必须触发持久化 Resume Command，而不是只更新审批表。

### 6.4 WorkerBroker

```text
claim(worker_id, capabilities) -> lease | none
heartbeat(worker_id, lease_id) -> lease_status
complete(worker_id, lease_id, tool_receipt) -> completion
fail(worker_id, lease_id, failure) -> retry_decision
```

### 6.5 Workflow

```text
install(definition) -> workflow_version
instantiate(task_id, workflow_version) -> workflow_run_id
handle_event(workflow_run_id, domain_event) -> workflow_actions
```

### 6.6 ToolGateway

```text
execute(capability_grant, tool_request) -> tool_receipt
```

ToolGateway 必须验证 Grant、nonce、参数哈希、资源范围和过期时间。

### 6.7 EventLog 与 Projection

```text
EventLog.append(events) -> append_receipt
EventLog.read(cursor, filters) -> event_page

Projection.rebuild(stream) -> projection_version
Projection.snapshot(scope) -> control_center_snapshot
```

## 7. Command 与 Event 协议

### 7.1 AgentCommand

```ts
type AgentCommand<T> = {
  schemaVersion: '1.0'
  commandId: string
  commandType: string
  idempotencyKey: string
  tenantId: string
  workspaceId: string
  actor: {
    type: 'user' | 'service' | 'agent'
    id: string
    roles: string[]
  }
  target: {
    kind: string
    id: string
    expectedRevision?: number
  }
  deadline?: string
  correlationId: string
  data: T
}
```

命令结果必须区分：

- accepted
- rejected
- waiting_approval
- completed
- failed
- cancelled

### 7.2 DomainEvent Envelope

```ts
type DomainEvent<T> = {
  schemaVersion: '1.0'
  eventId: string
  eventType: string
  source: {
    system: string
    instanceId: string
  }
  tenantId: string
  workspaceId: string
  aggregate: {
    kind: string
    id: string
    revision: number
  }
  sequence: number
  occurredAt: string
  ingestedAt: string
  correlationId: string
  causationId?: string
  traceId?: string
  classification: 'public' | 'internal' | 'confidential' | 'secret'
  actor?: {
    type: 'user' | 'service' | 'agent'
    id: string
  }
  data: T
}
```

相关 payload 应显式包含 `runId`、`stepRunId`、`attempt`、`policyDecisionId`、`approvalId` 或 `toolReceiptId`。

### 7.3 投递语义

- 数据库事务同时写业务状态和 Outbox。
- 发布语义为 at-least-once。
- 消费者通过 eventId、aggregate revision 和 Inbox checkpoint 去重。
- 不宣称 exactly-once；通过幂等副作用实现业务等价。
- SSE/WebSocket 只是 UI 传输 Adapter，不是事件事实源。
- Projection 必须支持从 EventLog 全量重建。

### 7.4 UI 数据可信度

所有 Snapshot 必须携带：

```text
source_status: live | stale | unavailable | simulated
observed_at
projected_at
source_errors
```

后端失败时禁止把 mock 数据展示为真实 idle 状态。

## 8. 安全模型

### 8.1 部署 Profile 隔离

Enterprise 和 Personal 不仅是请求参数，应支持不同部署 Profile：

| Profile | 默认加载能力 |
|---|---|
| Enterprise | 无 shell、无 desktop、严格浏览器网络策略、高风险审批 |
| Personal | 可选本地 shell/desktop，但必须限定工作区并保留审批 |
| Development | Mock Adapter、测试账户、显式 debug 标记 |

不得允许普通请求通过 `X-Edition` 改变安全能力集。

### 8.2 Secret 分域

- Auth Token、Capability Grant、Webhook、数据加密使用不同密钥。
- 支持 key_id、轮换和撤销。
- 每个进程只获得自身需要的 Secret。
- 不共享包含全部 Provider Key 的 `.env`。
- 日志、事件和错误信息执行字段级脱敏。

### 8.3 特权 Adapter 隔离

Shell、PTY、桌面、插件、浏览器下载运行在独立进程或容器，并限制：

- 文件系统根目录
- 网络目标
- CPU 和内存
- 执行时长
- 输出大小
- 子进程数量
- 环境变量
- 可加载模块

插件 Manifest 的 permissions 必须成为运行时强制约束，而不是展示字段。

### 8.4 浏览器安全

- 每次请求、重定向、点击导航都重新检查目标。
- 阻止 localhost、私网、云元数据地址和 DNS rebinding。
- 表单提交、消息发送、支付、上传和下载按真实副作用重新评估风险。
- `browser.click` 不得永久标记为固定 low risk。

### 8.5 审计完整性

- 每个副作用记录 actor、decision、grant、tool receipt 和资源范围。
- 审计记录写入独立保留策略。
- 如需声明 tamper-evident，必须加入 hash chain、签名或外部不可变存储。

## 9. 当前阻断性修复清单

### 9.1 myself-agent P0

1. 修复 `POST /tasks/{id}/execute` 正常路径引用未定义 `task`。
2. 将创建与执行分离，执行既有 task_id，禁止 Orchestrator 二次创建 Task。
3. Policy 改成 DENY/WAIT_APPROVAL/GRANT 三态。
4. WAIT_APPROVAL 时不签 Capability Grant。
5. Approval resolve 后持久化 Resume Command。
6. API、CLI、Cron、Chat、SubAgent、插件全部收敛到 ExecutionControl。
7. 删除 SubAgent 和 CLI 的直接 Tool.execute 旁路。
8. Task、Memory、Skill、Audit、Export、WebSocket、GraphQL 增加租户和对象级过滤。
9. 请求体移除可伪造 user_id/tenant_id。
10. 修复生产 Cron 未启动、调度状态不持久的问题。
11. 修复 PostgreSQL 下的 SQLite 专用查询和备份行为。
12. Docker 镜像按 Profile 安装 Browser/Docx/Redis 等实际依赖。
13. CI 加入前端 build/test、PostgreSQL、Redis、Docker 和安全测试。
14. 修复 lint 基线后再允许新增功能。

### 9.2 agent_tianshu P0

这些修复只用于维持迁移期可用性，不代表要长期保留独立服务：

1. 修复 `/api/reports` 缺少 query 参数。
2. 修复 agents/templates 双重 send_json。
3. 替换所有 `shell=True` 字符串命令。
4. 修复写死的调度脚本路径。
5. JSON 文件写入增加锁或迁移到临时 SQLite。
6. 明确 demo、manual、adapter 三种运行模式。
7. 提取 WorkflowDefinition 后冻结旧状态机开发。

不把“迁移到 FastAPI”作为必做目标。只有旧服务仍需长期对外提供 OpenAPI、鉴权或实时通信时才迁移框架。

### 9.3 unified-admin P0

1. 以 OpenAPI 生成 `myself-agent` 客户端，删除错误的手写模型。
2. 明确所有 mock/simulated 数据，不得伪装为在线状态。
3. Express 删除任务、审批、队列等业务写模型。
4. 高风险写操作只能提交 AgentCommand。
5. 拆出只读 Query、Command Gateway 和 Privileged Adapter。
6. 将 4,000+ 行单文件按行为 Module 拆分，而不是只按 routes/services 分层。
7. 清理外层 gitlink、缺失 `.gitmodules` 和未提交改动。

### 9.4 ClawLibrary P0

1. 作为 workspace package 或固定版本依赖接入，不复制源码。
2. 只消费 Projection 读模型。
3. 保留代码 MIT 来源和 Attribution。
4. 商业发布前替换 CC BY-NC-SA 视觉资产或取得单独授权。

## 10. 推荐仓库结构

建议迁移后的目标结构：

```text
agent-control-center/
  apps/
    control-api/           # myself-agent 核心控制面
    operator-web/          # unified-admin 前端
    adapter-host/          # OpenClaw/Hermes 协议代理
    privileged-worker/     # shell/desktop/pty/browser/plugin 隔离进程
  packages/
    contracts/             # Command/Event/Read Model schema
    execution-control/     # 唯一执行 interface 与实现
    policy/                # Policy + Approval + Grant
    workflow/              # WorkflowDefinition/Runtime
    worker-broker/         # Lease/Heartbeat/Retry
    event-log/             # Outbox/Inbox/EventStore
    projection/            # Snapshot/Timeline/WorldDelta
    provider-adapters/
      openclaw/
      hermes/
      tianshu/
    visualization/         # ClawLibrary package
  migrations/
  docs/
    adr/
    threat-model.md
    domain-language.md
    migration-plan.md
    operations.md
  tests/
    contract/
    integration/
    security/
    failure-injection/
    e2e/
```

不要预先创建 `shared-auth`、`shared-config`、`shared-ui` 等无明确所有权的杂物包。只有出现两个真实 Adapter 或多处重复不变量时才建立新的 seam。

## 11. 迁移阶段与退出条件

## Phase 0：冻结、盘点与定界

目标：确定唯一主线和当前可信基线。

任务：

- 冻结新增功能。
- 记录 ADR：唯一任务所有者、目标仓库、前端选择、数据源选择。
- 建立领域词汇表和状态映射。
- 盘点全部数据库、JSON、备份、截图、`.env` 和上游来源。
- 记录每个快照的来源 commit、许可证和本地补丁。
- 建立唯一版本源、依赖锁文件和 CI 基线。
- 将 `agent_contorl` 标记为只读归档。

退出条件：

- 部署拓扑只有一个 Task 写模型和一个 Orchestrator。
- 每个资产都有保留、迁移或退役决定。
- 主分支 lint、基础测试和构建可重复执行。
- 版本、镜像标签、健康响应和发布说明来自同一来源。

## Phase 1：正确性与安全闭环

目标：完成一个可信的低风险/高风险垂直切片。

任务：

- 修复现有 Task 创建与执行身份问题。
- 引入 ActorScope 和 Repository 级租户过滤。
- 所有入口收敛到 ExecutionControl。
- 实现三态 Policy。
- 完成 WAIT_APPROVAL -> resolve -> resume。
- Approval 和 Grant 绑定参数哈希、策略版本和资源范围。
- 增加命令注入、路径穿越、跨租户和审批绕过测试。

退出条件：

- 高风险步骤在批准前执行次数为 0。
- CLI、SubAgent、插件和 Workflow 无法绕过 Policy。
- 跨租户读取和写入成功次数为 0。
- 每个副作用可追溯到 command、decision、approval/grant 和 receipt。

## Phase 2：持久执行与故障恢复

目标：任务不依赖 HTTP 请求或单进程内存存活。

任务：

- PostgreSQL 作为生产事实源。
- 业务写入与 Outbox 同事务提交。
- Worker Lease、heartbeat、超时回收和 CAS 完成。
- 每个外部副作用使用 idempotency key。
- 增加 retry、dead-letter、checkpoint 和 orphan recovery。
- Redis 只用于唤醒、缓存和短期协调。

退出条件：

- 在规划、审批、工具执行和结果提交时杀进程均可恢复。
- Redis 中断不丢任务。
- 重复消息不产生重复外部副作用。
- nginx/HTTP 请求超时不影响后台 Run。

## Phase 3：Command/Event 契约与 Projection

目标：为 UI 和外部系统提供稳定 seam。

任务：

- 固化 AgentCommand、DomainEvent、AuditRecord 和 Snapshot schema。
- 实现 Outbox publisher、Inbox dedupe 和事件重放。
- 实现 AgentSnapshot、TaskTimeline、ApprovalQueue、WorldDelta。
- 建立 OpenClaw/Hermes/Tianshu Adapter 契约测试。
- 标记数据 freshness 和 source status。

退出条件：

- 重复、乱序和断线重连测试通过。
- EventLog 重放生成相同 Snapshot。
- UI 不需要理解来源系统内部状态枚举。
- Adapter 替换不会要求修改 Projection 或 UI 业务逻辑。

## Phase 4：Operator Console 收敛

目标：建立唯一、可信的操作者界面。

任务：

- 以 unified-admin 为唯一前端。
- 从 OpenAPI/Schema 生成客户端。
- 首先接入只读 Dashboard、Task Timeline、Approval Queue 和 Source Health。
- 所有写操作改为提交 AgentCommand。
- Express BFF 保持无状态，只负责协议代理和会话终止。
- 禁止失败时静默返回 mock 在线数据。

退出条件：

- 所有写操作最终进入 ExecutionControl。
- 控制台能够明确显示 live/stale/unavailable/simulated。
- 后端全部离线时 UI 仍可显示最后已知状态，但不能显示为实时。
- 端到端覆盖提交、等待审批、批准恢复、取消和 Worker 离线。

## Phase 5：Workflow 与可视化世界

目标：让天枢和 ClawLibrary 成为控制面的扩展，而不是第二控制面。

任务：

- 将天枢角色、审核门、路由和停滞策略转换成 WorkflowDefinition。
- WorkflowRuntime 根据 DomainEvent 产生下一步 WorkflowAction。
- ClawLibrary 消费 WorldDelta 和 Snapshot。
- 建立房间、角色和资源分区到领域实体的稳定映射。
- 支持 Admin 详情页与 Museum 定位互跳。

退出条件：

- 同一 Task 只有一个规范 task_id。
- WorkflowPhase 不修改 TaskLifecycle 的所有权规则。
- Workflow 重放得到相同阶段历史。
- ClawLibrary 不直接调用来源系统写接口。

## Phase 6：Skill、插件与特权能力

目标：在可信基础上恢复高级能力。

任务：

- SkillVersion 不可变并记录真实使用版本。
- 建立 SkillEvaluation、对照基线和最小样本量。
- 插件迁移到独立进程或容器。
- Shell、桌面、PTY、浏览器下载按 Profile 启用。
- 增加资源、网络和 Secret 隔离测试。

退出条件：

- Skill 晋升可解释、可复现、可回滚。
- 恶意插件无法访问宿主未授权文件、网络或凭据。
- 特权动作全部具有审批和审计证据。

## Phase 7：切换与退役

目标：安全结束双系统阶段。

任务：

- 旧系统先停止新增功能。
- 双读比对新旧 Snapshot 和任务状态。
- 迁移 source ID 到 external_reference。
- 停止旧写入后观察稳定期。
- 执行回滚、备份恢复和灾难恢复演练。
- 归档旧 Orchestrator、旧队列和重复前端。

退出条件：

- 连续观察期无状态漂移。
- 数据总数、状态分布和关键审计记录对账通过。
- 回滚演练满足 RTO/RPO。
- 生产部署中不存在第二个任务写模型。

## 12. 数据迁移策略

当前存在多个数据源：

- `myself-agent` SQLite/PostgreSQL/Alembic 数据模型
- `agent_tianshu/data/*.json`
- 天枢 memory SQLite
- `more_agents/backend` 数据库
- unified-admin `wizard.db`
- 多份本地备份和运行时输出

迁移原则：

1. 不直接复制数据库文件作为最终迁移。
2. 为外部实体建立 `external_reference(source_system, source_id, canonical_id)`。
3. 先导入只读历史，再切换新写入。
4. 保留原始时间戳、来源和导入批次。
5. 对 Task、Agent、Skill、Memory 和 Artifact 分别定义映射规则。
6. 对无法确定语义的数据标记 `unresolved`，不猜测转换。
7. 运行时备份、截图、node_modules、dist 和本地 Secret 不进入主仓。

## 13. 测试与质量门禁

### 13.1 必须覆盖的测试层

- Module interface 行为测试
- Adapter 契约测试
- PostgreSQL/Redis 集成测试
- Command/Event schema 兼容性测试
- 审批暂停与恢复 E2E
- 跨租户与对象级授权测试
- 重复、乱序、延迟事件测试
- 进程崩溃和网络中断故障注入
- 插件、Shell、文件、浏览器安全测试
- 前端 build、typecheck、unit 和关键 Playwright 流程
- Docker 镜像启动和迁移测试

### 13.2 核心指标

| 指标 | 目标 |
|---|---|
| 批准前高风险执行次数 | 0 |
| 跨租户成功访问次数 | 0 |
| 重复外部副作用次数 | 0 |
| 审计缺失率 | 0 |
| Event Projection 延迟 P95 | 按部署目标定义阈值 |
| Task Queue 等待 P95 | 按任务等级定义阈值 |
| Lease 超时回收时间 | 小于设定恢复窗口 |
| 卡死 Run 数 | 0 或自动进入人工队列 |
| Snapshot 重放一致率 | 100% |
| Skill 相对质量提升 | 高于批准门槛且有最小样本量 |

## 14. 发布与仓库治理

- 建立真实的增量 Git 历史。
- 每个迁移阶段使用独立、可回滚提交。
- 建立签名或受保护的版本标签。
- Python 使用锁文件；Node 使用 `npm ci` 和提交的 lockfile。
- 生成 SBOM，并记录上游包、许可证和本地修改。
- 版本由一个源生成 pyproject、应用配置、镜像标签和健康响应。
- CI 不允许手工维护测试数量作为质量证据。
- 旧仓库进入只读后禁止继续双线开发。

## 15. 主要风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 继续维护多套 Orchestrator | 状态竞争、重复执行 | 唯一写模型 ADR + 部署检查 |
| UI/BFF 直接执行高权限操作 | 绕过 Policy | Command Gateway + Privileged Adapter |
| 事件乱序或重复 | 错误 Snapshot | sequence + revision + Inbox 去重 |
| Worker 崩溃 | 任务永久卡住 | Lease + heartbeat + orphan recovery |
| 审批后参数变化 | 越权执行 | 绑定规范参数哈希与策略版本 |
| 插件主进程执行 | 宿主失陷 | 独立进程/容器 + 权限 RPC |
| 多租户数据泄漏 | 企业级安全事故 | ActorScope + Repository 强制过滤 |
| mock 数据伪装在线 | 操作者误判 | source_status + freshness 强制显示 |
| 上游复制漂移 | 无法升级和审计 | 固定来源版本 + Adapter/Package 接入 |
| ClawLibrary 资产许可证 | 商业发布受阻 | 替换资产或取得授权 |

## 16. 最终产品形态

用户打开一个控制中心，可以可靠地看到并操作：

- 哪些 AgentProfile 已配置，哪些 Worker 当前在线。
- Task 当前生命周期、Workflow 阶段和具体 Run/StepRun。
- 哪个步骤等待审批，审批绑定了什么工具、参数和资源范围。
- 哪个 Worker 持有 Lease，最后心跳和恢复状态是什么。
- 调用了哪些工具，产生了哪些 Artifact、Memory 和 SkillVersion。
- 数据是实时、过期、不可用还是模拟。
- OpenClaw、Hermes、天枢和本地 Agent 的来源状态。
- 所有高风险命令的发起者、Policy Decision、Approval、Grant 和执行结果。
- 任务为什么卡住，以及系统是否正在自动恢复。

最终系统的关键不是把多个项目放进同一个页面，而是：

> 让所有 Agent 行为只有一个可信执行入口，让所有状态都有唯一所有者，让所有副作用都可授权、可审计、可恢复。

