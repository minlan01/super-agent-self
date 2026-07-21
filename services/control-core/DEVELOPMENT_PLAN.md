# 双版本可控自进化 Agent 平台 — 开发计划

> 基于《双版本可控自进化Agent平台_完整开发方案_DeepSeek版 v3.0》制定
> 创建日期：2026-04-29
> 目标目录：F:\myself-agent

---

## 一、项目概览

### 产品定义
一套 **Agent Core** 底座 + 两个产品版本：

| 版本 | 定位 | 阶段 |
|------|------|------|
| **Enterprise Edition** | 企业安全可控 Agent，网页自动化 + 文档生成 + 技能审批 | Phase 1（优先交付） |
| **Personal Jarvis Edition** | 个人智能助手，语音 + 桌面控制 + 长期记忆 | Phase 2+（架构预留） |

### 核心架构

```
Controlled Agent Core
├── Task System（任务状态机）
├── Planner Service（LLM 规划）
├── Policy Service（安全策略 + Capability Token）
├── Execution Service（工具执行器）
├── Tool Registry（工具注册表）
├── Capability Token（执行授权令牌）
├── Memory Service（长期记忆）
├── Skill Service（技能提炼/复用/审批）
├── Audit Service（全链路审计）
├── LLM Gateway（DeepSeek / Mock 双 Provider）
├── Evaluation System（任务评估 + 回归检测）
└── Edition/Profile Config（版本配置）
```

### 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.x / Pydantic v2 / Alembic |
| 数据库 | SQLite → PostgreSQL |
| LLM | DeepSeek v4（主）/ Mock Provider（无 Key 时） |
| 浏览器 | Playwright |
| 文档 | python-docx |
| 前端 | Vue 3 + Vite + Element Plus + Pinia |
| 配置 | YAML + pydantic-settings |
| 测试 | pytest |
| 部署 | Docker Compose |

---

## 二、Phase 1 开发计划（8 周 → 精简为可执行步骤）

### 设计原则
1. **LLM 只负责规划，不直接执行** — 输出结构化 JSON Plan
2. **Policy 是执行前唯一安全闸门** — 所有步骤必经 Policy
3. **Executor 只执行授权步骤** — 需 Capability Token
4. **Memory 只参考，不越权** — 不能绕过 Policy
5. **Skill 必须审批后复用** — candidate → stable 需人工批准
6. **两个版本共享核心** — Edition/Profile 区分行为

---

### Sprint 1：项目基础 + 数据层（第 1 周）

**目标**：项目骨架、数据库、ORM、Schema、基础 API

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| 1.1 | 项目初始化 | `pyproject.toml`, `.env.example`, `README.md`, `configs/app.yaml`, `pytest.ini`, `ruff.toml` | `pip install -e .` 成功 |
| 1.2 | 数据库 Session | `packages/db/session.py`, `scripts/init_db.py` | `python scripts/init_db.py` 创建 SQLite |
| 1.3 | ORM Models | `packages/db/models.py` — 8 张表（tasks, task_steps, audit_events, memories, skills, skill_runs, approvals, edition_profiles） | 全部表可创建 |
| 1.4 | Repository 层 | `packages/db/repositories/` — 6 个 repo（task, audit, memory, skill, approval, edition） | 单元测试通过 |
| 1.5 | Pydantic Schemas | `packages/agent_core/schemas.py` — 8 组 Schema | Schema 校验测试通过 |
| 1.6 | FastAPI 基础 | `apps/api_server/main.py`, `dependencies.py`, health check, 错误处理, 响应结构 | `curl /health` 返回 200 |
| 1.7 | Task API | `apps/api_server/routes/tasks.py` — CRUD + cancel | 集成测试通过 |

### Sprint 2：LLM + Planner + Policy（第 2 周）

**目标**：LLM 接入、规划服务、安全策略引擎、Capability Token

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| 2.1 | LLM Gateway | `packages/llm_gateway/` — base, mock_provider, deepseek_provider, provider_router, `configs/models.yaml` | Mock 模式可规划 |
| 2.2 | Planner Prompt | `packages/planner/prompt_templates.py` — 强制 JSON 输出，注入 tools/edition/memories/skills | Mock 输出可解析 |
| 2.3 | Planner Service | `packages/planner/planner_service.py`, `plan_validator.py` | 调用 LLM → 解析 → Pydantic 校验 → 失败重试 |
| 2.4 | Tool Registry | `packages/policy/tool_registry.py`, `configs/tools.yaml` — 注册/启用/禁用工具，edition 差异 | shell.run 默认 disabled |
| 2.5 | Policy Engine | `packages/policy/policy_engine.py`, `risk_rules.py` — 7 项检查 | 拒绝非法工具/路径/URL |
| 2.6 | Capability Token | `packages/policy/capability_token.py` — HMAC-SHA256 签发/验证 | 过期/篡改/args 不匹配 拒绝 |
| 2.7 | Policy + Token 集成 | 通过后签发 token，拒绝写 audit | 集成测试通过 |

