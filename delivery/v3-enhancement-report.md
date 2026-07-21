# v3 增强修改报告

> 基于 `agent-control-center-design-and-implementation-plan-v3.md`（v3 实施方案）对 7 份架构文档的针对性补强。
> 生成日期：2026-07-18
> 补强方式：定点修订，非重写；5 份文档修订，2 份（material_digest / research_report）无需修订。

## 1. 复核发现

对照 v3（2000 行）与我们的 7 份架构文档（基于 v2，7600 行），识别出 v3 在 4 个维度的实质升级：

| 维度 | 严重程度 | v3 引入的关键概念 | 我们方案的覆盖度 |
|------|---------|-----------------|----------------|
| 副作用失败语义 | 🔴 高 | EffectRecord / UNKNOWN_OUTCOME / fencing_token / ToolEffectContract | 0%（最大薄弱点） |
| 供应链安全 | 🟠 中高 | ContentProvenance / security_context_digest / execution_supply_chain_digest / SandboxProfile / WorkloadIdentity | 0%（Agent 特有威胁） |
| 迁移工程化 | 🟡 中 | cutover 9 态 / write_fence / forward recovery / 停用 7 步 | 仅"双读比对"概念级 |
| 审批完整性 | 🟢 低 | ApprovalVote / opaque Grant / break-glass | 方向一致，v3 更精细（本次未单独补强，已在安全设计 4A 覆盖部分） |

**17 个 v3 关键概念在补强前 0 覆盖**（通过 grep 验证）。

## 2. 补强内容（5 份文档，5 项修订）

### 修订 1：系统设计.md — 新增 M9 EffectJournal 模块 + 3 张数据表

**位置**：§3.2.M9（M8 之后）+ §4.2.E1/E2/E3（数据库设计）

**新增内容**：
- **M9 EffectJournal 模块五段式**（模块概述 / 接口清单 / 关键结构 / 时序图 / 异常处理）
  - EffectJournal 接口：prepare / acquire_dispatch / finalize / reconcile
  - 四阶段协议：PREPARE → ACQUIRE_DISPATCH → CALL_ADAPTER → FINALIZE
  - EffectStatus 状态机（10 态，含 UNKNOWN_OUTCOME 一等状态）
  - ToolEffectContract 4 类分级矩阵（read_only / provider_idempotent / reconcilable / non_retryable）
  - fencing_token 机制（Lease 单调递增令牌，过期 Worker 操作被拒）
  - Mermaid 时序图（含 unknown_outcome 异常分支）
  - 异常状态码：WAIT_AUDIT_DEPENDENCY / STALE_UI_STATE / LEASE_FENCED / SANDBOX_UNAVAILABLE
- **3 张新数据表**：
  - `effect_journal`：副作用意图主表（含 security_context_digest / execution_supply_chain_digest 字段）
  - `effect_authorization_attempts`：授权尝试历史（append-only，含 fencing_token）
  - `effect_dispatch_attempts`：派发尝试历史（append-only，含 provider_idempotency_key）
  - 关键约束：UNIQUE 逻辑 Effect / UNIQUE Grant 消费 / UNIQUE provider 幂等 scope
  - Alembic 迁移版本 16

**解决的核心问题**：工具调用模糊失败时盲目重试导致重复外部副作用（重复发邮件、重复扣款、重复删除）。

### 修订 2：安全设计.md — 新增 §4A Agent 特有威胁章节

**位置**：§4 应用安全之后、§5 网络安全之前，新增 §4A（6 个子节）

