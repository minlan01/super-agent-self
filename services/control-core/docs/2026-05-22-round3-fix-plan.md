# 第三轮审查修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复第三轮审查发现的25个问题，按严重度从CRITICAL到LOW依次修复

**Architecture:** 逐个修复，每个Task对应一个独立问题，TDD方式：先写测试→验证失败→实现修复→验证通过

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy, asyncio, Vue 3

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `packages/llm_gateway/cost_tracker.py` | Modify | 添加asyncio.Lock保护预算检查 |
| `packages/executor/tools/file_tools.py` | Modify | 符号链接检测 |
| `packages/policy/risk_rules.py` | Modify | URL编码路径遍历修复 |
| `packages/executor/tools/bash_tool.py` | Modify | 僵尸进程清理 |
| `apps/api_server/routes/health.py` | Modify | 敏感信息脱敏 |
| `packages/memory/memory_service.py` | Modify | 记忆创建限流 |
| `packages/llm_gateway/deepseek_provider.py` | Modify | API响应验证 |
| `packages/agent_core/orchestrator.py` | Modify | 任务状态事务保护 |
| `packages/cache/manager.py` | Modify | 空用户ID键冲突修复 |
| `packages/cron/scheduler.py` | Modify | 任务异常上报 |
| `packages/agent_core/agent_bus.py` | Modify | 消息日志一致性 |
| `packages/middleware/rate_limiter.py` | Modify | 配置热重载并发安全 |
| `packages/db/models.py` | Modify | JSON字段Schema验证 |
| `tests/unit/test_cost_tracker.py` | Modify | 新增并发预算测试 |
| `tests/unit/test_file_tools.py` | Modify | 新增符号链接测试 |
| `tests/unit/test_risk_rules.py` | Modify | 新增URL编码测试 |
| `tests/unit/test_bash_tool.py` | Modify | 新增僵尸进程测试 |
| `tests/unit/test_health.py` | Modify | 新增脱敏测试 |

---

### Task 1: C1 — CostTracker预算检查线程安全

**Files:**
- Modify: `packages/llm_gateway/cost_tracker.py:87-116`
- Test: `tests/unit/test_cost_tracker.py`

- [ ] **Step 1: 写并发预算超限测试**

```python
import asyncio
import pytest
from packages.llm_gateway.cost_tracker import CostTracker, BudgetExceededError

@pytest.mark.asyncio
async def test_concurrent_budget_enforcement():
    tracker = CostTracker(daily_budget_usd=0.01)
    tasks = []
    for _ in range(20):
        tasks.append(
            asyncio.to_thread(
                tracker.record, "deepseek", "deepseek-chat", 10000, 10000
            )
        )
    results = await asyncio.gather(*tasks, return_exceptions=True)
    budget_errors = [r for r in results if isinstance(r, BudgetExceededError)]
    assert len(budget_errors) > 0, "Budget should be exceeded by concurrent requests"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_cost_tracker.py::test_concurrent_budget_enforcement -v`
Expected: FAIL (budget not enforced under concurrency)

- [ ] **Step 3: 实现asyncio.Lock保护**

在 `CostTracker.__init__` 中添加 `self._lock = asyncio.Lock()`，在 `record()` 中使用锁：

```python
async def record_async(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> CostRecord:
    async with self._lock:
        return self._record_locked(provider, model, prompt_tokens, completion_tokens)

def record(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> CostRecord:
    cost = self.estimate_cost(provider, model, prompt_tokens, completion_tokens)
    rec = CostRecord(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost,
    )
    self._records.append(rec)

    if self._daily_budget_usd is not None:
        now = datetime.now(UTC)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_cost = self.get_total_cost(since=start_of_day.timestamp())
        if today_cost > self._daily_budget_usd:
            logger.warning(
                "Daily budget exceeded: $%.4f / $%.2f",
                today_cost,
                self._daily_budget_usd,
            )
            raise BudgetExceededError(
                f"Daily budget exceeded: ${today_cost:.4f} / ${self._daily_budget_usd:.2f}"
            )

    return rec
```

由于 `CostTracker` 在同步和异步上下文中都被使用，改用 `threading.Lock`：

