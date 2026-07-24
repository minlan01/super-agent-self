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

Agent不得把”工作量较大””测试运行较慢”或”希望进一步澄清”直接标为 `BLOCKED`。能够通过仓库证据、只读诊断或保守实现继续推进时，应继续工作。

---

# 当前任务包: P2 受控执行纵向切片

> 创建: 2026-07-24 | 阶段: P2 | 门禁: G2 | 状态: READY

## 业务结果

实现规格 §4.3 核心执行契约完整纵向切片:用 file.read(Low) + file.delete(High) 跑通全链路。

## 执行链路(必须全部实现)

```
Command -> PlanVersion(已有) -> PolicyDecision(已有 P0.5 三态)
  -> ApprovalRequest(需实现) -> CapabilityGrant(需实现 GrantIssuer)
  -> Lease(需实现 LeaseManager) -> EffectRecord PREPARED(需实现 EffectJournal)
  -> Adapter invoked(需实现 ToolGateway) -> ToolReceipt recorded
  -> EffectRecord CONFIRMED|FAILED|UNKNOWN_OUTCOME -> Audit(已有)
```

## 任务图(DAG)

```
P2.1 (DB models+migration, data-migration-engineer)
  |---> P2.2 (GrantIssuer, backend-engineer)         \
  |---> P2.3 (LeaseManager, exec-consistency-eng)     | 可并行(不同文件)
  |---> P2.4 (EffectJournal, exec-consistency-eng)   /
          |---> P2.5 (ToolGateway, exec-consistency-eng)
                  |---> P2.6 (ApprovalService+resume, backend-engineer)
                          |---> P2.7 (集成测试, test-automation-eng)
                                  |---> REVIEW -> VERDICT
```

## P2.1 任务包

```yaml
task_id: SAS-P2-001
title: P2 执行契约持久化层 - grant/lease/effect/receipt/dispatch_attempt
objective: >-
  为 CapabilityGrant/Lease/EffectRecord/ToolReceipt/DispatchAttempt 新增 DB models
  和 alembic migration,对齐 protocol/schemas/v1.py 已有 schema。
owner_agent: data-migration-engineer
review_agents: [architecture-governor, platform-sre-engineer, test-automation-engineer, independent-release-reviewer]
priority: P0
risk_level: high
allowed_paths:
  - services/control-core/packages/db/models.py
  - services/control-core/packages/db/repositories/
  - services/control-core/alembic/versions/
forbidden_paths:
  - services/control-core/packages/protocol/**
  - services/control-core/packages/policy/**
  - services/control-core/packages/executor/**
invariants:
  - tenant_id mandatory on all new tables
  - handle_digest 只存 SHA-256,不存明文 handle
  - fencing_token INTEGER NOT NULL DEFAULT 0
  - Effect status 终态不可回退
acceptance_criteria:
  - models.py 新增 5 个表: capability_grants, leases, effect_records, tool_receipts, dispatch_attempts
  - alembic migration 可在 SQLite 正向+反向执行
  - 每个 repository 有 create/get_by_id/update_status 方法
  - tenant_id 复合索引存在于每个新表
validation_commands:
  - command: cd services/control-core && alembic upgrade head
  - command: cd services/control-core && python -m pytest packages/db/ -v
dependencies: [protocol v1 schema frozen]
```

## P2.2 任务包

```yaml
task_id: SAS-P2-002
title: GrantIssuer - opaque handle 签发 + digest 持久化 + 撤销
objective: >-
  实现 GrantIssuer,从 PolicyDecision.GRANT 生成 256-bit opaque handle,
  DB 只存 digest,ToolGateway 回表验证。支持撤销和过期。
owner_agent: backend-engineer
review_agents: [security-governor, security-validation-engineer, test-automation-engineer, independent-release-reviewer]
priority: P0
risk_level: critical
allowed_paths:
  - services/control-core/packages/policy/grant_issuer.py
  - services/control-core/packages/db/repositories/grant_repo.py
  - services/control-core/tests/test_grant_issuer.py
forbidden_paths:
  - services/control-core/packages/executor/**
  - services/control-core/packages/protocol/**
invariants:
  - handle = secrets.token_urlsafe(32) (256-bit)
  - DB 只存 SHA-256(handle),不存明文
  - Grant 绑定: tenant/workspace/step_run_id/tool_name/bound_args_hash/resource_scope/security_context_digest/approval_resolution_id/audience/nonce/expires_at/max_uses=1
  - 消费后 status=CONSUMED,不可二次使用
  - 撤销后 status=REVOKED,不可消费
  - break_glass key_id 豁免 approval_resolution_id 但必须记录理由
acceptance_criteria:
  - issue() 返回 (handle, grant_record),DB 存 digest
  - verify(handle) 回表验证: digest 匹配 + 未过期 + 未消费 + 未撤销 + scope 匹配
  - consume(handle) 原子标记 CONSUMED,二次消费返回 False
  - revoke(grant_id) 标记 REVOKED
  - 测试: nonce 二次消费 = 0,过期 Grant 消费 = 0,撤销后消费 = 0
validation_commands:
  - command: cd services/control-core && python -m pytest tests/test_grant_issuer.py -v
dependencies: [SAS-P2-001]
```

