# Super Agent Self 全生命周期 Agent 团队设计

## 1. 设计目标

该团队用于完成 Agent 控制中心项目从需求、设计、实现、验证、迁移、部署到生产运维的完整闭环。项目包含外部副作用执行、授权审批、多租户隔离、Worker Lease、Artifact、审计和无损切换，任何一个环节的局部正确都不足以推出系统正确。

团队按深模块原则划分：每个 Agent 只暴露稳定的输入和输出 Interface，复杂分析留在角色内部；同一责任只有一个最终 Owner；设计、实施和独立裁决分离。

## 2. 团队拓扑

```text
                          Chief Orchestrator
                                  |
             +--------------------+--------------------+
             |                    |                    |
      Product & Domain     Architecture Governor  Security Governor
             |                    |                    |
             +---------- Task Graph / ADR / Controls --+
                                  |
       +------------+-------------+-------------+-------------+
       |            |             |             |             |
  Execution     Backend       Frontend       Data &       Platform &
  Consistency   Engineer      Engineer       Migration    SRE
       |            |             |             |             |
       +------------+-------------+-------------+-------------+
                                  |
             +--------------------+--------------------+
             |                    |                    |
       Test Automation    Security Validation   Observability & Incident
             |                    |                    |
             +--------------------+--------------------+
                                  |
                        Docs & Release Engineer
                                  |
                     Independent Release Reviewer
```

## 3. 角色清单

| ID | 角色 | 唯一责任 | 默认写权限 |
|---|---|---|---|
| `chief-orchestrator` | Chief Orchestrator | 建立任务图、调度、收口证据、推进门禁 | 仅任务与协调工件 |
| `product-domain-lead` | Product & Domain Lead | 业务状态、术语、UserStory 和可验收标准 | 需求、领域和 ADR 草案 |
| `architecture-governor` | Architecture Governor | 规范执行链、模块 Interface、所有权和 ADR 裁决 | 架构文档和 ADR |
| `security-governor` | Security Governor | 信任模型、授权、隔离、审计和安全放行条件 | 安全文档和威胁模型 |
| `execution-consistency-engineer` | Execution Consistency Engineer | Lease、fencing、Effect、恢复和外部副作用一致性 | 核心执行模块及其测试 |
| `backend-engineer` | Backend Engineer | 非核心一致性模块的后端纵向功能实现 | 后端代码及测试 |
| `frontend-engineer` | Frontend Engineer | 操作台、审批、状态展示和无障碍交互 | 前端代码及测试 |
| `data-migration-engineer` | Data & Migration Engineer | Schema、约束、迁移、回填、切换和回滚 | 数据库与迁移文件 |
| `platform-sre-engineer` | Platform & SRE Engineer | 构建、运行环境、部署、密钥和可靠性 | IaC、部署和运行配置 |
| `test-automation-engineer` | Test Automation Engineer | 测试策略、自动化、故障注入和回归证据 | 测试与测试工具 |
| `security-validation-engineer` | Security Validation Engineer | 对抗性验证、越权和租户逃逸测试 | 安全测试与报告 |
| `observability-incident-engineer` | Observability & Incident Engineer | SLI/SLO、遥测、告警、Runbook 和演练 | 观测与 Runbook |
| `docs-release-engineer` | Docs & Release Engineer | 文档同步、变更记录、操作说明和发布包 | 文档与发布工件 |
| `independent-release-reviewer` | Independent Release Reviewer | 只读独立复核并给出最终裁决 | 默认只读 |

## 4. 控制面与交付面

### 控制面

Chief Orchestrator、Product & Domain Lead、Architecture Governor、Security Governor 和 Independent Release Reviewer 属于控制面。它们定义问题、约束和裁决，不承担大规模实现。控制面 Agent 不得为了加快进度降低验收标准，也不得把未决架构问题交给实施 Agent自行决定。

### 交付面

其余 Agent 属于交付面。每个 Agent 只接受完整 `TASK-PACKET`，在允许路径内实现并通过 `HANDOFF` 回交。交付面 Agent 可发现设计缺陷，但不得自行改变跨模块不变量；它们应返回 `DECISION_REQUIRED`。

## 5. 标准生命周期

### 阶段 A：问题定义

1. Orchestrator 建立任务编号、目标和初始范围。
2. Product & Domain Lead 写出业务结果、状态转换和可观察验收标准。
3. Architecture Governor 判断是否涉及 Interface、所有权、事务或规范执行链。
4. Security Governor 判断是否涉及信任边界、授权、租户、Artifact 或生产数据。
5. 未决项完成裁决后进入 Gate G1。

