# ADR-008: Shell 隔离

**Status:** Accepted
**Date:** 2026-07-22

## Context
spec §4.2 + G-03：Shell/特权工具不得在 API 进程上下文运行。P-1 spike 已验证 Job Object。

## Decision
- **独立低权限 Runner + Windows Job Object**（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`）
- 受控工作目录（仅 workspace 可写）
- 资源限制：CPU / 内存 / 进程数 / 超时 / 输出大小
- 网络隔离：Shell 默认断网（egress allowlist 按 Workspace 配置）

## Alternatives
- AppContainer：细粒度但 Win 版本兼容性问题、spike 未验证
- gVisor/Kata：非 Windows

## Consequences
- P2 实现 ProcessSandbox Windows 版（platform/windows/）
- Job Object 保证进程树整体可终止（spike 已证）

## Reconsideration
若需细粒度网络/文件系统 ACL，评估 Job Object + AppContainer 组合（P2 末评估）。
