# 安全事件响应手册 (Security Incident Response)

> 版本: P3
> 更新: 2026-08-03

## 1. 事件分类

| 级别 | 描述 | 响应时间 |
|---|---|---|
| P0-Critical | 数据泄露 / 未授权外部副作用 / 完全攻陷 | 立即 |
| P1-High | 越权访问 / Grant 伪造 / 租户隔离突破 | < 1h |
| P2-Medium | 审批绕过尝试 / 路径逃逸尝试 (被阻止) | < 4h |
| P3-Low | 可疑行为 / 配置错误 | < 24h |

## 2. 紧急停止

### 2.1 紧急停用

当前源码尚未实现 `zcode emergency-stop` 命令，也没有经过审计的 Grant/Lease 批量撤销 API。使用 [Emergency Disable Runbook](../runbooks/emergency-disable.md) 停止桌面与 control-core 进程、禁用高风险工具并执行有记录的 break-glass Grant 撤销。自动急停仍是 Windows GA 阻断项。

### 2.2 手动撤销 Grant

```python
# 通过 API 或直接 DB 操作 (仅 break-glass)
from packages.policy.grant_issuer import GrantIssuer
gi = GrantIssuer(db)
gi.revoke(grant_id)
```

### 2.3 锁屏 / 注销自动响应

- SessionMonitor 检测锁屏/注销/用户切换
- 自动撤销所有会话 Grant
- 停止新 dispatch

## 3. 事件响应流程

### 3.1 P0: 数据泄露

1. **遏制** (立即):
   - 执行 emergency-stop
   - 断开网络 (如果是远程攻击)
   - 撤销所有活跃 Grant + Lease

2. **证据保全**:
   - 不要重启服务 (内存证据)
   - 通过数据库只读副本或现有审计 API 导出事件；`zcode audit export` CLI 尚未实现
   - 复制 DB: `cp data/agent_platform.db /secure/location/`
   - 截图审批队列和 Effect 状态

3. **评估**:
   - 检查 Audit hash chain 完整性
   - 检查是否有跨租户数据访问
   - 检查是否有未授权的外部副作用 (Effect UNKNOWN_OUTCOME)

4. **恢复**:
   - Rotate SECRET_KEY
   - Rotate 所有 API Key
   - 按 [Database Corruption Runbook](../runbooks/db-corruption.md) 从已验证备份离线恢复
   - 审查所有 PENDING 审批请求

### 3.2 P1: Grant 伪造 / 越权

1. **遏制**: 撤销可疑 Grant, 暂停相关用户
2. **调查**:
   - 搜索审计日志中该 Grant 的所有使用记录
   - 检查 ToolGateway 拒绝日志 (是否有更多伪造尝试)
   - 检查 nonce store 是否被绕过
3. **修复**: 修补漏洞, Rotate 密钥, 重新部署

### 3.3 P2: 路径逃逸尝试

路径逃逸已被 path_safety 阻止,但需调查:
1. 哪个任务/工具触发了逃逸尝试
2. 是否是 LLM 生成的恶意计划 (提示注入)
3. 是否需要调整 workspace 边界或工具权限

## 4. 审计链验证

### 4.1 Hash Chain 检查

审计 hash-chain 验证 CLI 尚未实现。恢复或发布前必须通过现有审计测试和数据库证据核对；在专用 `verify-chain` 命令落地前，不得把本项标记为自动化通过。

### 4.2 Effect 完整性

```python
# 检查所有 Effect 是否有对应的 Receipt
from packages.execution.effect_journal import EffectJournal
ej = EffectJournal(db)
unknown = ej.get_unknown_outcomes(tenant_id="*")
# 每个 UNKNOWN_OUTCOME 都需要有对应的 dispatch_attempt 记录
```

## 5. 事件后行动

- [ ] 编写事件报告 (时间线、影响、根因、改进)
- [ ] 更新威胁模型
- [ ] 添加回归测试覆盖攻击路径
- [ ] 审查相关 ADR 是否需要更新
- [ ] 如有必要,发布安全补丁 (P4 签名更新流程)

## 6. 联系方式

- 内部安全团队: security@zcode.local
- 紧急: 参考 Enterprise Profile 配置中的 on-call 联系人
