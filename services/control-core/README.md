# Controlled Agent Platform

> **上游项目**: 本项目融合了 [OpenClaw](https://github.com/openclaw/openclaw) 的多 Agent 编排、策略引擎与工具注册架构，以及 [Hermes](https://github.com/nicepkg/hermes) 的前端管理界面、实时通信与监控体系设计，在此基础上独立完成了全部 32 个 Sprint 的工程实践。

---

## 项目介绍

**Controlled Agent Platform** 是一套面向企业与个人场景的**可控自进化 Agent 平台**。与传统对话式 AI 不同，它将 LLM 严格限制在「规划」角色——输出结构化的 JSON 执行计划，由独立的策略引擎逐一审核、授权后，再交由执行器落地。每一步操作都可审计、可回滚、可拦截。

### 设计哲学

平台围绕六条不可妥协的原则构建：

| 原则 | 含义 |
|------|------|
| **LLM 只规划，不执行** | 大模型输出结构化 JSON Plan，绝不直接调用工具或修改系统 |
| **策略引擎是唯一闸门** | 每个执行步骤必须通过 Policy 的安全审查，无例外 |
| **执行需授权令牌** | Executor 仅在持有 Capability Token 时运行，防止越权 |
| **记忆可参考，不可越权** | Memory 服务提供上下文，但不能绕过策略链 |
| **技能经审批方可复用** | 从 candidate 到 stable 的晋升需要人工审核批准 |
| **双版本共享核心** | 企业版（安全合规）与个人版（语音/桌面控制）共用同一套 Agent Core |

### 系统架构

```
┌─────────────────────────────────────────────────┐
│                  用户 / 管理员                     │
├────────────────────┬────────────────────────────┤
│  Enterprise Web    │   Personal Jarvis           │
│  (Vue 3 前端)      │   (语音 + 桌面控制)           │
├────────────────────┴────────────────────────────┤
│              FastAPI API Layer                    │
│  REST · GraphQL · WebSocket · SSE                │
├─────────────────────────────────────────────────┤
│              Agent Core (共享层)                   │
│  ┌──────────┬──────────┬──────────┬───────────┐ │
│  │ Planner  │ Policy   │ Executor │ Memory    │ │
│  │ 规划器    │ 策略引擎  │ 执行器    │ 记忆服务   │ │
│  ├──────────┼──────────┼──────────┼───────────┤ │
│  │ Skills   │ Audit    │ Eval     │ LLM GW    │ │
│  │ 技能系统  │ 审计追踪  │ 评估系统  │ 大模型网关  │ │
│  └──────────┴──────────┴──────────┴───────────┘ │
├─────────────────────────────────────────────────┤
│              数据层                               │
│  SQLAlchemy ORM · 24 表 · Alembic 迁移           │
│  SQLite (开发) → PostgreSQL (生产)               │
├─────────────────────────────────────────────────┤
│              基础设施                              │
│  限流 · 缓存 · Prometheus · Docker · nginx       │
└─────────────────────────────────────────────────┘
```

### 开发历程

本项目由 **赤夜冥岚** 主导开发，以 GLM-5.1 为底层推理模型、Claude Code 协助工程实现，全程采用 **Autopilot + Ultrawork** 多 Agent 并行开发模式高效推进。Autopilot 与 Ultrawork 是赤夜冥岚基于 OMC (oh-my-claudecode) 与 OMO (oh-my-opencode) 自研的编排扩展层，负责需求拆解、Agent 调度与并行执行，相关项目均可在 [minlan01 的 GitHub 仓库](https://github.com/minlan01) 中查阅。

项目历经 41 个 Sprint 的持续迭代，每个阶段均保持完整的测试覆盖——从最初的 281 个测试稳步增长至 **2104 个后端测试 + 231 个前端测试，全部通过、零失败**：

| 阶段 | Sprint | 核心交付 | 测试数 |
|:----:|:------:|---------|:------:|
| 骨架搭建 | 1-3 | 数据库 + ORM + 规划器 + 策略引擎 + 执行器 | 281 |
| 核心能力 | 4-8 | 记忆 + 技能 + 认证 + Vue 管理界面 + Docker | 530 |
| 个人版 | 9-12 | 版本管理 + 个人工具 + 提醒 + 聊天意图路由 | 588 |
| 多模态 | 13-15 | 语音识别/合成 + 视觉 OCR + 桌面控制 + 评估 | 658 |
| 生产化 | 16-19 | 限流 + WebSocket + 定时任务 + MCP + 多 LLM | 653 |
| 安全加固 | 20-23 | HMAC 密钥 + CORS + DB 索引 + Alembic + CI/CD | 836 |
| 企业级 | 24-27 | 认证 UI + Prometheus + 国际化 + 分析面板 | 1181 |
| 功能完善 | 28-30 | E2E 测试 + GraphQL + 任务 DAG + 通知持久化 | 1460 |
| 架构扩展 | 31-32 | 通知 WS + 缓存抽象 + Redis + Grafana + 退避重连 | 1817 |
| 质量提升 | 33 | 测试隔离修复 + Redis 集成测试 + WS Token 刷新 + OpenAPI 增强 | 1683 |
| 前端优化 | 34 | 全量类型化 API + Composable 提取 + ECharts Tree-shaking + 双后端架构 | 1683+231 |
| 智能对话 | 35 | LLM 真实对话 + 多国产模型（GLM/Kimi/Doubao/Qwen）+ Failover 自动切换 + WS 代理 | 1683+231 |
| 企业安全 | 36 | RBAC 权限控制 + OIDC SSO + 4 角色 52 权限 + 22 路由守卫 + 权限管理 UI | 1914+231 |
| 高级分析 | 37 | 实时指标 + 成本分析 + 技能基准 + 异常检测 + 5 新 API + LLMCostRecord 持久化 | 2028+231 |
| 语音视觉 | 38 | 云端 STT + 中文 TTS + LLM 视觉理解 + Vision API 路由 + OCR 端点 | 2044+231 |
| 桌面自动化 | 39 | 文件系统工具 + 窗口管理器 + Desktop API 路由 + RBAC 守卫 | 2064+231 |
| 多Agent协作 | 40 | SubAgent 执行修复 + Agent Bus 消息 + 共识投票 + Agent API | 2081+231 |
| 插件系统 | 41 | Plugin SDK + 动态加载 + 热重载 + 沙箱执行 + Plugin API | 2104+231 |

**技术栈**

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.x / Pydantic v2 |
| 数据库 | SQLite → PostgreSQL，Alembic 迁移管理 |
| LLM | DeepSeek（主）/ GLM / Kimi / Doubao / Qwen / OpenRouter / OpenAI / Anthropic / Gemini / Ollama / llama.cpp |
| 前端 | Vue 3 + Vite + Element Plus（按需导入）+ Pinia + vue-i18n + ECharts（tree-shaken）|
| 监控 | Prometheus (纯 Python) + Grafana |
| 缓存 | 抽象 CacheBackend + MemoryCache + Redis 适配器 |
| 测试 | pytest (后端) + Vitest (前端) |
| 部署 | Docker Compose + nginx + 监控栈 |

---

## 快速开始

```bash
# 安装依赖
pip install -e ".[dev,browser,docx]"

# 初始化数据库
python scripts/init_db.py

# 填充演示数据（可选）
python scripts/seed_demo_data.py

# 启动 API 服务
python scripts/run_api.py

# 启动前端管理界面（可选）
cd apps/enterprise_admin_web && npm install && npm run dev
```

## 项目目录

```
packages/
  agent_core/    # 编排器、状态机、Schema、子Agent委派
  db/            # 数据库 Session、ORM（24表）、Repository
  llm_gateway/   # LLM 网关（DeepSeek / Mock / OpenRouter / OpenAI）+ 智能模型路由
  planner/       # 任务规划服务（强制 JSON 输出）
  policy/        # 安全策略引擎（7项检查）、Capability Token、命令安全
  executor/      # 工具执行器（13 工具）+ 沙箱 Bash + Web 搜索
  memory/        # 长期记忆服务 + 时间衰减检索 + 上下文压缩器
  skills/        # 技能提炼/复用/审批 + 自动降级
  evaluation/    # 任务评估 + 回归检测
  observability/ # 结构化 JSON 日志 + 审计追踪
  cron/          # 定时任务（链式调度 + 拓扑排序 + 环检测）
  mcp/           # MCP Client（stdio/HTTP）+ 工具适配器
  middleware/    # 限流中间件（热加载配置）+ Prometheus 指标
  cache/         # 缓存抽象层（MemoryCache + Redis 适配器）
  auth/          # 用户认证（bcrypt + HMAC-JWT）+ RBAC 权限控制 + OIDC SSO
  notification/  # 通知服务（内存 + DB 双写）+ WebSocket 推送
  graphql/       # GraphQL 查询层（strawberry-graphql）
  vision/        # OCR + 截屏 + 屏幕捕获
  voice/         # 语音识别/合成/命令路由
  personal_context/  # 个人上下文服务 + 提醒 + 偏好管理
  plugins/       # 插件 SDK + 动态加载 + 热重载
  config/        # pydantic-settings 配置管理
apps/
  api_server/           # FastAPI 后端（29 路由模块）
  enterprise_admin_web/ # Vue 3 + Element Plus 管理界面（21 视图 + i18n + 暗色主题 + typed API + 双后端）
monitoring/             # Prometheus + Grafana 监控栈
configs/                # YAML 配置（13 配置文件）
tests/                  # pytest 测试（2104 后端 + 231 前端 = 2335 测试）
```

| 模块 | 路径前缀 | 功能 |
|------|---------|------|
| 认证 | `/api/v1/auth` | 注册、登录、当前用户、SSO 单点登录 |
| RBAC | `/api/v1/rbac` | 角色/权限管理、用户授权、RBAC 种子 |
| 视觉 | `/api/v1/vision` | 图像理解分析、OCR 文字提取 |
| 桌面 | `/api/v1/desktop` | 文件系统操作、窗口管理、屏幕截图 |
| Agent | `/api/v1/agents` | 多Agent状态、消息、共识投票 |
| 插件 | `/api/v1/plugins` | 插件发现、加载、激活、热重载 |
| 任务 | `/api/v1/tasks` | CRUD、执行、取消、重试、批量创建、DAG |
| 记忆 | `/api/v1/memory` | 搜索、列表、详情、禁用、删除 |
| 技能 | `/api/v1/skills` | 列表、详情、审批、禁用、回滚 |
| 审计 | `/api/v1/audit` | 审计事件查询 |
| 审批 | `/api/v1/approvals` | 列表、详情、通过/拒绝 |
| 个人版 | `/api/v1/personal` | 提醒、上下文、偏好 |
| 版本 | `/api/v1/editions` | 版本列表和配置 |
| 聊天 | `/api/v1/chat` | 对话式交互（意图识别 + 自动路由）|
| 对话 | `/api/v1/conversations` | 对话历史查询和删除 |
| 定时任务 | `/api/v1/cron` | CRUD、链式调度、环检测 |
| 语音 | `/api/v1/voice` | 语音识别、合成、命令路由 |
| 导出 | `/api/v1/export` | 任务/记忆/审计 导出 JSON/CSV |
| 健康 | `/api/v1/health` | 就绪探针、平台指标 |
| 分析 | `/api/v1/analytics` | 趋势图、成功率、日期聚合 |
| 管理 | `/api/v1/admin` | 备份/恢复、限流配置 |
| GraphQL | `/api/v1/graphql` | GraphiQL 查询面板 |
| 通知 | `/api/v1/notifications` | 列表、未读计数、标记已读 |
| 指标 | `/api/v1/metrics/prometheus` | Prometheus 指标导出 |
| WebSocket | `/ws/tasks/{id}` | 实时任务进度推送（支持 Token 刷新） |
| WebSocket | `/ws/chat` | 双向聊天 + 意图路由（支持 Token 刷新 + 过期检测） |
| WebSocket | `/ws/notifications` | 专用通知推送（支持 Token 刷新 + 过期检测） |

## 测试

```bash
# 运行全部后端测试
pytest

# 仅运行单元测试
pytest tests/unit/ -m unit

# 仅运行集成测试
pytest tests/integration/

# 运行前端测试
cd apps/enterprise_admin_web && npx vitest run
```

## 配置

所有配置在 `configs/` 目录下：

- `app.yaml` — 应用基础配置、CORS、工作区
- `models.yaml` — LLM 模型配置
- `tools.yaml` — 工具注册和风险等级
- `policy.yaml` — 安全策略管道
- `memory.yaml` — 记忆类型和检索参数
- `skills.yaml` — 技能降级规则
- `cron.yaml` — 定时任务调度器
- `search.yaml` — 搜索引擎配置
- `mcp.yaml` — MCP 服务器配置
- `cache.yaml` — 缓存配置（memory / redis）
- `rate_limits.yaml` — API 限流配置（支持热加载）
- `rbac.yaml` — RBAC 权限配置（角色/权限/路由守卫/SSO）
- `editions/` — 版本特定配置（企业版/个人版）

## 监控

Prometheus + Grafana 监控栈：

```bash
# 启动监控栈
docker compose -f monitoring/docker-compose.monitoring.yml up -d

# 访问
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3001 (admin/admin)
```

Dashboard 包含 8 个面板：HTTP 请求速率、延迟百分位（p50/p95/p99）、任务完成率、活跃 WebSocket 连接、活跃 DB 连接、HTTP 错误率（含告警）、请求热力图、Top 10 端点。

## 安全特性

- RBAC 权限控制（4 角色 + 52 权限 + 22 资源 + TTL 缓存）
- OIDC SSO 单点登录（PKCE + nonce + JIT 用户创建）
- Capability Token（HMAC-SHA256 签名，环境变量密钥）
- 用户认证（bcrypt 密码哈希 + HMAC-JWT 令牌）
- 7 项安全策略检查（风险评估、命令拦截、路径遍历防护）
- 全局异常处理（隐藏内部信息）
- IP 限流（滑动窗口 + 热加载配置 + 10K 客户端上限）
- 审计追踪（所有操作可追溯，含注册/登录审计）
- 统一危险命令正则（22+ 模式 + Unicode 规范化）
- ECharts XSS 防护（tooltip sanitize）
- 生产环境 API 文档自动禁用
- SECRET_KEY 生产环境强制检查（默认值拒绝启动）
- MCP 子进程环境变量过滤（敏感变量不泄露给子进程）
- Docker 资源限制（CPU/内存配额）
- 监控镜像版本锁定（消除 :latest 不可复现风险）
- Python 依赖版本上限约束（防止主版本不兼容）

## 版本历史

- **v3.13.0** — 生产级深度优化（第5轮审查）：structlog contextvars 请求级结构化日志 + 全局异常处理器（ErrorResponse 统一格式 + request_id 关联 + 内部信息脱敏）+ asyncio.to_thread 阻塞卸载（Whisper/OCR/pyttsx3/os.unlink）+ asyncio.gather 并发 WebSocket 广播 + SQLAlchemy 批量操作（add_all + 单次 flush 替代 N+1 写入）+ DAG 环检测迭代 BFS（WHERE IN 逐层扩展替代全表加载）+ Redis 批量删除（500 键/批）+ 聊天消息懒加载（ORDER BY DESC LIMIT 替代全量切片）+ 路径遍历 403 语义修正 + 全项目 logger.exception 替换（15+ 处丢失堆追踪修复）+ API 错误信息脱敏（6 处内部信息泄露修复）+ DB 索引补全（4 组高频查询索引）+ Alembic 迁移（inspector 幂等守卫）+ .gitignore 完善 — 457+ unit/integration tests

- **v3.12.0** — 生产级优化（4轮深度审查）：SQLAlchemy 2.0 全面迁移（消除全部 db.query() 遗留用法）+ Session 线程安全修复（memory_service 跨线程合并）+ asyncio.gather 异常处理 + WebSocket 连接竞态修复 + AgentBus 消息日志快照安全 + CronScheduler asyncio.run 嵌套修复 + SSO/RBAC SQLAlchemy 2.0 迁移 + User.sso_id unique 约束 + 注册/登录审计日志 + RBAC 分页 + SECRET_KEY 生产环境启动检查 + Docker 健康检查统一（/api/v1/health/ready）+ nginx 健康检查 + 依赖版本上限锁定 + 监控镜像版本锁定 + MCP 子进程环境变量过滤 + Docker 资源限制 + Redis 异常日志 + structlog 迁移 + SQLite 迁移 downgrade 安全 — 892+ tests

- **v3.11.0** — Sprint 41：插件系统 — Plugin SDK（PluginBase + PluginManifest + PluginContext）+ PluginLoader 动态加载（importlib）+ 热重载 + 沙箱执行（工作区隔离 + 路径遍历防护）+ Plugin API（5 端点：list/discover/activate/deactivate/reload）+ 8 Hook 生命周期 + 23 新测试 — 2104+231 tests

- **v3.10.0** — Sprint 40：多Agent协作 — SubAgentRunner 真实执行修复 + AgentBus 消息总线（定向/广播/异步接收）+ 共识投票（提议/投票/多数决）+ Agent 管理 API（5 端点）+ 17 新测试 — 2081+231 tests

- **v3.9.0** — Sprint 39：桌面自动化 — FileSystemTool（工作区内 list/read/write + 路径遍历防护）+ WindowManagerTool（Windows/Linux/macOS 窗口列表）+ Desktop API 路由（/files + /windows + /screenshot）+ RBAC desktop 资源 + 20 新测试 — 2064+231 tests
- **v3.8.0** — Sprint 38：语音/视觉集成 — 云端 STT（httpx + OpenAI Whisper API 兼容）+ 中文 TTS（zh-CN-XiaoxiaoNeural）+ asyncio 修复 + LLM 视觉理解（ImageUnderstanding + OpenAI Vision API + OCR 降级）+ Vision API 路由（/analyze + /ocr）+ 16 新测试 — 2044+231 tests
- **v3.7.0** — Sprint 37：高级分析仪表板 — 实时执行指标 + LLM 成本分析（趋势 + Provider 分解）+ 技能性能基准（执行时间 + 成本）+ 异常检测（故障/成本/技能降级）+ LLMCostRecord 持久化表 + SkillRun 增强 + 5 新 API + 前端 6 图表 + 30s 自动刷新 — 2028+231 tests
- **v3.6.0** — Sprint 36：企业安全加固 — RBAC 权限控制（4 角色 52 权限 22 资源）+ OIDC SSO 单点登录 + 22 路由守卫 + 权限缓存 + Legacy Admin 兼容 + RBAC 管理 API（16 端点）+ Vue 管理界面 + 4 表 Alembic 迁移 — 1914+231 tests
- **v3.5.0** — Sprint 35：智能对话升级 — LLM 真实对话（非模板）+ 多国产模型支持（GLM/Kimi/Doubao/Qwen）+ Failover 自动切换（llama.cpp→云端→降级）+ WS 代理修复 + 聊天导航前移 + 12 个 LLM Provider — 1683+231 tests
- **v3.4.0** — Sprint 34：前端全面优化 — 全量 typed API（45 个端点类型化）+ useAsyncData/useEchartsChart composable + ECharts tree-shaking（~500KB gzip 减少）+ Element Plus 按需导入 + 双后端 API 层（more_agents :8900）+ WebSocket base composable 重构 + STATUS_COLORS 统一 — 1683+231 tests
- **v3.3.0** — Sprint 33：测试隔离修复 + Redis 集成测试 + WS Token 刷新 + OpenAPI 增强 — 1683 tests
- **v3.2.0** — Sprint 31-32：通知WS专用端点 + 缓存抽象层 + Redis适配器 + Grafana监控 + WS指数退避 + 路由守卫测试 — 1817 tests
- **v3.0.0** — Sprint 28-30：E2E测试 + GraphQL + DAG可视化 + 通知持久化 + DB连接池 + 安全加固 — 1460 tests
- **v2.2.0** — Sprint 23-25：Alembic迁移 + CI/CD + 配置验证 + 用户认证 + Chat UI + 密码哈希升级 — 898 tests
- **v2.0.0** — Sprint 17-22：Bash/Web/Cron/MCP/子Agent/多LLM/安全加固/生产就绪 — 802 tests
- **v1.0.0** — Sprint 1-16：完整核心平台 + 个人版 + 语音/视觉/桌面 + Docker — 530 tests
