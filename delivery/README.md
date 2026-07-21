# Agent Control Center 单一控制面 — 架构方案交付总览

> 本目录包含 Agent Control Center 单一控制面迁移项目的完整架构方案，由 AICoding 架构专家团（8 人协作）基于 v2 设计方案与 F:\Agents 下 5 个源项目产出。

## 交付物清单

| 序号 | 文档 | 作者 | 行数 | 校验 | Gate |
|------|------|------|------|------|------|
| 1 | [material_digest.md](material_digest.md) | 闻资料（knowledge-ingest-engineer） | 308 | 7/7 | G1 |
| 2 | [research_report.md](research_report.md) | 查有据（research-analyst） | 498 | 12/12 | G2 |
| 3 | [高层架构设计.md](高层架构设计.md) | 许边界（business-architect） | 592 | 12/12 | G3 |
| 4 | [系统设计.md](系统设计.md) | 高见远（system-architect） | 2682 | 11/11 | G4 |
| 5 | [UserStory.md](UserStory.md) | 顾全景（product-story-designer） | 1218 | 5/5 | G4 |
| 6 | [部署设计.md](部署设计.md) | 毕落地（platform-architect） | 1065 | 8/8 | G5 |
| 7 | [安全设计.md](安全设计.md) | 严守正（security-architect） | 1237 | 9/9 | G5 |

**合计**：7 份文档，约 7600 行，自动校验全部通过 + G5 交叉一致性 diff 6 项全一致。

## 核心架构决策（5 项）

| 编号 | 决策 | 内容 |
|------|------|------|
| D1 | 范围 | myself-agent 唯一写模型，所有副作用收敛到 ExecutionControl 接口 |
| D2 | 技术选型 | LangGraph + PostgreSQL Transactional Outbox + 自研三态 Policy + Docker 容器隔离 + Langfuse |
| D3 | MVP 边界 | 14 条 In-Scope（Phase 0~2），SkillEvaluation/停滞恢复/桌面插件 Adapter 延后完整版 |
| D4 | 复用 vs 新建 | 底座复用 myself-agent（FastAPI/SQLAlchemy 2/RBAC/Alembic），业务逻辑自研 |
| D5 | 部署 | Docker Compose + PostgreSQL 16 + Redis，self-hosted 非云原生 |

## 推荐技术组合（来自调研报告，被高层架构采纳）

| 能力 | 方案 | 来源 |
|------|------|------|
| Workflow 引擎 | LangGraph StateGraph（Python 库嵌入，映射天枢 9 角色 7 态） | B2 加权 3.90 |
| 持久化执行 | 自研（借鉴 Temporal Workflow/Activity/Signal 设计模式，不部署 Server） | B1 加权 4.05 |
| 事件溯源 | PostgreSQL Transactional Outbox（LISTEN/NOTIFY + FOR UPDATE SKIP LOCKED） | B4 设计思想借鉴 |
| Policy 引擎 | 自研三态（DENY/WAIT_APPROVAL/GRANT），扩展现有 RBAC | 自研 |
| 特权 Adapter 隔离 | Docker 容器 + seccomp + cgroups（MVP），gVisor（完整版可选） | U-02 裁决 |
| Telemetry | Langfuse（Docker Compose 自部署，OpenTelemetry 原生） | B5 加权 3.20 |

## 关键裁决结论

- **U-01 LangGraph 性能**：技术上可行，预估 50 并发 Checkpoint 写入 P99 < 50ms，MVP 前 POC 验证，备选自研状态机
- **U-02 Docker 隔离**：满足 MVP 安全要求，9 项资源限制落实到 Docker 配置，完整版可升级 gVisor（仅 runtime=runsc 配置变更）
- **U-03 Schema 合并**：Alembic 增量迁移（版本 15+），现有 24 表 ALTER + 新增 21 表 CREATE
- **D-04 密钥轮换**：key_id 版本号管理 + 旧密钥保留≥1年 + 验证链

## 业务架构（三层）

```
接入层：Operator Console（unified-admin）+ ClawLibrary 可视化包 + External API
   ↓
业务能力层：ExecutionControl → Policy(三态) → Approval → Workflow(LangGraph)
            → WorkerBroker → ToolGateway → [EventLog+Projection] → Audit(hash chain)
   ↓
基础能力层：PostgreSQL 16 + Redis + Langfuse + Docker 隔离容器 + LLM Gateway + Alembic
```

## 网络拓扑（5 信任域）

| 信任域 | Docker 网络 | 组件 | 入站 | 出站 |
|--------|------------|------|------|------|
| DMZ | dmz-net | Nginx | 公网 443/80 | 仅 app-net:8000 |
| 业务 VPC | app-net | Control API/Outbox Worker/Adapter Host | 仅 dmz-net | data-net/iso-net/外部 HTTPS |
| 数据层 | data-net | PostgreSQL + Redis | 仅 app-net | 无（封闭） |
| 特权隔离 | iso-net | PTY/Browser Adapter 容器 | 仅 app-net(Adapter Host) | seccomp+iptables 限制 |
| 可观测 | obs-net | Langfuse/Prometheus/Grafana | 仅 app-net | 无外部出站 |

## MVP 退出标准（Phase 0~2）

- 部署拓扑只有一个 Task 写模型和一个 Orchestrator
- 高风险步骤批准前执行次数为 0
- 跨租户读写成功次数为 0
- 每个副作用可追溯到 command/decision/approval/grant/receipt
- Shell/PTY 和浏览器 Adapter Docker 隔离生效

## 协作流程（Workflow A 全量交付）

```
G0 启动 → G1 资料摄入 → G2 行业调研 → G3 高层架构
  → G4 系统设计 + UserStory（并行）
  → G5 部署设计 + 安全设计（并行，骨架→策略对齐两阶段交接）
  → G6 集成交付（本目录）
```

## 待确认项（移交实施阶段）

| 编号 | 待确认项 | 验证方式 |
|------|---------|---------|
| U-01 | LangGraph 10万+ Workflow 量级性能 | MVP 前 50 并发压测 |
| U-04 | 数据规模上限（10万Task/100万AuditRecord） | MVP 验证 + 完整版归档策略 |

## 上游输入

- v2 设计方案：`agent-control-center-design-and-fix-plan-v2.md`（16 章节，权威驱动）
- 源项目：F:\Agents\myself-agent / agent_tianshu / more_agents / agent_contorl / super-agent-self
