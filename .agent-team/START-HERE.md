# 从这里开始

这是 `super-agent-self` 项目的 Agent 团队配置包。它采用“控制面治理 + 专业实施 + 独立验证 + 发布门禁”的结构，默认不允许 Agent 自证、越权、直接生产操作或把文档格式检查当成语义验证。

## 先读这四份

1. `TEAM-DESIGN.md`：团队拓扑、角色边界、生命周期和并行策略。
2. `shared/PROJECT-CONTEXT.md`：所有角色共享的不变量和真相源优先级。
3. `FIRST-RUN-PLAN.md`：针对当前项目已知冲突的首次基线收敛 Sprint。
4. `TOOL-CONFIGURATION.md`：开发工具权限、模型、状态机和人工审批映射。

## 配置入口

- `team.config.json`：14 个 Agent 的机器可读定义和强制路由。
- `runtime-policy.json`：风险等级、任务状态、文件租约、生产人工审批和预算。
- `prompts/00-chief-orchestrator.md`：多 Agent工具的默认入口角色。
- `BOOTSTRAP-PROMPT.md`：只支持单主Agent的工具的启动Prompt。

## 共享协议

- `shared/TASK-PACKET.md`：下发任务。
- `shared/HANDOFF.md`：实施回交。
- `shared/REVIEW.md`：独立审查。
- `shared/RELEASE-GATES.md`：G0至G7生命周期门禁。

## 运行前验证

```powershell
powershell -ExecutionPolicy Bypass -File .\Validate-Team.ps1
```

验证通过只表示团队配置内部一致，不表示项目代码已通过发布门禁。

## 当前环境的复制状态

团队包已完整生成在 `C:\tmp\super-agent-self-agent-team`。由于 `F:` USB卷当前未挂载，尚未写入用户项目目录。重新挂载后按 `COPY-INSTRUCTIONS.md` 执行，目标目录为 `F:\Agents\super-agent-self\.agent-team`。

