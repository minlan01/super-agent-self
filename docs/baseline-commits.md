# 迁移基线 commit 锚点

**生成日期**: 2026-07-21
**用途**: 作为 v1.1 规格 §2.5 存量资产清理（S 阶段）的追溯基准。vendor 时若发现冲突，回到此锚点对比上游变更。

| 仓库 | commit hash | branch | 最后提交说明 | 在新仓中的角色 |
|------|-------------|--------|-------------|----------------|
| myself-agent | `67848f768ce13c76cb31ab40224373378f7a8d49` | main | feat: v3.13.0 production-grade deep optimization (round 5 audit) | vendor 到 `services/control-core`，作为唯一写模型底座 |
| agent_tianshu | `7c89f075e8158d95a74a0f15a63dc4378cd5dbb3` | main | docs: rewrite README with upstream project, API reference, and dev guide | 仅提取概念到 `adapters/tianshu-concept/` |
| more_agents | `b9eca692219f5bdb04e40c8fa720dce82688a1f3` | master | feat: initial commit - Myagent-Admin multi-agent collaboration platform | 仅 `unified-admin/` 子目录取前端 src/，其余归档 |
| more_agents/unified-admin | `1581ea45977f897b94a9200ae52490b5a3f6ebd9` | optimization-and-integration | Phase 3: P1 shallowRef optimization - 6 Record patterns converted | vendor 到 `apps/web-console-src/`（不含 server/） |
| super-agent-self | n/a（.git 空壳） | — | — | S.1 将 `git init` 重建为主干 |

## vendor upstream 同步约定

S 阶段完成后，以下仓库保留作为 vendor upstream，可通过 `git remote add upstream <path>` 同步未来更新：

- `myself-agent` → `services/control-core` 的 upstream（见 `services/control-core/VENDOR.md`）
- `more_agents/unified-admin` → `apps/web-console-src` 的 upstream（待 D 阶段建立）
- `agent_tianshu` → 仅作概念参考，无 vendor 关系

## 复现命令

```bash
for r in myself-agent agent_tianshu more_agents more_agents/unified-admin; do
  cd /home/minlan/Agents/$r
  echo "$r: $(git rev-parse HEAD) ($(git rev-parse --abbrev-ref HEAD))"
  cd /home/minlan/Agents
done
```