### Sprint 3：Executor + 工具（第 3 周）

**目标**：执行器框架、浏览器工具、文档导出工具

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| 3.1 | Executor 框架 | `packages/executor/executor_service.py`, `tool_runner.py`, `tools/base.py` | token 验证 + Registry 查询 + 写 TaskStep |
| 3.2 | 执行审计 | 执行前/后/失败审计事件，标准化 ToolResult | 审计链路完整 |
| 3.3 | Word 导出工具 | `packages/executor/tools/file_tools.py` — python-docx，workspace 限制 | 生成 .docx 文件 |
| 3.4 | Playwright 上下文 | Browser context 初始化，headless 配置，截图目录 | 浏览器可启动 |
| 3.5 | browser.open | `packages/executor/tools/browser_tools.py` — 打开 URL + 截图 + 安全规则 | URL 安全检查 |
| 3.6 | browser.click | CSS selector 点击 + 元素检查 + 前后截图 | 点击操作成功 |
| 3.7 | browser.extract_text | selectors 提取 + 表格结构化 | 文本/表格提取成功 |

### Sprint 4：Orchestrator + 端到端 Demo（第 4 周）

**目标**：完整任务生命周期、企业 Demo 跑通

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| 4.1 | Task 状态机 | `packages/agent_core/task_state.py` — 8 种状态流转 | 状态转换正确 |
| 4.2 | Orchestrator v1 | `packages/agent_core/orchestrator.py` — 连接 Planner → Policy → Executor | PLAN → POLICY_CHECK → EXECUTE 链路 |
| 4.3 | Orchestrator 执行 | 顺序执行 steps，失败中断，保存结果 | 全流程测试通过 |
| 4.4 | 本地 Demo 页面 | 静态 HTML（搜索列表 + 详情页） | 浏览器可访问 |
| 4.5 | 网页→Word E2E Demo | `scripts/run_enterprise_demo.py` | 一键运行输出 Word |
| 4.6 | Task API 接 Orchestrator | POST /api/tasks 触发全流程 | curl 创建任务生成 Word |
| 4.7 | 第 4 周修复 | 补测试 + 修复集成问题 | `pytest` 全绿 |

### Sprint 5：Memory 系统（第 5 周）

**目标**：长期记忆写入、召回、注入 Planner

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| 5.1 | Memory Schema | `packages/memory/schemas.py` — 5 种类型 | Schema 校验通过 |
| 5.2 | Memory Summarizer | `packages/memory/summarizer.py` — mock + DeepSeek | 摘要输出 JSON |
| 5.3 | Memory 写入 | 任务完成触发，content_hash 去重，audit log | 写入测试通过 |
| 5.4 | Memory API | 5 个端点 — search/list/get/disable/delete | API 测试通过 |
| 5.5 | Memory Retriever | 关键词/最近任务召回，预留向量召回 | 召回排序正确 |
| 5.6 | Memory Token Budget | 最多 5 条 / 1500 tokens / 过期不注入 | 100 条只取 5 条 |
| 5.7 | Memory + Planner 集成 | Planner 前召回，注入 prompt，不绕过 Policy | 集成测试通过 |

### Sprint 6：Skill 系统（第 6 周）

**目标**：技能提炼、审批、复用、指标

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| 6.1 | Skill Schema | `packages/skills/schemas.py` — Definition/Status/Run/Metrics | Schema 校验通过 |
| 6.2 | Skill Extractor | `packages/skills/skill_extractor.py` — 从 task_steps 提取模板 | 生成 candidate skill |
| 6.3 | Skill Registry | `packages/skills/skill_registry.py` — CRUD + 去重 + 版本 | Registry 测试通过 |
| 6.4 | Skill API | 5 个端点 — list/get/approve/disable/rollback | API 测试通过 |
| 6.5 | 任务完成提炼 | 成功任务触发 Extractor，写 CANDIDATE + audit | Demo 后出现 candidate |
| 6.6 | Skill Reuse | Planner 输入 skills → 选择/展开 → 仍经 Policy | 批准后同类任务复用 |
| 6.7 | Skill Metrics | skill_runs 统计，连续 3 次失败降级，< 70% 降级 | 指标测试通过 |

