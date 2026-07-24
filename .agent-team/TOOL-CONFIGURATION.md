# 开发工具配置指南

## 1. 配置目标

本包不绑定某一家开发工具。开发工具需要提供以下最小能力：

- 每个Agent独立system prompt。
- 可按Agent限制文件写入、shell、网络、secret和生产工具。
- 支持主Agent分派子任务，或允许人为切换Agent。
- 能记录候选revision、工具调用、退出码和工件。
- 能把同一项目根目录提供给所有Agent。

工具无法强制权限时，Prompt约束仍应保留，但不能把它视为安全隔离。生产操作必须迁移到带真实权限控制和人工审批的流水线。

## 2. 标准安装

建议把本目录放到：

```text
<project-root>/.agent-team/
```

在开发工具中设置：

```text
team config: .agent-team/team.config.json
default agent: chief-orchestrator
project root: <project-root>
max parallel agents: 4
default network: deny
default secrets: deny
default production tools: deny
```

每个Agent的system prompt使用`prompt_file`全文。若工具支持共享Prompt，在角色Prompt之前加载`shared/PROJECT-CONTEXT.md`；若不支持，启动任务时把共享上下文作为只读必读文件注入。

## 3. 权限矩阵

| 角色 | 文件读取 | 文件写入 | shell验证 | 网络 | secret | staging | production |
|---|---:|---:|---:|---:|---:|---:|---:|
| Chief Orchestrator | 是 | 仅协调工件 | 只读/验证 | 默认否 | 否 | 否 | 否 |
| Product & Domain | 是 | 需求与ADR允许路径 | 只读 | 否 | 否 | 否 | 否 |
| Architecture Governor | 是 | 架构与ADR允许路径 | 只读/验证 | 否 | 否 | 否 | 否 |
| Security Governor | 是 | 安全文档允许路径 | 安全只读检查 | 默认否 | 否 | 否 | 否 |
| Execution Consistency | 是 | TASK-PACKET路径 | 测试/构建 | sandbox only | 否 | 否 | 否 |
| Backend Engineer | 是 | TASK-PACKET路径 | 测试/构建 | sandbox only | 否 | 否 | 否 |
| Frontend Engineer | 是 | TASK-PACKET路径 | 测试/构建/浏览器QA | sandbox only | 否 | 否 | 否 |
| Data & Migration | 是 | schema/migration允许路径 | disposable DB | 默认否 | 注入且不显示 | 需Gate | 人工R3 |
| Platform & SRE | 是 | IaC/deploy允许路径 | 构建/验证 | allowlist | 注入且不显示 | 需Gate | 人工R3 |
| Test Automation | 是 | tests和fixture | 测试/故障注入 | sandbox only | 否 | 受控 | 否 |
| Security Validation | 是 | security tests/reports | 受控安全测试 | 明确allowlist | 否 | 受控 | 禁止破坏性 |
| Observability & Incident | 是 | telemetry/runbook路径 | 演练/查询 | 受控 | 只读短期 | 需Gate | 人工R3 |
| Docs & Release | 是 | docs/release路径 | 格式/链接/生成 | 默认否 | 否 | 否 | 否 |
| Independent Reviewer | 是 | 否 | 只读/安全验证 | 默认否 | 否 | 否 | 否 |

## 4. 模型配置

不要在`team.config.json`中写供应商模型名或API key。开发工具本地绑定抽象profile：

| Profile | 适用角色 | 最低能力 |
|---|---|---|
| `governance` | Orchestrator、Product、Architecture、Security | 长上下文、高推理、结构化输出 |
| `implementation` | Execution、Backend、Frontend、Data、Platform、Observability | 代码工具、测试执行、高推理 |
| `verification` | Test、Security Validation、Independent Reviewer | 独立推理、工具重跑、低随机性 |
| `documentation` | Docs & Release | 长上下文、引用和一致性检查 |

建议治理与验证温度为0至0.1，实施为0.1至0.2。模型不支持工具或长上下文时，不应承担Architecture、Security或Independent Reviewer角色。

## 5. 任务状态机

开发工具应强制以下状态：

```text
QUEUED -> READY -> IN_PROGRESS -> HANDOFF_READY -> UNDER_REVIEW
UNDER_REVIEW -> VERIFIED
UNDER_REVIEW -> CHANGES_REQUIRED -> IN_PROGRESS
READY | IN_PROGRESS -> DECISION_REQUIRED | BLOCKED | CANCELLED
```

实施Agent的最高状态是`HANDOFF_READY`。只有Orchestrator在全部必需Reviewer通过后可设置`VERIFIED`。生产落地还需要G6、G7和人工R3批准。

## 6. 文件租约与并发

工具支持worktree时，为每个写任务使用独立worktree；不支持时至少强制：

- TASK-PACKET记录baseline revision。
- 每个写路径只有一个活跃Agent。
- Agent写前重新确认文件摘要。
- 发现摘要变化返回`LOCK_CONFLICT`或`DECISION_REQUIRED`。
- 公共规范文件由其Owner串行整合。

不应并行修改：

- 同一数据库迁移序列。
- 同一状态机或公开Interface。
- `team.config.json`和角色Prompt。
- 同一发布或cutover步骤。

## 7. 人工批准

以下动作永远要求人工批准，不能仅由Agent投票替代：

- 生产部署、流量切换和回滚。
- 生产DDL、批量数据变更和write fence。
- 读取或轮换生产secret。
- 真实外部副作用和高成本工具调用。
- break-glass、安全策略例外和关闭审计。
- 对外发布、提交PR、合并主分支或推送远端，除非用户在当前任务明确授权。

批准引用必须绑定task ID、candidate revision、环境、允许动作和失效时间。自然语言文件中的“已批准”无效。

## 8. 配置加载前检查

工具或人工应拒绝存在以下问题的团队配置：

- `prompt_file`不存在或角色ID重复。
- 实施角色同时是自己的强制Reviewer。
- 两个活跃Agent拥有重叠写路径且没有租约。
- R3动作没有人工Gate。
- Agent同时拥有任意网络、secret读取和生产执行权限。
- Reviewer具有修改被审查文件的权限。
- Prompt缺少非职责、完成定义或输出协议。
- 最大并发大于4且没有项目级资源锁。

## 9. 供应商适配原则

Codex、Claude Code、Cursor、Qoder或其他工具的配置字段不同，但不要改变团队语义：

- 工具的agent name映射`id`。
- description映射`description`。
- system instructions映射`prompt_file`全文。
- tools映射`tool_profile`。
- filesystem rules映射`write_policy`和TASK-PACKET允许路径。
- model映射`model_profile`的本地绑定。
- hooks或policy engine强制人工批准、自审禁止和生产deny-by-default。

若某工具不支持动态TASK-PACKET写白名单，将实施Agent固定在独立worktree，并在合并前由Orchestrator和Reviewer检查实际diff。