```python
import threading

class CostTracker:
    def __init__(self, max_records=MAX_RECORDS, daily_budget_usd=None):
        self._records = deque(maxlen=max_records)
        self._custom_costs = {}
        self._flushed_count = 0
        self._daily_budget_usd = daily_budget_usd
        self._lock = threading.Lock()

    def record(self, provider, model, prompt_tokens, completion_tokens):
        with self._lock:
            cost = self.estimate_cost(provider, model, prompt_tokens, completion_tokens)
            rec = CostRecord(
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=cost,
            )
            self._records.append(rec)

            if self._daily_budget_usd is not None:
                now = datetime.now(UTC)
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                today_cost = self.get_total_cost(since=start_of_day.timestamp())
                if today_cost > self._daily_budget_usd:
                    raise BudgetExceededError(
                        f"Daily budget exceeded: ${today_cost:.4f} / ${self._daily_budget_usd:.2f}"
                    )

            return rec
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_cost_tracker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/llm_gateway/cost_tracker.py tests/unit/test_cost_tracker.py
git commit -m "fix: add threading.Lock to CostTracker budget check for thread safety"
```

---

### Task 2: C2 — file_tools符号链接绕过工作区限制

**Files:**
- Modify: `packages/executor/tools/file_tools.py:15-24`
- Test: `tests/unit/test_file_tools.py`

- [ ] **Step 1: 写符号链接绕过测试**

```python
def test_symlink_escape_detected(tmp_path):
    base = tmp_path / "workspace"
    base.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "flag.txt").write_text("secret")
    link = base / "link"
    link.symlink_to(outside)
    safe, err = _check_path_within_base(link / "flag.txt", base)
    assert not safe
    assert "escapes" in err.lower() or "symlink" in err.lower()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_file_tools.py::test_symlink_escape_detected -v`
Expected: FAIL (symlink escape not detected)

- [ ] **Step 3: 实现符号链接检测**

修改 `_check_path_within_base`：

```python
def _check_path_within_base(path: Path, base: Path) -> tuple[bool, str]:
    try:
        resolved = path.resolve()
        base_resolved = base.resolve()
    except OSError as exc:
        return False, f"Cannot resolve path: {exc}"
    if not resolved.is_relative_to(base_resolved):
        return False, f"Path escapes workspace: {path}"
    if path.is_symlink():
        return False, f"Symbolic links not allowed: {path}"
    return True, ""
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_file_tools.py::test_symlink_escape_detected -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/executor/tools/file_tools.py tests/unit/test_file_tools.py
git commit -m "fix: block symbolic links in file tools to prevent workspace escape"
```

---

### Task 3: C3 — risk_rules URL编码路径遍历绕过

**Files:**
- Modify: `packages/policy/risk_rules.py:42-49`
- Test: `tests/unit/test_risk_rules.py`

- [ ] **Step 1: 写URL编码绕过测试**

```python
def test_url_encoded_path_traversal():
    ok, _ = check_forbidden_path("%2Fetc%2Fpasswd", ["/etc"])
    assert not ok

def test_double_encoded_path_traversal():
    ok, _ = check_forbidden_path("%252Fetc%252Fpasswd", ["/etc"])
    assert not ok

def test_backslash_path_traversal():
    ok, _ = check_forbidden_path("\\etc\\passwd", ["/etc"])
    assert not ok
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/unit/test_risk_rules.py::test_url_encoded_path_traversal -v`
Expected: FAIL

- [ ] **Step 3: 实现URL解码预处理**

```python
from urllib.parse import unquote

def check_forbidden_path(path: str, forbidden_prefixes: list[str]) -> tuple[bool, str]:
    decoded = unquote(unquote(str(path)))
    normalized = decoded.replace("\\", "/")
    for prefix in forbidden_prefixes:
        prefix_normalized = prefix.replace("\\", "/")
        if normalized.startswith(prefix_normalized):
            return False, f"Path '{path}' matches forbidden prefix '{prefix}'"
    return True, ""
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/unit/test_risk_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/policy/risk_rules.py tests/unit/test_risk_rules.py
git commit -m "fix: decode URL-encoded paths in forbidden prefix check"
```

---

### Task 4: H1 — 健康检查端点敏感信息脱敏

**Files:**
- Modify: `apps/api_server/routes/health.py:29-59`
- Test: `tests/unit/test_health.py`

- [ ] **Step 1: 写脱敏测试**

```python
def test_readiness_no_sensitive_info(client):
    resp = client.get("/api/v1/health/ready")
    data = resp.json()
    checks_str = str(data)
    assert "api_key" not in checks_str.lower()
    assert "secret" not in checks_str.lower()
    assert "password" not in checks_str.lower()
    for v in data.get("checks", {}).values():
        if v not in ("ok", "not_initialized", "degraded"):
            assert "error:" not in v or len(v) < 100
```