### Sprint 7：Enterprise Admin UI（第 7 周）

**目标**：Vue 3 管理界面

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| 7.1 | Admin Web 初始化 | `apps/enterprise_admin_web/` — Vue 3 + Vite + Element Plus + Router + Axios + Layout | `npm run dev` 启动 |
| 7.2 | 任务列表/详情 | TaskList.vue + TaskDetail.vue — 状态/步骤/参数/结果/错误 | UI 查看 demo 任务 |
| 7.3 | Audit 页面 | AuditLog.vue — 按 task_id/event_type 过滤，详情展示 | 完整审计可查 |
| 7.4 | Memory 页面 | MemoryList.vue — 搜索/过滤/详情/禁用 | 记忆可管理 |
| 7.5 | Skill 页面 | SkillList.vue + SkillDetail.vue — approve/disable/rollback | 技能可审批 |
| 7.6 | Approval 页面 | ApprovalList.vue — 待审批/approve/reject | 审批流程完整 |
| 7.7 | Dashboard | Dashboard.vue — 任务数/成功率/技能数/记忆数/拦截次数 | 真实数据展示 |

### Sprint 8：安全 + 部署 + 封版（第 8 周）

**目标**：安全加固、E2E 测试、Docker 部署、v0.1 封版

| # | 任务 | 产出文件 | 验收标准 |
|---|------|---------|---------|
| 8.1 | Security Tests | 9 项安全测试 | `pytest tests/security` 全绿 |
| 8.2 | E2E Tests | 完整链路测试（创建→规划→Policy→执行→Word→Memory→Skill→审批→复用→审计） | `pytest tests/e2e` 全绿 |
| 8.3 | Docker Compose | Dockerfile + docker-compose.yml + workspace 挂载 | `docker compose up` 启动 |
| 8.4 | 部署文档 | docs/deployment.md + configs 说明 + .env.example | 新环境按文档启动 |
| 8.5 | 产品文档 | README + architecture/editions/security/api docs | 新人可理解 |
| 8.6 | 稳定性修复 | 全量测试 + 修复 flaky + Windows 路径 + 浏览器超时 | `pytest` + demo 稳定 |
| 8.7 | v0.1 封版 | tag + release notes + 风险清单 + roadmap | 非开发者可启动 |

---

## 三、Phase 2 计划（第 9-12 周，Personal Jarvis Alpha）

> 基于 Phase 1 Agent Core 扩展，不修改 Core 架构

| 周 | 重点 | 关键任务 |
|---|------|---------|
| 第 9 周 | Personal Edition 基础 | personal.yaml 配置 + Web Shell + 个人 Memory + 文件索引/搜索 + 输出工具 |
| 第 10 周 | 个人助手能力 | 个人 Planner Prompt + 项目助手 + 提醒系统 v1 + 个人技能库 + 对话式交互 |
| 第 11 周 | 浏览器增强 | 个人浏览器辅助 + 多标签管理 + 书签 + 信息聚合 + 价格/新闻监控 |
| 第 12 周 | Alpha 封版 | 集成测试 + Personal Demo + UI 完善 + 安全审查 + v0.1-alpha 封版 |

---

## 四、Phase 3-4 路线图（第 13-20 周+）

| 阶段 | 目标 |
|------|------|
| Phase 3 | 语音交互 + 屏幕理解 + OCR + 桌面控制（安全受限） |
| Phase 4 | Enterprise v1.0 生产化 + Jarvis v1.0 + 多设备扩展 |

---

## 五、目录结构

