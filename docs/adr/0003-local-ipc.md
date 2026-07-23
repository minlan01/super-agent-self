# ADR-003: 本地 IPC

**Status:** Accepted
**Date:** 2026-07-22

## Context
Desktop Shell (Tauri) 需要与 Python Control Core sidecar 双向通信。P-1 spike 已验证 Named Pipe + nonce/PID（P95 2.997ms）。spec §4.4 + §4.2 要求对端身份校验、防重放、协议版本协商。

## Decision
- Windows: **Named Pipe + SID ACL**（仅当前用户 SID 可连接）+ nonce + 协议版本协商
- Linux: Unix Domain Socket + peer creds (SO_PEERCRED)
- macOS: UDS / XPC + peer identity
- 消息大小上限 10MB；速率限制 100 req/s；重放/乱序/暴力请求拒绝并审计

## Alternatives
- Tauri postMessage：与 Nuitka sidecar 架构冲突（sidecar 不在 WebView 内）
- localhost HTTP：无 peer 身份校验，任何本机进程可调用

## Consequences
- P1 实现 Windows SID ACL（spike 的 nonce/PID 基础上加 SID）
- IPC schema 复用 P0.1 的 protocol v1（版本协商靠 SCHEMA_VERSION）

## Reconsideration
若 Win10 某些场景 SID ACL 不可用（如 Service 账户），评估降级到 nonce+PID+端口绑定。