## P2.3 任务包

```yaml
task_id: SAS-P2-003
title: LeaseManager - fencing_token 单调性 + 续租/释放/过期
objective: >-
  实现 WorkerBroker 的 Lease 管理:创建 Lease 带 fencing_token(单调递增 per worker),
  续租延长 expires_at,释放标记 inactive,过期 Lease 不可用于 dispatch。
owner_agent: execution-consistency-engineer
review_agents: [architecture-governor, security-governor, test-automation-engineer, independent-release-reviewer]
priority: P0
risk_level: critical
allowed_paths:
  - services/control-core/packages/execution/lease_manager.py
  - services/control-core/packages/db/repositories/lease_repo.py
  - services/control-core/tests/test_lease_manager.py
forbidden_paths:
  - services/control-core/packages/policy/**
  - services/control-core/packages/protocol/**
invariants:
  - fencing_token 单调递增 per (worker_id, step_run_id)
  - Lease expires_at > created_at
  - 释放/过期后不可用于新 dispatch
  - WorkerBroker 是 Lease 的唯一写入 Owner
acceptance_criteria:
  - acquire(worker_id, step_run_id) 返回 Lease, fencing_token = max(existing)+1
  - renew(lease_id) 延长 expires_at,旧 fencing_token 不变
  - release(lease_id) 标记 inactive
  - is_valid(lease_id) 检查: active + 未过期 + fencing_token 匹配
  - 测试: stale fencing_token dispatch = 0,过期 Lease dispatch = 0
validation_commands:
  - command: cd services/control-core && python -m pytest tests/test_lease_manager.py -v
dependencies: [SAS-P2-001]
```

## P2.4 任务包

```yaml
task_id: SAS-P2-004
title: EffectJournal - PREPARED->DISPATCHED->CONFIRMED/FAILED/UNKNOWN 状态机
objective: >-
  实现 EffectJournal:在 adapter 调用前创建 EffectRecord(PREPARED),
  dispatch 时记录 attempt(fencing_token/grant_digest/worker_id/adapter/time),
  收到 receipt 后迁移到 CONFIRMED/FAILED/UNKNOWN_OUTCOME。
  不可幂等 unknown_outcome 不自动重投,进入对账队列。
owner_agent: execution-consistency-engineer
review_agents: [architecture-governor, security-governor, test-automation-engineer, independent-release-reviewer]
priority: P0
risk_level: critical
allowed_paths:
  - services/control-core/packages/execution/effect_journal.py
  - services/control-core/packages/db/repositories/effect_repo.py
  - services/control-core/tests/test_effect_journal.py
forbidden_paths:
  - services/control-core/packages/policy/**
  - services/control-core/packages/protocol/**
invariants:
  - Effect 状态: PREPARED -> DISPATCHED -> CONFIRMED|FAILED|UNKNOWN_OUTCOME
  - 终态不可回退
  - 每次 dispatch attempt 持久化: effect_id/attempt_id/lease_id/fencing_token/grant_digest/worker_id/adapter/时间
  - UNKNOWN_OUTCOME + 非幂等 -> 对账队列,不自动重投
  - EffectJournal 不能越权关闭 Lease
acceptance_criteria:
  - prepare() 创建 EffectRecord(status=PREPARED)
  - record_dispatch() 追加 dispatch_attempt,迁移到 DISPATCHED
  - finalize(status, receipt) 迁移到终态,记录 finalized_at
  - get_unknown_outcomes() 返回需对账的 Effect 列表
  - 测试: 状态转换合法,终态不可回退,unknown 非幂等不重投
validation_commands:
  - command: cd services/control-core && python -m pytest tests/test_effect_journal.py -v
dependencies: [SAS-P2-001]
```

## P2.5 任务包

