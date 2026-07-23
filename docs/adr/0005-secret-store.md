# ADR-005: Secret 存储

**Status:** Accepted
**Date:** 2026-07-22

## Context
API Key / token / 刷新令牌需存储。spec §11 要求 secret 不进入普通数据库和日志。

## Decision
- **OS 原生密钥环**：Windows Credential Manager/DPAPI、Linux Secret Service (libsecret)、macOS Keychain
- DB 只存 `SecretRef`（key_id + label + mask，无明文）
- 无密钥环时 **fail closed**（明确错误，绝不降级到明文）
- 凭据轮换: `rotate(ref, new_plaintext)` 原子操作（删旧 + 存新）

## Alternatives
- 加密 SQLite：跨平台一致，但密钥管理弱于 OS 原生（密钥存哪？）
- .env 明文：违反 spec §11，本机其他用户可读

## Consequences
- P1 实现 Windows Credential Manager 集成（platform/windows/）
- 字段加密密钥（ADR-004）也存这里

## Reconsideration
若 headless Linux 无 gnome-keyring，评估 encrypt-config + machine-id 绑定（记录为降级路径）。
