# ADR-007: 更新机制

**Status:** Accepted
**Date:** 2026-07-22

## Context
spec §1.2 要求签名更新 + N-1 回退 + 防降级。ADR-006 选定 NSIS。

## Decision
- **签名 manifest + 双阶段安装 + N-1 回退**
- `min_previous_version` 防降级
- 断电恢复（原子更新，旧版保留至新版验证通过）
- 渠道隔离：stable / beta / internal
- 离线更新支持（手动下载签名包）

## Alternatives
- Sparkle：macOS only
- 自动更新无签名：违反 spec §9（未签名执行 = 0）

## Consequences
- P4 实现签名 manifest 生成 + staged rollout
- 回退保留 N-1 安装目录

## Reconsideration
若 Tauri updater 在 Win10 表现不佳，评估自研 NSIS updater。
