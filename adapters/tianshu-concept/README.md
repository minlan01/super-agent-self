# tianshu 概念提取（非直接复用）

本目录是 `agent_tianshu` 的**概念提取副本**，仅作为 P3 阶段 WorkflowDefinition 设计的输入，**不含可执行后端**。

## 规格依据

- v1.1 §2.1.1 / §2.5 S.5
- ADR-013：tianshu 仅取概念，丢弃独立后端

## Vendor 进来的资产

| 资产 | 来源 | 用途 |
|------|------|------|
| `agents/*.json` | `agent_tianshu/agents/`（8 个） | 8 个角色定义：receiver/planning/review/dispatch/doc/eng/qa/aggregation |
| `skills/registry.json` | `agent_tianshu/skills/registry.json` | 23 个技能注册表（参考） |
| `skills/tianshu_api.py` | `agent_tianshu/skills/tianshu_api.py` | Agent 端 SDK 参考 |
| `openclaw-agents-config.json` | `agent_tianshu/` | OpenClaw 平台注册配置（含 8 个 Windows workspace 路径，待 P0 改造） |
| `../../scripts/etl/tianshu-tasks-source.json` | `agent_tianshu/data/tasks.json` | 7 条历史任务数据，P3 阶段 ETL 到 control-core |

## 丢弃的资产（未 vendor）

以下资产因 G-11/G-12 缺口**未进新仓**：

| 资产 | 丢弃原因 |
|------|----------|
| `scripts/server.py` | http.server 冒充 FastAPI + `subprocess.run(shell=True)` 调 openclaw CLI（G-11 命令注入） |
| `scripts/auto_dispatch.py` | 同上（G-11） |
| `scripts/tianshu_agent_worker.py` | 同上（G-11） |
| `scripts/scheduler_scan.py` | 同上（G-11）+ 停滞恢复 4 阶段逻辑复杂（O2 不做） |
| `scripts/agent_auto_process.py` | mock 模拟处理 |
| `subagents/subagent_manager.py` | `_execute_task()` 是 `time.sleep(1)` mock |
| `memory/palace_memory.py` | 写死 `Path.home() / '.openclaw'` |
| `dashboard/` | HTMX 前端，v1 改用 operator-console |
| `data/*.json`（comments/templates/time_tracking 等） | 字段名与 control-core schema 不一致，单独评估 |
| `docs/` | 过程文档，不 vendor |

## 待 P0 形成的映射表（ADR-013 落地）

### 1. 7 态 → LangGraph StateGraph 节点（G-15）

tianshu 的 7 态**不直接进 TaskStatus**（会污染 8 态语义），改为 LangGraph 节点：

| tianshu 态 | LangGraph 节点 | control-core TaskStatus |
|------------|----------------|-------------------------|
| Pending | entry | PENDING |
| Receiving（承旨司接旨） | `receiving` 节点 | （合并到 PENDING） |
| Planning（中书局规划） | `planning` 节点 | PLANNING |
| Reviewing（审核院三审） | `review` 节点 → approval gate | AWAITING_APPROVAL |
| Assigned（调度监分发） | `dispatch` 节点 | （合并到 PLANNING） |
| Doing（执行部门） | `doing` 节点 | EXECUTING |
| Done | END | COMPLETED |
| Cancelled | cancel 分支 | CANCELLED |
| （tianshu 无失败态） | failure 分支 | FAILED |

**关键决策**：Receiving/Assigned 是组织行为而非任务执行态，不进 TaskStatus。

### 2. tasks.json 字段 → control-core Task schema（G-16）

`tasks.json` 的字段（实测 7 条）与 control-core Task 模型字段名几乎全不同，P3 阶段 ETL 时按下表映射：

| tianshu 字段 | control-core 字段 | 备注 |
|--------------|-------------------|------|
| `id` | `external_reference.source_id` | 用 ExternalReference 保留原 ID |
| `title` | `goal` | |
| `priority` | `priority` | 值映射：normal/high/urgent |
| `state` | `status` | 用上面 7 态 → 8 态映射 |
| `now` | `metadata.now` | tianshu 组织语义，不进 TaskStatus |
| `output` | `result` | |
| `block` | `metadata.block` | tianshu 阻塞原因 |
| `flow_log` | `audit_note`（或 metadata） | **必须保留**，作为审计链 |
| `progress_log` | `metadata.progress_log` | |
| `org` | `metadata.org` | tianshu 当前责任部门 |
| `_scheduler` | （丢弃） | 内部调度状态 |
| `createdAt` | `created_at` | |
| `updatedAt` | `updated_at` | |

### 3. 8 Agent workspace 路径（G-12）

`openclaw-agents-config.json` 中 8 个 workspace 路径全部硬编码 `C:\Users\Administrator\.openclaw\workspace-tianshu-{name}`，Linux 部署直接失败。

P0 改造：
```
C:\Users\Administrator\.openclaw\workspace-tianshu-{name}
  ↓
${OPENCLAW_HOME}/workspace-tianshu-{name}
```

### 4. Qwen GGUF 模型（G-18，ADR-018）

8 个 Agent 全部用 `llamacpp/Qwen3.5-9B-Q4_K_M.gguf`，control-core 的 llm_gateway 不支持 llamacpp。

ADR-018 决策：**切 Ollama**（control-core 已支持 ollama provider），拉 `qwen3.5:9b`。模型名替换：
```
llamacpp/Qwen3.5-9B-Q4_K_M.gguf
  ↓
tianshu（control-core/configs/models.yaml 中定义为 ollama provider + qwen3.5:9b）
```
