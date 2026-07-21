# Vendor 同步流程（myself-agent → control-core）

此目录是 `myself-agent` 的 vendor 副本。**不带 git 历史**（规避上游可能的杂质），通过定期 rebase 同步上游更新。

## Vendor 锚点

- **源仓库**: `/home/minlan/Agents/myself-agent`
- **源远程**: `git@github.com:minlan01/myself-agent.git`
- **Vendor 时的 HEAD**: `67848f768ce13c76cb31ab40224373378f7a8d49`（v3.13.0 production-grade deep optimization, round 5 audit）
- **Vendor 日期**: 2026-07-21
- **规格依据**: v1.1 §2.1.1 + ADR-012

## 已剔除的项（vendor 时 rsync exclude）

- `.git/` — 不带历史
- `.env` / `.env.*`（保留 `.env.example`）— 凭据不入仓
- `__pycache__/` / `*.pyc` / `.pytest_cache/` / `.ruff_cache/` / `.venv/` — 编译和工具缓存
- `node_modules/` / `dist/` — 前端构建产物
- `data/*.sqlite` / `data/*.db` / `data/*.sqlite3` — 运行时数据库
- `workspace/` — 运行时工作区
- `controlled_agent_platform.egg-info/` — pip 构建产物（vendor 后已删）
- `data/cron/jobs.json` / `data/backups/*` — 运行时数据（vendor 后已清）

## 同步上游更新

当 `myself-agent` 上游有值得同步的更新时（父仓已配置 `upstream` remote 指向本地 myself-agent 仓库）：

```bash
cd /home/minlan/Agents/super-agent-self

# 1. fetch 上游最新
git fetch upstream

# 2. 用 diff 对比上游与本地 vendor 副本的差异（vendor 不带 git 历史，用 diff -r 对比）
diff -r --brief services/control-core/ /home/minlan/Agents/myself-agent/ \
  --exclude=.git --exclude=.env --exclude=__pycache__ --exclude=.venv \
  --exclude=node_modules --exclude=dist --exclude=data --exclude=workspace \
  --exclude='*.pyc' --exclude='*.egg-info' --exclude=.pytest_cache --exclude=.ruff_cache

# 3. 对每一处差异，决定吸收还是忽略：
#    - 吸收：rsync 单个文件/目录过来
#    - 忽略：明确在 VENDOR.md 记录原因
```

## 父仓提交

```bash
cd /home/minlan/Agents/super-agent-self
git add services/control-core/
git commit -m "vendor(myself-agent): sync upstream @<上游 commit-hash>"
```

## 冲突优先级

当上游与本仓改造冲突时：
- **control-core 内部改动优先**（本仓的 v3 契约改造、Profile 抽象、ToolGateway 等不退让）
- 上游的新功能、bug fix、依赖升级可吸收
- 上游对 `.env.example` / `docker-compose.yml` / `data/` 的改动一律忽略

## upstream 初始化（已完成，2026-07-21）

父仓已添加 upstream remote：

```bash
cd /home/minlan/Agents/super-agent-self
git remote add upstream /home/minlan/Agents/myself-agent
git fetch upstream --depth=1
```

后续只需 `git fetch upstream` 即可同步上游最新 commit 引用。