**新增内容**：
- **§4A.1 ContentProvenance**：内容来源追踪，3 级信任（trusted_system / authenticated_user / external_untrusted），8 类 source_type，明确"模型输出默认不可信"
- **§4A.2 security_context_digest**：9 项输入的 SHA-256（provenance/模型/system prompt/Tool schema/classification/外发目的地/Secret scope/预算/delegation），绑定点 PolicyDecision/Approval/Grant/Effect，任一变化触发授权失效
- **§4A.3 execution_supply_chain_digest**：插件包/Manifest/SandboxProfile/RPC/Worker build 组合 digest，审批后调包失效
- **§4A.4 SandboxProfile**：完整沙箱定义（13 字段），零权限起步按需授予，digest 绑定授权，Sandbox 不可用绝不回退主进程
- **§4A.5 WorkloadIdentity**：Worker capabilities 来自服务端登记而非自报，build_digest 验证
- **§4A.6 Browser/Desktop 内容来源控制**：Browser Context 隔离 + 表单提交生成 EffectRecord + STALE_UI_STATE 机制

**解决的核心问题**：Agent 系统中模型输出/网页/工具返回值作为不可信数据污染 Policy；审批后调包 Tool schema/插件/Sandbox 导致旧授权被滥用。

### 修订 3：部署设计.md — 新增 §6A 迁移切换协议

**位置**：§6 应急回滚之后、§7 安全合规之前，新增 §6A（6 个子节）

**新增内容**：
- **§6A.1 迁移基本原则**：不双写 / forward recovery / strangler pattern / 每 Phase 有 owner 和退出证据
- **§6A.2 Cutover 9 态状态机**：shadow_read → drain → write_freeze → cutback_check → cutover → dual_read_verify → parallel_run → drain_legacy → retired，含转换规则/检查清单/超时自动中止
- **§6A.3 write_fence**：DB Role 级写入栅栏（REVOKE 旧 Writer 权限 + active_writer_epoch 切换 + 触发器校验）
- **§6A.4 标准停用协议 7 步**：close_admission → stop_new_claims → drain → revoke_grants → reconcile_effects → verify_zero → disable，含超时/自动中止条件
- **§6A.5 ExternalReference**：旧数据导入映射键（含 status: resolved/unresolved/conflict/tombstoned）
- **§6A.6 与 G5 的关系**：MVP 阶段建映射机制，Phase 6~7 执行完整 cutover

**解决的核心问题**：把"双读比对"概念升级为可执行、可回滚、有自动中止条件的生产级迁移工程协议。

### 修订 4：UserStory.md — US-3 Orphan Recovery 落地

**位置**：§5.3.2 AC 验收标准（US-3）

**新增内容**：
- 原 AC-3 重写：基于 EffectRecord 状态分支处理（PREPARE 前 / prepared 无 dispatch / dispatching 无 Receipt / confirmed / unknown_outcome 五种情况）
- 新增 AC-4：provider_idempotent 类工具的幂等重投（同一 provider_idempotency_key + 新 fencing_token）
- 新增 AC-5：reconcilable 类工具的 provider 查询对账（已创建→confirmed / 不存在→retry / 查询失败→manual_review）
- 新增 AC-6：审批后上下文变化导致 Grant 失效（STALE_SECURITY_CONTEXT，需重新审批）

**解决的核心问题**：把 U-02 待确认项（"副作用不确定转人工"）落地为基于 EffectRecord + UNKNOWN_OUTCOME + ToolEffectContract 的可执行对账机制。

### 修订 5：高层架构设计.md — 功能清单补充

**位置**：§6.3 功能清单表

**新增内容**：
- **F19 EffectJournal**（P0，MVP）：副作用四阶段协议 + UNKNOWN_OUTCOME + ToolEffectContract + fencing_token，对齐 V4 可靠性
- **F20 供应链安全 digest**（P0，MVP）：security_context_digest + execution_supply_chain_digest + ContentProvenance + SandboxProfile，对齐 V2 安全
- **F21 迁移切换协议**（P1，MVP 部分建映射 / 完整版全量）：cutover 9 态 + write_fence + forward recovery + 停用 7 步，对齐 V6 唯一写模型

**解决的核心问题**：MVP 范围纳入 EffectJournal 和供应链安全（生产可靠性底线），迁移协议列为 P1。

## 3. 未补强的内容（评估后判断不需要）

