# 数据流图 v1

**生成日期**: 2026-07-22
**适用版本**: spec v1.1, P0 完成
**依据**: spec §4.1 逻辑拓扑 + §4.3 核心执行契约

## 1. 顶层数据流（DFD Level 0）

```
┌──────────┐     ①Command      ┌─────────────────┐     ⑥ToolReceipt    ┌──────────────┐
│  用户    │ ─────────────────→ │                 │ ←─────────────────  │  Sandbox     │
│ (Operator)│                    │  Control API    │                     │  Runner      │
└──────────┘                    │  (FastAPI)      │                     └──────────────┘
     ↑                          │                 │                            ↑
     │ ⑦Projection              │  ┌───────────┐  │ ⑤EffectRecord              │
     │ (read-only)              │  │ Orchestrator │ │                            │
     │                          │  │ (唯一写者) │  │ ④CapabilityGrant           │
     │                          │  └─────┬─────┘  │                            │
     │                          │        │        │                            ↓
     │                          │        ↓        │     ┌──────────────────────┐
     │                          │  ┌───────────┐  │     │  Tool Gateway        │
     │                          │  │  Policy   │  │────→│  (唯一 Tool 调用入口)│
     │                          │  │  Engine   │  │     └──────────────────────┘
     │                          │  └─────┬─────┘  │
     │                          │        │        │
     │                          │        ↓        │
     │                          │  ┌───────────┐  │
     │                          │  │ Approval  │  │  ③ApprovalRequest
     │                          │  │  Gate     │  │  (high-risk only)
     │                          │  └───────────┘  │
     │                          │                 │
     │                          │  ┌───────────┐  │
     └──────────────────────────│→ │  Audit    │  │
                                │  │  Store    │  │
                                │  └───────────┘  │
                                └─────────────────┘
                                         │
                                         ↓ ②PlanVersion
                                 ┌─────────────────┐
                                 │   DB (SQLite/PG)│
                                 │   + Audit (WORM)│
                                 └─────────────────┘
```

## 2. 核心执行契约数据流（spec §4.3）

每个副作用的完整链路（P0.1 已定义全部 schema）：

```
①Command (submit/execute/resume/cancel)
    │  携带 actor_scope（不可伪造身份）
    ↓
②PlanVersion (immutable, SHA-256 digest)
    │
    ↓
③PolicyDecision (DENY / WAIT_APPROVAL / GRANT)
    │
    ├─→ DENY → 终止，审计
    ├─→ WAIT_APPROVAL → ③a ApprovalRequest (expires_at)
    │                    ↓ (人工 resolve)
    │                   ③b ApprovalResolution
    │                    ↓
    │                   ③c 重新 evaluate PolicyDecision
    └─→ GRANT → ④CapabilityGrant (opaque handle, digest-only)
                    │
                    ↓
                ⑤Lease (worker claim, fencing_token)
                    │
                    ↓
                ⑥EffectRecord PREPARED (副作用意图持久化)
                    │
                    ↓
                ⑦ToolGateway.execute (验证 Grant/nonce/args_hash)
                    │
                    ↓
                ⑧ToolReceipt (succeeded/failed/unknown)
                    │
                    ↓
                ⑨EffectRecord CONFIRMED | FAILED | UNKNOWN_OUTCOME
                    │
                    ↓
                ⑩AuditRecord (hash-chained, append-only)
```

## 3. 信任边界穿越（DFD Level 1）

### 3.1 用户 → Desktop Shell（边界 1）

| 数据 | 方向 | 分类 | 控制 |
|---|---|---|---|
| goal/args | 入 | confidential | 参数化，不经 shell |
| Projection 快照 | 出 | internal | source_status 标注 |

### 3.2 Shell → Control API（边界 2：IPC）

| 数据 | 方向 | 分类 | 控制 |
|---|---|---|---|
| Command | 入 | internal | Named Pipe SID ACL（P1） |
| WS 推送 | 出 | internal | nonce + 协议版本 |

### 3.3 Control API → DB（边界 3）

| 数据 | 方向 | 分类 | 控制 |
|---|---|---|---|
| Task/Run/StepRun 写 | 入 | confidential | tenant_id 强制过滤（P1） |
| Audit 写 | 入 | secret | append-only + REVOKE UPDATE（P2） |

### 3.4 Control API → LLM Gateway（边界 4：外网）

| 数据 | 方向 | 分类 | 控制 |
|---|---|---|---|
| prompt + context | 出 | confidential | 数据发送范围可配（P3） |
| LLM 响应 | 入 | llm_generated | ContentProvenance 标注 |

### 3.5 ToolGateway → Sandbox Runner（边界 5：特权隔离）

| 数据 | 方向 | 分类 | 控制 |
|---|---|---|---|
| executable + args[] | 入 | confidential | 参数化，Job Object（P2） |
| stdout/stderr/screenshot | 出 | confidential | 输出大小限制 + 分类 |

## 4. 数据存储清单

| 存储 | 内容 | 分类 | 加密 | 备份 |
|---|---|---|---|---|
| SQLite/PG | Task/Run/StepRun/Approval/Grant/Lease/Effect/Receipt | confidential | WAL（P1 字段级加密） | zcode backup |
| Audit 表 | AuditRecord + hash chain | secret | append-only | 独立备份 |
| SecretStore | API Key / token | secret | OS-native（DPAPI/Keychain） | 不备份 |
| 文件系统 | Workspace 产物 | internal | — | 用户负责 |
| Langfuse | Trace + LLM 调用 | confidential | — | 自治 |

## 5. 数据生命周期

| 数据类型 | 保留期 | 处置 |
|---|---|---|
| Task/Run（已完成） | 永久（或用户配置） | archive |
| AuditRecord | ≥1 年（spec §11） | append-only，不删 |
| LLM 调用记录 | 默认不保存完整内容（spec §11） | 调试模式显式限时 |
| 截图 | 会话级 | 会话结束清除 |
| Secret | 直到 rotate | rotate 时旧 key 失效 |
| 日志 | 7 天轮转 | 自动覆盖 |
