# REVIEW 独立审查协议

审查 Agent先给 findings，再给结论。findings按 `P0`、`P1`、`P2`、`P3` 排序，每项必须包含证据和可验证修复条件。

```yaml
review_id: REV-SAS-2026-001
task_id: SAS-2026-001
reviewer_agent: independent-release-reviewer
scope:
  baseline: accepted commit or task start snapshot
  reviewed_change: current worktree or candidate commit
verdict: CHANGES_REQUIRED
findings:
  - id: REV-SAS-2026-001-F01
    severity: P0
    title: stale fencing token can reach Adapter
    evidence:
      - file: src/tool_gateway/dispatch.py
        line: 142
        observation: Adapter call occurs before fencing validation
    impact: old Worker can repeat an external side effect
    required_fix: move validation before Adapter invocation and add a test proving zero Adapter calls
    closure_evidence: focused test command and passing output
requirements_coverage:
  satisfied: []
  unsatisfied:
    - ToolGateway rejects stale fencing tokens before Adapter invocation
validation_reviewed:
  - command: repository-specific focused test command
    exit_code: 1
    interpretation: release gate not met
residual_risk:
  - no production-like latency fault injection evidence
```

## 严重度

- `P0`：可能造成越权、跨租户泄漏、不可逆外部副作用、数据丢失或生产不可恢复；阻断发布。
- `P1`：重要正确性、安全性、可靠性或可运维性缺口；阻断生产基线。
- `P2`：有限场景缺陷、维护性风险或缺少非关键验证；需排期或在发布中显式接受。
- `P3`：不影响当前正确性的改进建议。

## 裁决

- `PASS`：没有未关闭的 P0/P1，强制门禁证据完整，残余风险已在允许范围。
- `CHANGES_REQUIRED`：存在可在当前范围修复的发现。
- `BLOCKED`：缺少必要决策、环境、权限或外部证据，审查无法形成可靠结论。

Reviewer不得修改被审查实现来消除自己的 finding，也不得因模板检查通过而推断语义正确。