```
F:\myself-agent\
├── pyproject.toml
├── .env.example
├── README.md
├── pytest.ini
├── ruff.toml
│
├── configs/
│   ├── app.yaml
│   ├── editions/
│   │   ├── enterprise.yaml
│   │   └── personal.yaml
│   ├── models.yaml
│   ├── tools.yaml
│   ├── policy.yaml
│   ├── memory.yaml
│   └── skills.yaml
│
├── apps/
│   ├── api_server/
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   └── routes/
│   │       ├── tasks.py
│   │       ├── memory.py
│   │       ├── skills.py
│   │       ├── audit.py
│   │       ├── approvals.py
│   │       ├── metrics.py
│   │       └── editions.py
│   │
│   ├── enterprise_admin_web/
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   └── src/
│   │       ├── main.ts
│   │       ├── router/
│   │       ├── api/
│   │       ├── stores/
│   │       ├── views/
│   │       └── components/
│   │
│   └── personal_shell/          (Phase 2)
│       └── placeholder.md
│
├── packages/
│   ├── agent_core/
│   │   ├── orchestrator.py
│   │   ├── task_state.py
│   │   ├── edition_manager.py
│   │   └── schemas.py
│   ├── planner/
│   │   ├── planner_service.py
│   │   ├── prompt_templates.py
│   │   └── plan_validator.py
│   ├── policy/
│   │   ├── policy_engine.py
│   │   ├── capability_token.py
│   │   ├── tool_registry.py
│   │   ├── approval_service.py
│   │   └── risk_rules.py
│   ├── executor/
│   │   ├── executor_service.py
│   │   ├── tool_runner.py
│   │   └── tools/
│   │       ├── base.py
│   │       ├── browser_tools.py
│   │       ├── file_tools.py
│   │       ├── api_tools.py
│   │       └── desktop_tools_placeholder.py
│   ├── memory/
│   │   ├── memory_service.py
│   │   ├── retriever.py
│   │   ├── summarizer.py
│   │   ├── importance_scorer.py
│   │   └── schemas.py
│   ├── skills/
│   │   ├── skill_service.py
│   │   ├── skill_extractor.py
│   │   ├── skill_registry.py
│   │   ├── skill_evaluator.py
│   │   └── schemas.py
│   ├── llm_gateway/
│   │   ├── base.py
│   │   ├── deepseek_provider.py
│   │   ├── mock_provider.py
│   │   └── provider_router.py
│   ├── db/
│   │   ├── session.py
│   │   ├── models.py
│   │   └── repositories/
│   │       ├── task_repo.py
│   │       ├── memory_repo.py
│   │       ├── skill_repo.py
│   │       ├── audit_repo.py
│   │       ├── approval_repo.py
│   │       └── edition_repo.py
│   ├── evaluation/
│   │   ├── task_evaluator.py
│   │   ├── skill_metrics.py
│   │   └── regression_checker.py
│   ├── personal_context/         (Phase 2)
│   │   └── placeholder.py
│   └── observability/
│       ├── logger.py
│       ├── audit.py
│       └── metrics.py
│
├── workspace/
│   ├── outputs/
│   ├── screenshots/
│   ├── raw/
│   └── browser_profiles/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   └── e2e/
│
├── scripts/
│   ├── init_db.py
│   ├── run_api.py
│   ├── run_enterprise_demo.py
│   └── seed_demo_data.py
│
└── docs/
    ├── architecture.md
    ├── editions.md
    ├── security_model.md
    ├── memory_design.md
    ├── skill_lifecycle.md
    ├── api_reference.md
    └── deployment.md
```

---

## 六、数据库设计（8 张表）

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| tasks | 任务 | id, user_id, edition, goal, status, risk_level, result |
| task_steps | 执行步骤 | id, task_id, step_id, tool_name, args, risk_level, requires_approval, status, capability_token_hash, result |
| audit_events | 审计日志 | id, task_id, step_id, edition, event_type, actor, detail |
| memories | 长期记忆 | id, user_id, edition, memory_type, title, summary, importance_score, confidence_score |
| skills | 技能库 | id, edition, name, version, status, definition(JSON), success_rate |
| skill_runs | 技能运行记录 | id, skill_id, task_id, success, metrics |
| approvals | 审批 | id, edition, approval_type, target_id, status, approved_by |
| edition_profiles | 版本配置 | id, edition, name, config(JSON) |

---

## 七、安全模型（核心约束）

### 禁止行为（默认）
1. 任意 shell 命令
2. 删除文件
3. 写入 workspace 之外
4. 访问 localhost（除非配置允许）
5. 自动提交表单/发送邮件/支付
6. 下载并执行文件
7. 修改系统设置/权限

### Capability Token 机制
- HMAC-SHA256 签名
- 5 分钟有效期
- 绑定 task_id + step_id + tool_name + args_hash
- 任何篡改/过期/不匹配均拒绝

### Prompt Injection 防护（6 层）
1. Planner 强制 JSON 输出
2. Pydantic schema 校验
3. Tool Registry 白名单
4. Policy Engine 拒绝未注册工具
5. Executor 需 Capability Token
6. Policy 不给高风险工具签发 Token

---

## 八、立即开始

当前执行优先级：**Sprint 1 — 项目基础 + 数据层**

执行顺序：
1. 创建项目目录结构
2. 编写 pyproject.toml + 配置文件
3. 实现数据库层（session → models → repositories）
4. 定义 Pydantic Schemas
5. 搭建 FastAPI 基础
6. 实现 Task API

每个步骤完成后运行对应测试验证。
