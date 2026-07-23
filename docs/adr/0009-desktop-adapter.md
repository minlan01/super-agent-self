# ADR-009: Desktop Adapter

**Status:** Accepted
**Date:** 2026-07-22

## Context
spec §4.4 + G-09：桌面自动化需跨平台，Windows 首发。

## Decision
- **平台接口 + Windows UI Automation/Win32 优先**
- 坐标点击受限使用：必须先计算 UI digest 并验证未变
- DPI / 多屏 / UAC secure desktop 处理
- stale UI 状态返回 `STALE_UI_STATE`，不盲目点击

## Alternatives
- 纯坐标（pyautogui 裸用）：易误操作，无 stale 检测
- 纯视觉：性能差，依赖大模型

## Consequences
- P2 实现 WindowProvider Windows 版
- desktop.input 必须绑定 window_id + ui_digest + focus 检测

## Reconsideration
若 UI Automation 在某些应用失效（如游戏），评估视觉坐标兜底（标记为受限能力）。
