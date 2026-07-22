# 威胁模型 v1（STRIDE）

**生成日期**: 2026-07-22
**适用版本**: spec v1.1, P0 完成
**评审状态**: Draft（P0 产出，P1 评审）
**依据**: spec §6 风险模型 + §9 安全门禁 + v3 §4A Agent 特有威胁

## 1. 范围

本文档覆盖 Zcode Desktop Agent 的核心控制面（control-core + desktop shell + IPC）的 STRIDE 威胁分析。P1-P3 会随实现演进补充各平台 Adapter 的细化威胁。

## 2. 信任边界

```
[不可信输入]                  [半可信]                    [可信核心]
                                                       
 用户输入 ──────→ Desktop Shell ──IPC──→ Control API ──→ DB
 (goal/args)     (Tauri/Vue)           (FastAPI)       (SQLite/PG)
                       │                     │
                       │                     ├─→ LLM Gateway → 外部 LLM API
                       │                     ├─→ Tool Gateway → Sandbox Runner
                       │                     └─→ Audit Store
                       │
                       └─→ 本地文件系统 / SecretStore
```

**5 条信任边界**（spec §4.5 + 部署设计 §5.1）：
1. **DMZ**：Nginx 唯一公网入口（self-hosted Profile）
2. **app-net**：Control API + Outbox Worker（personal Profile 下即 loopback）
3. **data-net**：PG/SQLite + Redis
4. **iso-net**：Sandbox Runner（特权隔离）
5. **obs-net**：Langfuse + Prometheus

## 3. STRIDE 矩阵

### S — 欺骗（Spoofing）

| ID | 威胁 | 资产 | 现有缓解 | 残余风险 | 处置阶段 |
|---|---|---|---|---|---|
| S-01 | 伪造 JWT 冒充用户 | API 访问 | HMAC-SHA256 + 5min TTL + SECRET_KEY 校验 | SECRET_KEY 在 app.yaml 写死默认值（G） | P1 rotate |
| S-02 | 伪造本地 IPC peer | sidecar 通信 | P1 实现 Named Pipe SID ACL | 当前无 ACL（spike 用 nonce+PID） | P1 |
| S-03 | Worker 冒充合法 Runner | Tool 执行 | v3 fencing_token + Lease（P2 实现） | 当前无 Lease | P2 |
| S-04 | OIDC token 重放 | SSO 登录 | PKCE + nonce（P3 实现） | 未实现 | P3 |
| S-05 | 跨租户身份伪造 | 租户隔离 | P0.5 ActorScope（待落地到 Repository） | Repository 未强制 tenant 过滤（G） | P1 |

### T — 篡改（Tampering）

| ID | 威胁 | 资产 | 现有缓解 | 残余风险 | 处置阶段 |
|---|---|---|---|---|---|
| T-01 | 审计记录被改 | AuditEvent | append-only（DB 层） | 无 hash chain（v3 §9 要求） | P2 |
| T-02 | CapabilityGrant 参数篡改 | Tool 执行 | P0.5 token withhold（high-risk 不签 token） | Grant 未绑定 args_hash（P2） | P2 |
| T-03 | WorkflowDefinition 篡改 | 编排 | v3 version+digest（P3 实现） | 未实现 | P3 |
| T-04 | tianshu message 命令注入 | dispatch | P0.6 改 REST + 参数化（已完成） | — | ✅ P0 |
| T-05 | app.yaml 配置篡改 | SECRET_KEY | P0.5 暴露默认值问题 | 文件可被本机用户改 | P1 |

### R — 抵赖（Repudiation）

| ID | 威胁 | 资产 | 现有缓解 | 残余风险 | 处置阶段 |
|---|---|---|---|---|---|
| R-01 | 用户否认执行过某动作 | 审计 | AuditEvent 17 种事件类型 + actor 字段 | 无签名/hash chain | P2 |
| R-02 | Agent 否认产出 | Receipt | ToolReceipt schema（P0.1 已定义） | 未持久化 | P2 |

### I — 信息泄露（Information Disclosure）

