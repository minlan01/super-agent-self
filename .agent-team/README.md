# Super Agent Self 项目 Agent 团队包

本目录是一套面向 `super-agent-self` 项目的、开发工具无关的 Agent 团队配置。它覆盖需求澄清、架构治理、核心开发、安全、测试、迁移、部署、运维、文档和独立发布评审。

## 目录内容

- `TEAM-DESIGN.md`：团队拓扑、职责边界、协作流程和落地方式。
- `team.config.json`：机器可读的角色、路由、并发和门禁配置。
- `shared/PROJECT-CONTEXT.md`：所有 Agent 必须遵守的项目上下文和不变量。
- `shared/TASK-PACKET.md`：Orchestrator 下发任务的统一格式。
- `shared/HANDOFF.md`：实施 Agent 回交结果的统一格式。
- `shared/REVIEW.md`：审查 Agent 输出发现和裁决的统一格式。
- `shared/RELEASE-GATES.md`：从需求到生产的阶段门禁。
- `prompts/`：14 个可直接作为 system prompt 使用的完整角色 Prompt。
- `BOOTSTRAP-PROMPT.md`：给支持单一主 Prompt 的开发工具使用的启动 Prompt。

## 快速配置

1. 将本目录放到项目根目录，建议目录名为 `.agent-team`。
2. 在开发工具中创建 `team.config.json` 定义的 14 个 Agent。
3. 每个 Agent 的 system prompt 使用其 `prompt_file` 指向的文件全文。
4. 将 `00-chief-orchestrator` 配置为唯一默认入口；普通任务不要直接交给实施 Agent。
5. 将项目根目录作为所有 Agent 的工作目录，并启用版本控制读取、文件搜索、测试命令和补丁编辑工具。
6. 对治理和审查角色默认禁用写权限；需要写 ADR 或评审报告时，只开放任务包明确列出的路径。
7. 将最大并发设置为 4。相同文件、相同数据库迁移链和相同状态机不得并行修改。

如果开发工具只支持一个 Agent，将 `BOOTSTRAP-PROMPT.md` 作为主 system prompt，并让主 Agent按需加载 `prompts/` 中的角色 Prompt。该模式能工作，但独立审查隔离会弱于真正的多 Agent 配置。

## 推荐运行模式

### 最小团队

适合文档修订、小型功能和低风险维护：

- Chief Orchestrator
- Product & Domain Lead
- Architecture Governor
- 对应实施 Agent
- Test Automation Engineer
- Independent Release Reviewer

涉及授权、外部副作用、租户数据、Artifact、迁移或生产部署时，最小团队模式不得使用，必须切换完整团队。

### 完整团队

适合核心执行链、生产发布和跨模块改动。Orchestrator 根据任务图并行调度相关角色；Security Governor、Architecture Governor、Test Automation Engineer 和 Independent Release Reviewer 构成强制门禁。

## 使用规则

- 任务必须先形成 `TASK-PACKET`，再开始实现。
- 文档冲突必须记录为决策问题，任何 Agent 都不得静默选择对自己最方便的一版。
- Agent 只能修改任务包 `allowed_paths` 内的文件。
- 实施 Agent 不得给自己的变更判定 `PASS`。
- 没有命令、退出码、测试数量和关键输出摘要的“已验证”不算证据。
- 模板、关键词和章节检查只能证明格式合规，不能证明架构、事务或安全语义正确。
- 生产发布必须满足 `shared/RELEASE-GATES.md` 的全部强制门禁。

## 工具映射

对任意支持自定义 Agent 的开发工具，按以下字段映射：

| 本包字段 | 开发工具常见字段 |
|---|---|
| `id` | agent name / slug |
| `display_name` | display name |
| `description` | when to use / routing description |
| `prompt_file` | system prompt / instructions |
| `tool_profile` | allowed tools / permissions |
| `write_policy` | file access policy |
| `model_profile` | model tier / reasoning level |

工具不支持某字段时，应保留 Prompt 中的行为约束，不要删除角色边界或发布门禁。

