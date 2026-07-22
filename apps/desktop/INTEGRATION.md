# Zcode Desktop Agent — 接入说明（P0.8）

**日期**: 2026-07-22
**状态**: P0 基线（基于 P-1 spike，待 P1 增强）

## 1. 目录定位

`apps/desktop/` 是 Zcode Desktop Agent 的 Tauri 2 桌面壳，负责：
- 渲染本地 UI（Vue/TS 前端）
- 启动并监督 Python Control Core sidecar（Nuitka standalone）
- 通过 Named Pipe 与 sidecar 双向通信
- 管理生命周期（健康检查、崩溃重启、Job Object 强清理）

**来源**: P-1 spike（`tauri-spike/`）→ P0.8 重命名 + 元信息更新。
**ADR**: ADR-001（Tauri 2 Accepted）、ADR-002（Nuitka sidecar Accepted）、ADR-022（GO）。

## 2. 与 control-core 的对接

```
apps/desktop/ (Tauri/Rust)
    │
    ├── 启动 → services/control-core (Nuitka 打包的 sidecar.exe)
    │           ↑
    ├── HTTP /health 轮询（127.0.0.1:9876）
    │
    ├── Named Pipe \\.\pipe\zcode-sidecar-spike → sidecar
    │   (nonce + PID 身份校验，spike 已实现)
    │
    └── 关闭 → Job Object 杀整个进程树
```

**当前状态（P0）**:
- ✅ 生命周期 4 项硬指标全部通过（spike 验证）
- ✅ sidecar 启动 + 健康检查 + IPC
- ⚠️ **sidecar 是 spike 版本**（`sidecar.py` 提供 /health + echo pipe），尚未接入 control-core 的真实业务 API
- ⚠️ IPC 端点固定（`zcode-sidecar-spike`），P1 改为 per-user + ACL

## 3. 构建

**sidecar 构建**（Windows）:
```powershell
cd services/control-core/scripts/nuitka-build
powershell -File build.ps1
# 产物: dist-final/sidecar.dist/sidecar.exe (20.4 MB)
```

**Tauri 构建**（Windows）:
```powershell
cd apps/desktop
npm ci
npm run tauri -- build --bundles nsis --ci
# 产物: src-tauri/target/release/bundle/nsis/*.exe
```

详见 P-1 RESULT.md（`docs/spike/p1-2026-07-22.md`）。

## 4. P1 待接入项

| 项 | 说明 | 依赖 |
|---|---|---|
| sidecar 替换为真实 control-core | 用 Nuitka 打包 `apps/api_server/main.py` 而非 spike 的 `sidecar.py` | P1 IPC |
| Named Pipe SID ACL | spike 用 nonce+PID，P1 加 Windows SID ACL | ADR-003 |
| 版本协商 | sidecar 与 shell 的协议版本握手 | P0.1 SCHEMA_VERSION |
| 单实例策略 | 防止多实例端口冲突 | ADR-017 |
| UI 接入真实读模型 | 替换 spike 的 demo UI 为 operator-console 组件 | P3 |

## 5. 测试

spike 的 5 个 PowerShell 测试脚本（`tests/`）：
- `measure_startup.ps1` — 冷启动计时
- `measure_ipc_v2.ps1` — IPC P95
- `run_artifact_suite.ps1` — 综合测试
- `test_authenticode.ps1` — 签名验证
- `test_lifecycle.ps1` — 生命周期（kill/重启）

**CI 集成**: P1 加 Windows runner 跑这些脚本（当前 CI 只跑 Python 测试）。
