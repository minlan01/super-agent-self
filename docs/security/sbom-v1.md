# SBOM（软件物料清单）v1

**生成日期**: 2026-07-22
**适用版本**: P0 完成
**格式**: 机器可读 JSON + 本索引文档

## 1. 组件清单

| 组件 | 语言 | SBOM 文件 | 包数 |
|---|---|---|---|
| control-core | Python | `sbom-control-core.json` | 68（17 direct + 51 transitive） |
| operator-console | JavaScript | `sbom-operator-console.json` | 52（32 deps + 20 devDeps） |
| desktop-spike | Rust + TypeScript | `apps/desktop-spike/src-tauri/Cargo.lock` | 见 Cargo.lock |

## 2. 直接依赖（control-core）

```
fastapi>=0.110,<1.0     uvicorn              sqlalchemy<3
alembic                 pydantic>=2.0        pydantic-settings
python-dotenv           structlog            bcrypt
typer                   click                rich
httpx                   pytest               pytest-asyncio
```

## 3. 许可证策略

| 许可证 | 允许? | 说明 |
|---|---|---|
| MIT / BSD-2/3 / Apache-2.0 | ✅ | 宽松许可证 |
| LGPL / MPL-2.0 | ✅ | 弱 copyleft（file-level） |
| GPL / AGPL | ❌ | 强 copyleft，阻断 |
| CC BY-NC-SA | ❌ | 商业风险（spec §2.1.1 ClawLibrary 资产） |
| Unlicense / WTFPL | ⚠️ | 公共领域，但需复核 |

**P0 状态**：未做全量许可证扫描（`pip-audit` / `pip-licenses` 待 P1 CI 集成）。

## 4. 漏洞扫描状态

| 工具 | 范围 | 状态 | 严重度阈值 |
|---|---|---|---|
| `pip-audit` | Python | P1 CI 集成 | Critical/High=0 |
| `npm audit` | Node | P1 CI 集成 | Critical/High=0 |
| `bandit` | Python SAST | P0 已装 | Medium+报告 |
| `semgrep` | 多语言 SAST | P1 集成 | — |
| `trivy` / `grype` | Docker 镜像 | P3（无镜像阶段） | — |

**P0 状态**：bandit 已装但未跑入 CI；pip-audit/npm audit 待 P1。

## 5. 供应链完整性（spec v3 §4A）

| 控制项 | 状态 |
|---|---|
| 锁文件（requirements.lock / Cargo.lock / package-lock.json） | ✅ Cargo.lock + package-lock.json 已入仓；Python 用 pyproject + pip cache |
| 可重复构建 | ⚠️ Python 无 lock（P1 用 pip-compile 生成） |
| 签名标签 | P4 |
| execution_supply_chain_digest | v3 §4A schema（P0.1 已定义），P2 落地到 Grant |

## 6. 已知风险依赖

| 依赖 | 版本 | 风险 | 处置 |
|---|---|---|---|
| `pyautogui` | latest | desktop.click 实现，需 Job Object 隔离（E-03） | P2 |
| `better-sqlite3` | — | 已在 S.4 vendor 时随 server/ 删除 | ✅ |
| `node-pty` | — | 已在 S.4 vendor 时随 server/ 删除 | ✅ |
