# Zcode Desktop Agent — 管理员指南

> 版本: P3
> 更新: 2026-08-03
> 适用: Self-hosted / Enterprise Profile 管理员

## 1. 部署架构

```
┌─────────────────────────────────────────┐
│  Desktop Agent (Tauri 2 + Vue)          │
│  ├── WebView2 (前端)                     │
│  └── Python Sidecar (Nuitka 打包)        │
│      ├── control-core (FastAPI)          │
│      ├── SQLite WAL (本地数据库)          │
│      └── Worker Pool (文件/Shell/浏览器)   │
└─────────────────────────────────────────┘
         │ (Hybrid Profile only)
         ▼
┌─────────────────────────────────────────┐
│  Self-hosted Server (可选)               │
│  ├── control-core API                    │
│  ├── PostgreSQL (多租户)                  │
│  └── Redis (nonce store / cache)         │
└─────────────────────────────────────────┘
```

## 2. 配置

### 2.1 核心配置文件

| 文件 | 用途 | 关键项 |
|---|---|---|
| `configs/app.yaml` | 应用主配置 | database.url, secret_key (生产从环境变量) |
| `configs/tools.yaml` | 工具注册 + 风险等级 | enabled, risk_level, edition |
| `configs/policy.yaml` | 策略规则 | forbidden_tools, require_approval_risk_levels |
| `configs/cache.yaml` | 缓存后端 | backend=redis (多进程) |

### 2.2 SECRET_KEY 配置

**生产环境必须**:
```bash
export SECRET_KEY="<your-256-bit-secret>"
```

优先级: 环境变量 > app.yaml > 默认值(change-me)。app.yaml 中 `secret_key: null`。

### 2.3 多租户隔离

- tenant_id 在所有 DB 查询中强制 (P1.2)
- ActorScope 从 JWT 派生 tenant (P1.1)
- 查询不接受客户端传入的 tenant_id (防伪造)

## 3. 执行契约 (§4.3)

每个产生副作用的操作经过完整安全链:

```
PolicyDecision (DENY/WAIT_APPROVAL/GRANT)
  → ApprovalRequest (如果 WAIT_APPROVAL)
  → CapabilityGrant (opaque 256-bit handle, DB 存 digest)
  → Lease (fencing_token 单调递增)
  → EffectRecord (PREPARED → DISPATCHING → 终态)
  → ToolGateway (唯一入口,验证 Grant+Lease+fencing)
  → ToolReceipt
  → EffectRecord (CONFIRMED/FAILED/UNKNOWN_OUTCOME)
```

### 安全不变量

| 不变量 | 实现 |
|---|---|
| 批准前高风险执行 = 0 | policy_engine withhold token (P0.5) |
| Grant nonce 二次消费 = 0 | 原子 conditional UPDATE consume() |
| stale fencing token = 0 | LeaseManager monotonic + is_valid() |
| 路径逃逸 = 0 | path_safety.resolve_path() |
| 恶意下载 = 0 | quarantine MIME + size + content check |
| 自审 = 0 | ApprovalService SelfApprovalError |

## 4. 监控

### 4.1 健康检查

```
GET /api/v1/health/ready     就绪检查
GET /api/v1/metrics           Prometheus 指标
```

### 4.2 关键指标

| 指标 | 含义 | 告警阈值 |
|---|---|---|
| task_execution_duration_seconds | 任务执行时长 | P99 > 300s |
| effect_unknown_outcome_count | 未知结果 Effect 数 | > 0 需人工对账 |
| grant_consume_failure_count | Grant 消费失败 | 突增可能 nonce 重放攻击 |
| lease_expiry_count | Lease 过期数 | 突增可能 Worker 崩溃 |

## 5. 审批管理

### 5.1 查看待审批

```
GET /api/v1/gateway-approvals?status=pending
```

### 5.2 Quorum 配置

- 默认 quorum=1 (一个非发起人批准即可)
- 可按工具风险等级配置更高 quorum
- Enterprise 可配置多角色审批

### 5.3 审批失效

以下情况旧审批自动失效:
- Policy digest 变更 (策略规则改变)
- Args hash 变更 (参数改变)
- Security context digest 变更

## 6. 数据管理

### 6.1 备份策略

- 每日自动备份 (cron)
- 保留策略: 最近 7 天每日 + 最近 4 周每周
- 备份位置: `data/backups/`
- 验证: 每次备份后自动 checksum + integrity_check

### 6.2 数据导出

```
GET /api/v1/export?format=json&tenant=<id>
```

导出不包含 Secret (API Key 在 OS 密钥环,不在导出中)。

## 7. 故障排查

### 7.1 启动失败

| 症状 | 原因 | 解决 |
|---|---|---|
| SECRET_KEY default warning | 未设置环境变量 | `export SECRET_KEY=...` |
| Alembic migration error | DB 版本不匹配 | `alembic upgrade head` |
| Port already in use | 8000 被占用 | 修改 app.yaml 或 kill 进程 |

### 7.2 Worker 崩溃

1. 检查 Effect 是否进入 UNKNOWN_OUTCOME
2. 查看对账队列: `GET /api/v1/gateway-approvals` + EffectJournal
3. 非幂等 Effect 不自动重投,需人工确认

### 7.3 审批卡住

- 检查是否有足够的非发起人审批者
- 检查 ApprovalRequest 是否过期 (默认 24h)
- 可手动 invalidate 过期请求
