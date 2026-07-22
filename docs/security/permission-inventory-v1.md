# 权限清单 v1

**生成日期**: 2026-07-22
**适用版本**: spec v1.1, P0 完成
**依据**: spec §6 风险模型 + configs/tools.yaml + configs/rbac.yaml + configs/policy.yaml

## 1. 角色清单（RBAC）

来自 `packages/auth/rbac.py` + `configs/rbac.yaml`：4 角色 52 权限。

| 角色 | 定位 | L0/L1 | 权限互斥 |
|---|---|---|---|
| `architect` | 平台架构负责人（决策者） | L0 | — |
| `operator` | Agent 运维操作者（最终用户） | L1 | 与 auditor 互斥 |
| `auditor` | 安全合规审计员 | L1 | 与 operator 互斥 |
| `sre` | DevOps/SRE | L1 | — |

## 2. 工具风险矩阵

来自 `configs/tools.yaml`（P0.4 已对齐）：

| 工具名 | 风险 | enabled | 审批要求 | 说明 |
|---|---|---|---|---|
| `file.read` | low | ✅ | 否 | Workspace 内读取 |
| `file.list` | low | ✅ | 否 | 目录列举 |
| `file.search` | low | ✅ | 否 | 内容搜索 |
| `file.write_docx` | low | ✅ | 否 | 写 docx |
| `file.write_markdown` | low | ✅ | 否 | 写 markdown |
| `web.search` | low | ✅ | 否 | 网络搜索 |
| `browser.open` | low | ✅ | 否 | 打开 URL |
| `browser.click` | low | ✅ | 否 | 点击 |
| `browser.extract_text` | low | ✅ | 否 | 提取文本 |
| `browser.screenshot` | low | ✅ | 否 | 截图 |
| `browser.bookmark` | low | ✅ | 否 | 书签（P0.4 补登记） |
| `browser.monitor` | medium | ✅ | 否 | 监控（P0.4 补登记） |
| `desktop.screenshot` | low | ✅ | 否 | 桌面截图 |
| `desktop.windows` | low | ✅ | 否 | 窗口列表 |
| `desktop.type` | medium | ✅ | 否 | 键盘输入 |
| `desktop.files` | medium | ✅ | 否 | 文件操作 |
| `delegate.task` | medium | ✅ | 否 | 子代理委派 |
| `message.send` | medium | ✅ | 否 | 发消息（personal） |
| **`desktop.click`** | **high** | ✅ | **是** | 鼠标点击（P0.4 对齐到 high） |
| **`shell.execute`** | **high** | ✅ | **是** | Bash 执行 |
| `shell.run` | critical | ❌ | — | 禁用（占位） |
| `system.modify` | critical | ❌ | — | 禁用（占位） |
| `screen.capture` | medium | ❌ | — | 禁用（P0.5 注册前） |
| `image.ocr` | low | ❌ | — | 禁用（P0.5 注册前） |
| `image.analyze` | medium | ❌ | — | 禁用（P0.5 注册前） |

**审批规则**（`configs/policy.yaml`）：`require_approval_risk_levels: ["high"]` → high 及以上必须人工审批。

## 3. Policy 配置（configs/policy.yaml）

| 配置项 | 值 | 说明 |
|---|---|---|
| `max_allowed_risk` | high | critical 永远拒绝 |
| `forbidden_tools` | [] | 无额外禁用（靠 enabled 标志） |
| `workspace_only` | true | 文件操作限定工作区 |
| `forbidden_path_prefixes` | [.ssh, .aws, ...] | 敏感目录（spec §4.7） |
| `forbidden_url_patterns` | [localhost, 169.254.169.254, ...] | SSRF 防护 |
| `token_expire_minutes` | 5 | Capability token TTL |
| `token_max_uses` | 1 | 单次消费 |

## 4. API 路由权限（节选）

来自 `apps/api_server/routes/*.py` 的 `require_permission()` 装饰器：

| 路由 | 方法 | 权限 | 备注 |
|---|---|---|---|
| `/api/v1/tasks` | POST | `task:create` | 创建任务 |
| `/api/v1/tasks/{id}/execute` | POST | `task:execute` | 执行任务 |
| `/api/v1/tasks/{id}/cancel` | POST | `task:cancel` | 取消 |
| `/api/v1/approvals` | GET | `approval:list` | 审批队列 |
| `/api/v1/approvals/{id}/resolve` | POST | `approval:resolve` | 批准/拒绝 |
| `/api/v1/audit` | GET | `audit:read` | 审计查询 |
| `/api/v1/memory` | POST | `memory:write` | 写记忆 |
| `/api/v1/skills` | POST | `skill:manage` | 技能管理 |
| `/api/v1/desktop/windows` | POST | `desktop:read` | 窗口列表（旁路，P1 改走 ToolGateway） |
| `/api/v1/admin/*` | * | `admin:*` | 管理操作 |

## 5. 已识别的权限缺陷（P1 修复）

| ID | 缺陷 | 风险 | 修复 |
|---|---|---|---|
| PI-01 | Repository 无 tenant_id 过滤 | 跨租户访问 | P1 ActorScope 强制注入 |
| PI-02 | 请求体含可伪造 user_id | 身份伪造 | P1 删字段改 Depends 注入 |
| PI-03 | routes/desktop.py 绕过 ToolRunner | 提权 | P1 改走 ToolGateway |
| PI-04 | SubAgentRunner 不检查 enabled | 提权 | P1 接入 ToolRunner |
| PI-05 | personal_shell CLI 无审计 | 抵赖 | P1 接入 ToolGateway |
