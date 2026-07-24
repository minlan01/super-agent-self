# TASK-PACKET 任务下发协议

Orchestrator必须使用以下字段下发任务。缺少 `objective`、`acceptance_criteria`、`allowed_paths`、`invariants` 或 `validation_commands` 时，实施 Agent应先返回 `NEEDS_TASK_PACKET`，不得开始大范围修改。

```yaml
task_id: SAS-2026-001
title: 为 Effect dispatch attempt 持久化 fencing token
objective: >-
  使每次外部副作用调度都能在数据库中追溯有效 Lease 和 fencing token，
  并让 ToolGateway拒绝旧 token。
requester_outcome: >-
  Worker 崩溃、续租竞争或消息重复时，不会由旧 Worker再次执行同一外部副作用。
owner_agent: execution-consistency-engineer
review_agents:
  - architecture-governor
  - security-governor
  - test-automation-engineer
  - independent-release-reviewer
priority: P0
risk_level: critical
source_refs:
  - delivery/系统设计.md
  - delivery/安全设计.md
  - accepted ADR for Effect execution
allowed_paths:
  - src/execution/**
  - src/tool_gateway/**
  - migrations/**
  - tests/execution/**
forbidden_paths:
  - src/approval/**
  - deploy/production/**
invariants:
  - WorkerBroker remains the sole Lease owner.
  - ToolGateway rejects stale fencing tokens before Adapter invocation.
  - Missing ToolReceipt never implies safe retry.
acceptance_criteria:
  - Dispatch attempt schema persists Lease ID and fencing token atomically with dispatch intent.
  - A stale token test proves Adapter is not invoked.
  - Crash recovery test proves an unknown non-idempotent Effect is reconciled, not replayed.
validation_commands:
  - command: project-specific migration validation command discovered from repository
    required_result: exit code 0
  - command: focused execution consistency test command discovered from repository
    required_result: exit code 0 with stale-token and crash-recovery cases executed
dependencies:
  - accepted Effect state machine
  - accepted Lease ownership ADR
rollback:
  trigger: migration or compatibility validation failure
  action: stop rollout and execute the reviewed backward-compatible rollback path
deliverables:
  - implementation
  - migration
  - focused tests
  - handoff evidence
deadline_or_timebox: one bounded implementation cycle
```

## 状态值

- `READY`：任务包完整，可以开始。
- `NEEDS_TASK_PACKET`：必要字段缺失。
- `DECISION_REQUIRED`：规范冲突或跨模块裁决缺失。
- `IN_PROGRESS`：正在执行任务包内工作。
- `HANDOFF_READY`：实现和本地验证完成，等待审查。
- `BLOCKED`：外部依赖或权限阻止继续，且已给出证据和最小解阻动作。

Agent不得把“工作量较大”“测试运行较慢”或“希望进一步澄清”直接标为 `BLOCKED`。能够通过仓库证据、只读诊断或保守实现继续推进时，应继续工作。

