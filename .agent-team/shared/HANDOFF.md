# HANDOFF 实施回交协议

每个实施 Agent完成任务后必须返回以下结构。任何必需验证未执行时，状态不能是 `HANDOFF_READY`，除非任务包明确允许并由 Orchestrator记录例外。

```yaml
task_id: SAS-2026-001
agent_id: execution-consistency-engineer
status: HANDOFF_READY
outcome: >-
  Dispatch attempt 已原子持久化 Lease ID 和 fencing token，ToolGateway在 Adapter调用前拒绝旧 token。
changed_files:
  - path: migrations/20260720_add_dispatch_fencing.sql
    purpose: 添加字段、约束和兼容索引
  - path: src/execution/effect_dispatch.py
    purpose: 在 dispatch intent事务中保存 Lease上下文
  - path: tests/execution/test_fencing.py
    purpose: 覆盖旧 token和崩溃恢复
behavior_changes:
  - stale fencing token now fails closed before Adapter invocation
interface_changes:
  - dispatch intent requires lease_id and fencing_token
data_changes:
  - nullable expansion followed by backfill and validated not-null contraction
security_impact:
  - closes stale Worker replay path
decisions_made:
  - decision: no local architecture decision
    basis: followed accepted ADR and task invariants
validation:
  - command: repository-specific focused test command
    working_directory: project root
    exit_code: 0
    result: stale-token, duplicate-delivery and crash-recovery cases passed
  - command: repository-specific migration validation command
    working_directory: project root
    exit_code: 0
    result: upgrade and reviewed rollback path passed on disposable database
unrun_checks: []
known_risks: []
review_focus:
  - transaction boundary between dispatch intent and Effect state
  - Adapter invocation remains after all authorization and fencing checks
rollback_ready: true
```

## 回交质量规则

- `changed_files` 必须与实际 diff一致。
- `validation` 不能只写“测试通过”，必须给出命令、退出码和结果。
- `known_risks` 为空表示 Agent已主动检查，没有已知未披露风险，不表示系统绝对无风险。
- 发现任务外缺陷时记录在 `out_of_scope_findings`，不得顺手扩大修改范围。
- 变更涉及 Interface、schema、授权或运行行为时，必须填写对应影响字段。

