# ADR-006: Windows 安装包

**Status:** Accepted
**Date:** 2026-07-22

## Context
spec §1.2 要求签名安装 + N-1 回退 + 数据保留。P-1 spike 已验证 NSIS 全链路。

## Decision
- **NSIS 签名 exe**，`currentUser` 安装模式（不需管理员）
- 静默 WebView2 `downloadBootstrapper` 模式
- Authenticode 签名 + 时间戳（P4 生产证书）

## Alternatives
- MSIX：Microsoft 现代格式，但打包复杂、WebView2 集成未验证、企业分发需 sideload
- MSI：传统企业格式，与 NSIS 无明确优势

## Consequences
- 复用 P-1 spike 的 NSIS 配置（tauri.conf.json bundle.windows.nsis）
- P4 加生产证书签名 + 时间戳

## Reconsideration
若企业客户强制要求 MSIX（Store 分发），评估 MSIX + NSIS 双格式发布。
