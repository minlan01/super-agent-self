# 全生命周期发布门禁

## G0：任务准入

必须满足：

- 用户结果、范围、风险等级和 Owner明确。
- 已生成完整 TASK-PACKET。
- 允许路径与禁止路径明确。
- 需要的治理和审查 Agent已路由。

失败动作：返回 Orchestrator补全，不进入实现。

## G1：需求与领域闭合

必须满足：

- UserStory描述可观察业务结果，不只描述技术动作。
- 状态、参与者、权限和异常路径明确。
- 每条验收标准可由测试或运行证据验证。
- 术语在文档、schema、代码和 UI中含义一致。

失败动作：Product & Domain Lead修订；涉及状态所有权时升级 Architecture Governor。

## G2：架构与安全闭合

必须满足：

- 只有一条规范执行链。
- 模块 Interface、状态 Owner、事务、错误模式和恢复路径明确。
- threat model覆盖主体、资产、信任转换和攻击路径。
- Authorization、Approval、Grant、Lease、Effect、Artifact和 tenant scope绑定完整。
- schema能够表达设计承诺的字段和约束。
- 迁移、部署和回滚方案与设计一致。

失败动作：禁止实施；由治理 Agent裁决冲突并记录 ADR。

## G3：实现完成

必须满足：

- diff仅位于 allowed paths，且无无关重构。
- 代码、schema、测试、配置和规范文档同步。
- 无旧执行旁路、兼容分支或公开接口重新引入已关闭风险。
- 静态检查、类型检查、focused tests和相关回归通过。
- 实施 Agent提交完整 HANDOFF。

失败动作：返回对应实施 Agent一次；再次失败由 Orchestrator重新规划。

## G4：集成、故障与安全验证

必须满足：

- 正常路径、拒绝路径、并发和重试测试通过。
- Worker崩溃、网络超时、ACK丢失、重复消息和 stale fencing测试通过。
- 授权重放、自审、scope篡改、跨租户、恶意 Artifact和密钥误用测试通过。
- 数据迁移支持 upgrade、backfill、校验、cutover和 reviewed rollback path。
- 遥测能区分拒绝、失败、待对账和真实成功。

失败动作：任何 P0/P1 阻断发布。

## G5：发布就绪

必须满足：

- 构建产物可复现，依赖和镜像来源可追溯。
- 密钥、证书、配置和 Profile符合生产策略。
- 容量、超时、重试、熔断、队列背压和降级经过验证。
- 备份恢复演练和回滚触发条件明确。
- 变更记录、操作手册、告警和 Runbook完整。
- Independent Release Reviewer给出 `PASS`。

失败动作：保持上一稳定版本，不执行生产切换。

## G6：迁移与生产切换

必须按顺序满足：

1. 预检查和备份恢复点确认。
2. shadow read或等价一致性验证。
3. drain并阻止新长任务进入旧系统。
4. 数据库级硬 write fence。
5. 终止旧连接和未提交事务。
6. final delta导入。
7. 行数、业务聚合、checksum和关键抽样校验。
8. 原子路由切换。
9. 观察窗口和错误预算监控。
10. 达到回滚阈值时执行已演练的回滚。

任何一步失败都停止后续步骤。不得在缺少状态迁移协议时迁移运行中的 Run。

## G7：发布关闭

必须满足：

- 观察窗口完成，SLI和错误预算在阈值内。
- 没有未对账 Effect、孤儿 Lease、悬空 Grant或 quarantine绕过。
- 发布证据归档并能从任务追溯到生产版本。
- 临时开关、兼容路径和提升权限已撤销。
- 事故和偏差形成复盘或后续任务。

只有 G7 完成后，Orchestrator才能把发布标为最终落地完成。