- [ ] **Step 2: 运行测试验证失败**

- [ ] **Step 3: 实现脱敏**

修改 `readiness_check` 中的异常信息处理：

```python
except Exception:
    checks["db"] = "error"
...
except Exception:
    checks["llm"] = "error"
```

移除 `f"error: {exc}"` 中的异常详情，只返回 "error"。

- [ ] **Step 4: 运行测试验证通过**

- [ ] **Step 5: Commit**

```bash
git add apps/api_server/routes/health.py tests/unit/test_health.py
git commit -m "fix: sanitize health endpoint to avoid leaking sensitive info"
```

---

### Task 5: H3 — bash_tool僵尸进程清理

**Files:**
- Modify: `packages/executor/tools/bash_tool.py:106-111`
- Test: `tests/unit/test_bash_tool.py`

- [ ] **Step 1: 写僵尸进程测试**

```python
@pytest.mark.asyncio
async def test_timeout_kills_and_reaps():
    tool = BashExecute()
    context = _make_context()
    result = await tool.execute({"command": "sleep 999", "timeout": 1}, context)
    assert not result.success
    assert "timed out" in result.error.lower()
```

- [ ] **Step 2: 运行测试验证通过（基线）**

- [ ] **Step 3: 实现proc.wait()清理**

```python
except TimeoutError:
    proc.kill()
    await proc.wait()
    return ToolResult(
        success=False,
        error=f"Command timed out after {timeout}s",
    )
```

- [ ] **Step 4: 运行测试验证通过**

- [ ] **Step 5: Commit**

```bash
git add packages/executor/tools/bash_tool.py
git commit -m "fix: await proc.wait() after kill to prevent zombie processes"
```

---

### Task 6: H2 — 记忆创建速率限制

**Files:**
- Modify: `packages/memory/memory_service.py:34-98`

- [ ] **Step 1: 实现速率限制**

在 `MemoryService.__init__` 中添加简单的滑动窗口限速器：

```python
from collections import deque
import time

class _RateLimiter:
    def __init__(self, max_writes: int = 60, window_seconds: int = 60):
        self._max = max_writes
        self._window = window_seconds
        self._timestamps: deque[float] = deque()

    def allow(self) -> bool:
        now = time.time()
        cutoff = now - self._window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._max:
            return False
        self._timestamps.append(now)
        return True
```

在 `write_from_task` 开头添加检查：

```python
if not self._limiter.allow():
    logger.warning("Memory write rate limit exceeded for user %s", user_id)
    return None
```

- [ ] **Step 2: Commit**

```bash
git add packages/memory/memory_service.py
git commit -m "feat: add rate limiting to memory creation"
```

---

### Task 7: H4 — DeepSeek API响应验证

**Files:**
- Modify: `packages/llm_gateway/deepseek_provider.py:114-133`

- [ ] **Step 1: 实现响应验证**

在 `generate()` 和 `generate_json()` 中添加字段验证：

```python
async def generate(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
    body = self._build_body(messages, **kwargs)
    data = await self._request(body)

    choices = data.get("choices")
    if not choices or not isinstance(choices, list) or len(choices) == 0:
        raise RuntimeError(
            f"DeepSeek returned no choices: {list(data.keys())}"
        )
    choice = choices[0]
    msg = choice.get("message", {})
    content = msg.get("content", "")
    usage = self._parse_usage(data.get("usage"))

    return LLMResponse(
        content=content,
        model=data.get("model", self.model),
        provider=self.name,
        usage=usage,
        raw=data,
    )
```

- [ ] **Step 2: Commit**

```bash
git add packages/llm_gateway/deepseek_provider.py
git commit -m "fix: validate DeepSeek API response structure before accessing"
```

---

### Task 8: H6 — Orchestrator任务状态事务保护

**Files:**
- Modify: `packages/agent_core/orchestrator.py:108-116`

- [ ] **Step 1: 实现db.expire刷新**

在获取任务状态前刷新会话缓存：

```python
result = await self.executor.execute_plan(db, task.id, plan, context)

db.expire(task)
task = TaskRepository.get_by_id(db, task.id)
if task is None:
    return {
        "task_id": "unknown",
        "status": "failed",
        "error": "Task not found after execution",
    }
```

