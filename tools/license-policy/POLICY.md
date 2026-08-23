# 依赖许可证政策(P4 阻塞项 #9)

## 政策

| 生态 | 工具 | 白名单 | 执行点 |
|---|---|---|---|
| Rust | cargo-deny | `tools/license-policy/deny.toml` | CI `license-policy` job |
| Python | pip-license | `tools/license-policy/check_licenses.py` | 同上 |
| Node | npm ls --prod | 同一脚本 | 同上 |

**原则**:MIT/Apache-2.0/BSD/ISC/Zlib/MPL-2.0 等宽松许可自动通过;
GPL/AGPL/SSPL 等著佐权默认拒绝,需法律评审后加入白名单并记录理由。
无许可证(unlicensed)的依赖一律拒绝(fail closed)。

## 本地执行

```bash
# Rust(先 cargo install cargo-deny)
cd services/control-core/scripts/nuitka-build  # 或任何含 Cargo.lock 的目录
cargo deny --config ../../../tools/license-policy/deny.toml check licenses

# Python + Node
python tools/license-policy/check_licenses.py
```

## CI 卡点

`.github/workflows/ci.yml` 的 `license-policy` job 任一违规即失败。

## 例外审批记录

每个加入白名单的例外必须在此登记:

| 日期 | 依赖 | 许可 | 理由 | 批准人 |
|---|---|---|---|---|
| 2026-08-22 | (初始基线) | — | pip-audit/npm audit/RustSec 均 0 漏洞;扫描全绿 | minlan |

> 添加例外时同步更新 `deny.toml` 的 `exceptions` 或脚本的 `APPROVED`,
> 并在 CI 证据(artifacts)中保留当次完整扫描输出。
