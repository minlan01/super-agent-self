# ADR-004: 本地数据库

**Status:** Accepted
**Date:** 2026-07-22

## Context
spec §1.3 三个 Profile 需要不同数据层，但业务状态机必须共用。personal Profile 不许依赖 Docker/PostgreSQL。

## Decision
- personal Profile: **SQLite WAL** + 字段级加密（AES-256-GCM for secret 字段）
- self-hosted/hybrid Profile: **PostgreSQL 16**
- 共用 `StorageProfile` 抽象（ADR-011 跨方言适配）
- 凭据不入 DB（只存 SecretRef，见 ADR-005）
- 备份: `zcode backup create/restore`；崩溃恢复演练必过

## Alternatives
- 纯 PostgreSQL：personal Profile 终端安装即用不成立（依赖 Docker）
- LevelDB / Redis：无 SQL，业务查询复杂度高

## Consequences
- ADR-011 必须解决 SQLite 无 LISTEN/NOTIFY 的 Outbox 实现（应用层轮询）
- 字段加密密钥由 ADR-005 SecretStore 提供

## Reconsideration
若 SQLite 并发瓶颈显现（>50 并发写），self-hosted Profile 切 PG（已设计）。
