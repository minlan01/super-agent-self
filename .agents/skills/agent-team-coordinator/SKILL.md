---
name: agent-team-coordinator
description: Load and operate the super-agent-self 14-role agent team for coordinated development. Use when starting any implementation task, code review, security validation, or release gate in this project - the team enforces single-entry dispatch, mandatory routing, independent review, and G0-G7 release gates per spec v1.1. Triggers on phrases like "implement", "review", "deploy", "run tests", "security check", "release gate", or when a task touches lease/grant/effect/schema/migration/deployment.
---

# Agent Team Coordinator

This skill loads the `super-agent-self` agent team defined in `.agent-team/` and coordinates multi-role development using ZCode's Agent tool for sub-agent dispatch.

## How it works

The team has 14 roles across 4 layers:

| Layer | Roles | Purpose |
|---|---|---|
| **Coordinator** | chief-orchestrator | 唯一任务入口;拆解、路由、依赖、门禁、证据收口 |
| **Governance** | product-domain-lead, architecture-governor, security-governor | 领域/架构/安全治理,写 ADR 和规范 |
| **Implementation** | execution-consistency-engineer, backend-engineer, frontend-engineer, data-migration-engineer, platform-sre-engineer, observability-incident-engineer | 按角色实现代码,只能交付 HANDOFF 不能自定 PASS |
| **Verification** | test-automation-engineer, security-validation-engineer, independent-release-reviewer | 独立测试/攻击/最终发布裁决 |
| **Documentation** | docs-release-engineer | 文档同步 + 发布包 |

## Startup protocol

When this skill triggers, read these files in order (they are the fact source, this skill is only a loader):

1. `.agent-team/team.config.json` - 14 agent 定义 + 强制路由 + 全局策略
2. `.agent-team/shared/PROJECT-CONTEXT.md` - 不可违反不变量 + 真相源优先级
3. `.agent-team/shared/TASK-PACKET.md` - 任务下发格式
4. `.agent-team/shared/HANDOFF.md` - 实施回交格式
5. `.agent-team/shared/REVIEW.md` - 独立审查格式
6. `.agent-team/shared/RELEASE-GATES.md` - G0-G7 门禁定义
7. `.agent-team/runtime-policy.json` - 风险等级/任务状态/预算
8. `.agent-team/prompts/00-chief-orchestrator.md` - 协调者角色指令

After reading, act as **chief-orchestrator** and follow the 10-step protocol in `.agent-team/BOOTSTRAP-PROMPT.md`.

## Dispatching sub-agents

When dispatching a task to a specific role via ZCode's Agent tool:

1. Read the role's prompt file (e.g. `.agent-team/prompts/05-backend-engineer.md`)
2. Construct the sub-agent's instruction by combining:
   - The role's full prompt (from the .md file)
   - The relevant TASK-PACKET (from `.agent-team/shared/TASK-PACKET.md` template)
   - The shared PROJECT-CONTEXT (invariants the role must respect)
   - The specific task scope, allowed paths, and forbidden paths
3. The sub-agent returns a HANDOFF (not a self-approved PASS)
4. Route the HANDOFF to the mandatory reviewers from `team.config.json` `mandatory_routing`

## Mandatory routing (from team.config.json)

| Task keywords | Implementer | Reviewers |
|---|---|---|
| lease, fencing, effect, tool_gateway, recovery | execution-consistency-engineer | architecture-governor, security-governor, test-automation-engineer, independent-release-reviewer |
| capability_grant, approval, authorization, tenant, audit | backend-engineer | security-governor, security-validation-engineer, test-automation-engineer, independent-release-reviewer |
| schema, migration, cutover, rollback | data-migration-engineer | architecture-governor, platform-sre-engineer, test-automation-engineer, independent-release-reviewer |
| deployment, secret, capacity, backup | platform-sre-engineer | security-governor, observability-incident-engineer, independent-release-reviewer |

## Global policies (non-negotiable)

- **single_entry**: all tasks go through chief-orchestrator
- **require_task_packet**: no work without a structured TASK-PACKET
- **implementer_may_self_approve**: false (实现者不能自审)
- **reviewer_may_modify_reviewed_change**: false (审查者不能改被审查的代码)
- **evidence_required_for_completion**: true (完成声明必须有命令+退出码+测试数)
- **production_fail_closed**: true (生产环境 fail closed)
- **maximum_fix_review_cycles**: 1 (最多修一轮)

## Release gates (G0-G7)

| Gate | Phase | Key checks |
|---|---|---|
| G0 | P0 基线 | ADR/schema/CI/架构测试/审批修复 |
| G1 | P1 控制面 | IPC 对抗/Secret 隔离/跨 Session 拒绝 |
| G2 | P2 执行切片 | 审批前执行=0/nonce 二次消费=0/Sandbox 回退=0 |
| G3 | P3 MVP | STRIDE/渗透/8h 长稳/审计完整率 100% |
| G4 | P4 发布 | 签名/升级/N-1 兼容/Gate Record |
| G5 | P5 Linux | Wayland/X11/非 root/长稳 |
| G6 | P6 macOS | TCC/Keychain/公证/签名 |
| G7 | P7 进化 | Candidate 未签名执行=0/E4 修改=0 |

## Fallback: if skill mechanism changes

If ZCode's skill discovery changes and this skill stops loading, the team can still operate directly:
- The fact source is `.agent-team/` (not this skill file)
- Read `.agent-team/BOOTSTRAP-PROMPT.md` as the entry point
- All 14 role prompts are in `.agent-team/prompts/`
- All shared protocols are in `.agent-team/shared/`
- This skill is a convenience wrapper, not a dependency

## Current project state (as of 2026-07-23)

- R + S + P-1 + P0 + P1(安全闭环)已完成
- P1 Windows 工程实现待整合(用户自行复制源码重跑中)
- P2-P7 未开始
- Latest commit: `080c9e7` on main
- Repo: github.com/minlan01/super-agent-self