### 阶段 B：设计闭合

1. Architecture Governor 给出模块 Interface、调用顺序、失败模式和所有权矩阵。
2. Security Governor给出威胁、控制、失败时默认行为和验证方法。
3. Data & Migration Engineer 给出 schema、约束、迁移和回滚设计。
4. Test Automation Engineer 把不变量转换为测试矩阵。
5. Orchestrator确认没有互相冲突的规范路径后进入 Gate G2。

### 阶段 C：实现

1. 按文件所有权和依赖图并行实施。
2. 同一状态机、同一迁移链、同一 Interface 的修改串行进行。
3. 每个实施 Agent本地验证并提交 Handoff。
4. Architecture Governor和 Security Governor只复核影响各自不变量的变更。

### 阶段 D：集成验证

1. Test Automation Engineer执行功能、并发、恢复、故障注入和回归测试。
2. Security Validation Engineer执行越权、重放、跨租户、Artifact 和密钥滥用测试。
3. Observability & Incident Engineer验证指标、日志、trace、告警和 Runbook。
4. 所有失败必须有负责人、复现证据和关闭证据。

### 阶段 E：发布与落地

1. Data & Migration Engineer验证备份、回填、final delta、硬 write fence、切换和回滚。
2. Platform & SRE Engineer验证部署工件、密钥、容量、健康检查和降级策略。
3. Docs & Release Engineer生成变更记录、操作手册和发布清单。
4. Independent Release Reviewer独立审阅完整证据并裁决 `PASS`、`CHANGES_REQUIRED` 或 `BLOCKED`。
5. 只有 `PASS` 可进入生产执行；部署后的观测窗口仍属于本次发布。

## 6. 并行策略

默认最大并发为 4。允许并行的典型组合：

- Product & Domain Lead 与 Security Governor并行澄清业务和威胁。
- Backend Engineer 与 Frontend Engineer在 Interface 冻结后并行。
- Test Automation Engineer在实现期间并行编写契约测试和故障注入框架。
- Observability & Incident Engineer在部署设计稳定后并行建立告警与 Runbook。

禁止并行的情形：

- 两个 Agent修改同一文件或同一数据库迁移序列。
- Architecture Governor尚未裁决却让多个 Agent分别实现不同状态机。
- CapabilityGrant、Approval、Lease 或 Effect 的 Interface 尚未冻结。
- cutover、rollback 和 write fence 尚未形成一套原子协议。

## 7. 任务路由

| 变更类型 | 主实施 Agent | 强制审查 |
|---|---|---|
| Lease、fencing、Effect、ToolGateway | Execution Consistency Engineer | Architecture、Security、Test、Independent Reviewer |
| 授权、Approval、Grant、租户、Artifact | 对应实施 Agent | Security、Security Validation、Independent Reviewer |
| 普通后端业务 | Backend Engineer | Test；涉及 Interface 时加 Architecture |
| 操作台和审批 UI | Frontend Engineer | Product、Security、Test |
| Schema、迁移、回填、cutover | Data & Migration Engineer | Architecture、Platform、Test、Independent Reviewer |
| 部署、密钥、容量、灾备 | Platform & SRE Engineer | Security、Observability、Independent Reviewer |
| 仅文档修订 | Docs & Release Engineer 或文档 Owner | Architecture/Security按内容选择 |

## 8. 防止 Agent 失控的机制

- 单入口：只有 Orchestrator 接收未经结构化的用户请求。
- 限定路径：任务包显式列出允许和禁止修改的路径。
- 决策升级：跨模块不变量变化必须生成 ADR，不由实施 Agent临场决定。
- 证据优先：完成状态必须带命令、退出码和关键输出。
- 独立裁决：Reviewer只审不改，实施 Agent不可自审。
- 失败默认关闭：涉及授权、租户归属、Grant、Effect 或 Artifact 状态不确定时，禁止继续执行外部副作用。
- 防循环：同一发现最多经历一次修复和一次复审；仍不通过则返回 Orchestrator重新规划。
- 防文档漂移：代码、测试、schema、运行配置和规范文档必须在同一发布任务中同步。

## 9. 团队成功指标

- 规范执行链只有一条，仓库内不存在相互冲突的旧流程。
- 关键不变量都有可自动运行的契约测试或故障注入测试。
- 每个生产变更都能从 UserStory追溯到任务、代码、测试、迁移和发布证据。
- 发布裁决可由未参与实现的人根据仓库证据复现。
- 回滚不是口头方案，而是经过演练且有时间和数据边界的可执行过程。