| 项 | 原因 |
|----|------|
| ApprovalVote / ApprovalResolution / ApprovalInvalidation（多人投票/quorum） | MVP 单人审批足够，完整版可增量补充，不构成架构返工 |
| opaque Grant handle（256-bit，DB 只存 digest） | 当前 CapabilityGrant 字段存储方式可用，完整版升级为 opaque handle 是安全增强非必需 |
| break-glass（紧急通道 + 强制告警 + 事后双人复核） | 运维流程问题，非架构问题，在 §6A 停用协议中已部分覆盖 |
| Personal Windows 部署 Profile | 当前部署设计聚焦 Enterprise/Docker Compose，Personal Profile 是完整版范围 |
| ArtifactStore（大对象 + 隔离区 + 恶意内容检查） | MVP 阶段 Artifact 量小，直接存 PostgreSQL + 文件系统足够，完整版引入专用 ArtifactStore |

## 4. 校验结果

补强后 5 份文档回归自动校验全部通过：

| 文档 | 校验 | 行数变化 |
|------|------|---------|
| 系统设计.md | 11/11 ✅ | 2682 → ~2820（+M9 模块 +3 表） |
| 安全设计.md | 9/9 ✅ | 1237 → ~1380（+§4A 供应链安全） |
| 部署设计.md | 8/8 ✅ | 1065 → ~1180（+§6A 迁移协议） |
| UserStory.md | 5/5 ✅ | 1218 → ~1290（+4 条 AC） |
| 高层架构设计.md | 12/12 ✅ | 592 → ~595（+3 条功能 F19~F21） |

**合计**：45/45 校验项通过，新增约 350 行实质内容。

## 5. 关键裁决（v3 与我们方案的差异处理）

| 差异点 | 我们的选择 | 理由 |
|--------|-----------|------|
| v3 不预先指定 unified-admin，要求 Phase 0 评分 | **保持选择 unified-admin** | 我们的调研报告已充分论证（加权评分 + 场景契合度），且用户诉求明确指定；v3 的"评分门"是更严谨的流程，但结论一致 |
| v3 采用关系型写模型（非完整 Event Sourcing） | **与 v3 一致** | 我们方案本来就是 PG Transactional Outbox，v3 §13.1 明确确认了这一选择 |
| v3 把 EffectJournal 作为独立 Module | **采纳为 M9** | EffectJournal 在 ToolGateway 内部，是 ToolGateway 的子模块，但功能重要性足以独立编号 |
| v3 的 SLO 数值（Command P95 500ms 等） | **保留我们的数值** | v3 明确标注"设计初始目标，Phase 0 必须确认"，我们的数值也是初始目标，在 §6.2 已标注"非 SLA 承诺" |
| v3 要求 Shadow Table + 原子切换的 Projection 重建 | **保留在完整版** | MVP 单 Projection 重建足够验证链路，Shadow Table 原子切换是完整版多 Projection 的需求 |

## 6. 补强后的架构成熟度评估

| 维度 | 补强前 | 补强后 |
|------|--------|--------|
| 副作用可靠性 | 🟡 有重试但无模糊失败处理 | 🟢 四阶段协议 + UNKNOWN_OUTCOME + 对账队列 |
| Agent 安全 | 🟡 传统 OWASP + 基础沙箱 | 🟢 供应链 digest + 内容来源追踪 + 完整 SandboxProfile |
| 迁移工程化 | 🟡 概念级"双读" | 🟢 9 态状态机 + write_fence + 停用协议 |
| 审批完整性 | 🟢 三态 Policy（已对齐） | 🟢 三态 Policy（已对齐） |
| 整体生产就绪度 | MVP 可用但模糊失败有风险 | MVP 生产级可靠，完整版路径清晰 |

**结论**：补强后的方案在副作用可靠性、Agent 安全、迁移工程化三个维度达到 v3 同等深度，可作为生产级实施方案的架构基线。