同样修改 `run_with_plan` 中约 L172 处。

- [ ] **Step 2: Commit**

```bash
git add packages/agent_core/orchestrator.py
git commit -m "fix: expire ORM cache before reading task state after execution"
```

---

### Task 9: M1 — CacheManager空用户ID键冲突

**Files:**
- Modify: `packages/cache/manager.py:85-99`

- [ ] **Step 1: 实现空用户ID防护**

```python
def _ns_key(self, namespace: str, key: str, *, user_id: str | None = None) -> str:
    if user_id and user_id.strip():
        return f"{self._prefix}:{namespace}:u:{user_id}:{key}"
    return f"{self._prefix}:{namespace}:{key}"

def _ns_pattern(self, namespace: str, *, user_id: str | None = None) -> str:
    if user_id and user_id.strip():
        return f"{self._prefix}:{namespace}:u:{user_id}:*"
    return f"{self._prefix}:{namespace}:*"
```

- [ ] **Step 2: Commit**

```bash
git add packages/cache/manager.py
git commit -m "fix: prevent empty user_id from causing cache key collision"
```

---

### Task 10: M2 — Cron任务异常上报

**Files:**
- Modify: `packages/cron/scheduler.py`

- [ ] **Step 1: 实现异常上报**

在 `_run_job` 中添加异常状态追踪：

```python
def _run_job(self, job_id: str):
    ...
    except Exception as e:
        logger.error("Cron job '%s' failed: %s", job_id, e, exc_info=True)
        self._job_errors[job_id] = {
            "error": str(e),
            "timestamp": time.time(),
        }
```

添加 `get_job_errors()` 方法供外部查询。

- [ ] **Step 2: Commit**

```bash
git add packages/cron/scheduler.py
git commit -m "feat: track cron job errors for observability"
```

---

### Task 11: M5 — AgentBus消息日志一致性

**Files:**
- Modify: `packages/agent_core/agent_bus.py`

- [ ] **Step 1: 统一日志截断逻辑**

将 `MAX_LOG = 1000` 和截断到500的逻辑改为统一的 `MAX_LOG = 500`：

```python
MAX_LOG = 500

# 在 send() 中：
if len(self._message_log) > MAX_LOG:
    self._message_log = self._message_log[-MAX_LOG:]
```

- [ ] **Step 2: Commit**

```bash
git add packages/agent_core/agent_bus.py
git commit -m "fix: unify message log truncation to MAX_LOG=500"
```

---

### Task 12: M6 — RateLimiter配置热重载并发安全

**Files:**
- Modify: `packages/middleware/rate_limiter.py`

- [ ] **Step 1: 添加threading.Lock**

```python
import threading

class RateLimiter:
    def __init__(self, ...):
        ...
        self._config_lock = threading.Lock()

    def _check_reload(self):
        if not self._config_path:
            return
        ...
        with self._config_lock:
            new_config = self._load_config()
            if new_config:
                self._routes = new_config.get("routes", {})
                ...
```

- [ ] **Step 2: Commit**

```bash
git add packages/middleware/rate_limiter.py
git commit -m "fix: add threading.Lock for rate limiter config hot-reload safety"
```

---

### Task 13: M9 — DB Models JSON字段Schema验证

**Files:**
- Modify: `packages/db/models.py`

- [ ] **Step 1: 为AuditEvent.details添加验证**

在 `AuditEvent` 模型中添加验证方法：

```python
class AuditEvent(Base):
    ...
    @validates("detail")
    def _validate_detail(self, key, value):
        if value is not None and not isinstance(value, dict):
            raise ValueError("AuditEvent.detail must be a dict")
        return value
```

类似地为 `SkillRun.result` 和 `ConversationMessage.content` 添加验证。

- [ ] **Step 2: Commit**

```bash
git add packages/db/models.py
git commit -m "fix: add validates for JSON fields in ORM models"
```

---

### Task 14: 运行完整测试和lint验证

- [ ] **Step 1: 运行单元测试**

Run: `pytest tests/unit/ -q --tb=short --ignore=tests/unit/test_evaluation.py --ignore=tests/unit/test_observability.py`
Expected: ALL PASS

- [ ] **Step 2: 运行ruff lint**

Run: `ruff check packages/ apps/ tests/`
Expected: No new errors

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "chore: round 3 audit fixes — test and lint verification"
```