| ID | 威胁 | 资产 | 现有缓解 | 残余风险 | 处置阶段 |
|---|---|---|---|---|---|
| I-01 | 跨租户读取任务 | Task 数据 | — | Repository 无 tenant 过滤（G） | P1 |
| I-02 | LLM API Key 泄露 | Secret | .env 不入 git（R.2 已验证） | app.yaml 默认值警告 | P1 |
| I-03 | 日志含明文敏感字段 | 日志 | structlog 脱敏中间件 | 未覆盖所有字段 | P1 |
| I-04 | 错误信息泄露栈 | API 响应 | 全局异常处理器 | 生产模式可能漏 | P1 |
| I-05 | 截图含敏感内容 | 屏幕数据 | 默认 confidential 分级（P0.1 schema） | 未实现访问控制 | P2 |

### D — 拒绝服务（Denial of Service）

| ID | 威胁 | 资产 | 现有缓解 | 残余风险 | 处置阶段 |
|---|---|---|---|---|---|
| D-01 | LLM 超时耗尽资源 | API | timeout + max_retries | — | ✅ |
| D-02 | Outbox 积压 | 事件投递 | v3 重试+退避（P2 实现） | 未实现 | P2 |
| D-03 | Runner 雪崩 | Sandbox | v3 资源限制（P2 实现） | 未实现 | P2 |
| D-04 | 限流绕过 | API | rate_limiter 中间件 | — | ✅ |

### E — 提权（Elevation of Privilege）

| ID | 威胁 | 资产 | 现有缓解 | 残余风险 | 处置阶段 |
|---|---|---|---|---|---|
| E-01 | Tool 旁路执行 | Tool 网关 | P0.4 import-linter + check_no_tool_bypass.py | 4 处历史债务待 P0.5/P1 清 | P1 |
| E-02 | 高风险工具绕过审批 | Policy | P0.5 token withhold（已完成） | — | ✅ P0 |
| E-03 | 容器逃逸 | Sandbox | P2 Job Object + seccomp（ADR-008） | 未实现 | P2 |
| E-04 | RBAC 越权 | 权限 | 4 角色 52 权限 RBAC | 请求体含可伪造 user_id（G） | P1 |
| E-05 | SubAgent 自签 Grant | 子代理 | P0.4 get_tool_instance enabled 检查 | SubAgentRunner 仍旁路 | P1 |
| E-06 | 插件越权 | 插件 | Manifest permissions（P7） | 未实现 | P7 |

## 4. v3 §4A Agent 特有威胁

| ID | 威胁 | 现有缓解 | 处置阶段 |
|---|---|---|---|
| AG-01 | Prompt injection 通过 tool_output | ContentProvenance 枚举（P0.1） | P2 落地到 Receipt |
| AG-02 | 审批后上下文调包（tool schema/sandbox 变） | security_context_digest schema（P0.1） | P2 落地到 ToolGateway |
| AG-03 | 供应链：插件/镜像篡改 | execution_supply_chain_digest（v3 §4A） | P3 |
| AG-04 | 浏览器间接注入 | SSRF guard + egress allowlist（P3） | P3 |
| AG-05 | mock 伪装 live | source_status schema（P0.1） | P2 Projection |
| AG-06 | unknown_outcome 被当 failed 重试 | EffectStatus UNKNOWN_OUTCOME 一等状态（P0.1） | P2 EffectJournal |

## 5. P0 已闭环的威胁

- ✅ **T-04** tianshu shell 注入 → P0.6 改 REST
- ✅ **E-02** 高风险审批旁路 → P0.5 token withhold
- ✅ **E-01 部分** Tool 旁路新增闸门 → P0.4 import-linter + AST 检查

## 6. P1 必须闭环的威胁（最高优先级）

- 🔴 **I-01 / S-05** 跨租户访问 → ActorScope 落地到 Repository
- 🔴 **E-04** RBAC 请求体伪造 → 删 user_id 字段
- 🔴 **S-02** IPC 伪造 → Named Pipe SID ACL
- 🔴 **T-05 / I-02** SECRET_KEY 默认值 → rotate + 配置优先级修复
