# ADR-010: 自托管网络边界

**Status:** Accepted
**Date:** 2026-07-22

## Context
spec §1.3 + §4.5：默认数据不离开设备，无外部入站。

## Decision
- **默认 loopback-only**（personal Profile），无外部入站
- self-hosted Profile：HTTPS 入口（Nginx）+ LAN/VPS
- hybrid Profile：设备**仅出站** mTLS，不开入站端口
- 远程访问启用必须单独 threat model + ADR

## Alternatives
- 默认对外开放：违反 spec §1.3「核心工作流不依赖厂商云控制面」
- UPnP 自动端口映射：安全风险

## Consequences
- personal Profile 的 Control API 只监听 127.0.0.1
- self-hosted Profile 的远程访问需显式配置 + mTLS

## Reconsideration
若 hybrid 设备在 NAT 后无法出站长连接，评估 relay server（独立 ADR）。