```yaml
task_id: SAS-P2-005
title: ToolGateway - Tool 调用唯一入口,验证 Grant+Effect+Lease+fencing
objective: >-
  实现 ToolGateway 作为 Tool 调用唯一入口:
  1.验证 Grant(handle 回表,scope 匹配,未过期/消费/撤销)
  2.验证 Lease(active,未过期,fencing_token 匹配)
  3.创建 Effect(PREPARED) -> 记录 dispatch -> 调用 adapter -> 记录 receipt -> finalize Effect
  4.消费 Grant(max_uses=1,原子标记 CONSUMED)
  5.替换 tool_runner.py 的直接 tool.execute() 调用
owner_agent: execution-consistency-engineer
review_agents: [architecture-governor, security-governor, test-automation-engineer, independent-release-reviewer]
priority: P0
risk_level: critical
allowed_paths:
  - services/control-core/packages/executor/tool_gateway.py
  - services/control-core/packages/executor/tool_runner.py  # 改为委托 ToolGateway
  - services/control-core/packages/executor/executor_service.py  # 改为调 ToolGateway
  - services/control-core/tests/test_tool_gateway.py
forbidden_paths:
  - services/control-core/packages/protocol/**
invariants:
  - ToolGateway 是 Tool 调用唯一入口
  - Grant 验证失败 -> fail closed,不执行
  - Lease/fencing 验证失败 -> fail closed,不执行
  - Effect 必须在 adapter 调用前 PREPARED
  - Grant 消费是原子的(consume 在 dispatch 前)
  - 无 ToolReceipt 不能推导工具没执行
acceptance_criteria:
  - invoke(handle, lease_id, tool_name, args) 全链路执行
  - 无效 handle/过期/撤销/已消费 -> 拒绝,Effect 记录 FAILED
  - stale fencing_token -> 拒绝,Effect 记录 FAILED
  - adapter 成功 -> Effect CONFIRMED, Grant CONSUMED
  - adapter 超时/崩溃 -> Effect UNKNOWN_OUTCOME
  - 架构测试(P0.4 check_no_tool_bypass.py)证明无旁路
validation_commands:
  - command: cd services/control-core && python -m pytest tests/test_tool_gateway.py -v
  - command: cd services/control-core && python scripts/check_no_tool_bypass.py
dependencies: [SAS-P2-002, SAS-P2-003, SAS-P2-004]
```

## P2.6 任务包

```yaml
task_id: SAS-P2-006
title: ApprovalService - Request/Vote/Resolution + resume 机制
objective: >-
  实现 ApprovalService:
  1.从 PolicyDecision.WAIT_APPROVAL 创建 ApprovalRequest(绑定 plan/资源/policy_digest/security_digest)
  2.审批人 Vote(身份来自 ActorScope,禁止自审)
  3.达 quorum 后 Resolution(APPROVED/REJECTED)
  4.APPROVED 后触发 GrantIssuer 签发 Grant,resume 执行
  5.关键内容改变后旧 Resolution 失效
owner_agent: backend-engineer
review_agents: [security-governor, security-validation-engineer, test-automation-engineer, independent-release-reviewer]
priority: P0
risk_level: critical
allowed_paths:
  - services/control-core/packages/approval/approval_service.py
  - services/control-core/packages/db/repositories/approval_repo.py
  - services/control-core/tests/test_approval_service.py
forbidden_paths:
  - services/control-core/packages/protocol/**
  - services/control-core/packages/execution/**
invariants:
  - 审批身份来自服务端 ActorScope,不接受客户端自报
  - 禁止发起人自审(即使 quorum=1)
  - ApprovalRequest 绑定 plan/资源/policy_digest/security_digest
  - 关键内容改变后旧 Resolution 失效
  - APPROVED 事务内部持久化唯一续跑命令,不暴露通用 resume
acceptance_criteria:
  - create_request(policy_decision) 创建 ApprovalRequest(PENDING)
  - vote(request_id, actor_scope, decision) 记录 Vote,禁止自审
  - resolve(request_id) 达 quorum 后创建 Resolution
  - approved -> 触发 GrantIssuer.issue + resume 执行
  - rejected -> 标记 step REJECTED
  - 测试: 自审被拒,quorum 不足不 resolve,approved 后 Grant 签发
validation_commands:
  - command: cd services/control-core && python -m pytest tests/test_approval_service.py -v
dependencies: [SAS-P2-002, SAS-P2-005]
```

## P2.7 任务包

```yaml
task_id: SAS-P2-007
title: 纵向切片集成测试 - file.read(Low) + file.delete(High) 全链路
objective: >-
  端到端测试完整执行链路:
  1. file.read(Low): Policy GRANT -> Grant issued -> Lease -> Effect PREPARED -> ToolGateway -> Receipt -> Effect CONFIRMED
  2. file.delete(High): Policy WAIT_APPROVAL -> ApprovalRequest -> Vote APPROVED -> Grant issued -> Lease -> Effect -> ToolGateway -> Receipt -> CONFIRMED
  3. file.delete(High) REJECTED: -> step REJECTED,无 Grant,无 Effect
  4. Grant nonce 重用 -> 拒绝
  5. stale fencing_token -> 拒绝
owner_agent: test-automation-engineer
review_agents: [security-validation-engineer, independent-release-reviewer]
priority: P0
risk_level: high
allowed_paths:
  - services/control-core/tests/test_p2_vertical_slice.py
  - services/control-core/tests/test_p2_security_invariants.py
forbidden_paths:
  - services/control-core/packages/**
invariants:
  - 测试不跳过
  - 每个断言有明确错误信息
  - 测试覆盖 G2 门禁全部子项
acceptance_criteria:
  - file.read 全链路通过,Audit 完整
  - file.delete High 批准后执行,before_hash/after_hash 记录
  - file.delete High 拒绝后无执行
  - Grant nonce 重用 = 0 成功
  - stale fencing = 0 成功
  - Effect 三态(confirmed/failed/unknown_outcome)覆盖
validation_commands:
  - command: cd services/control-core && python -m pytest tests/test_p2_vertical_slice.py tests/test_p2_security_invariants.py -v
dependencies: [SAS-P2-001 through SAS-P2-006]
```

