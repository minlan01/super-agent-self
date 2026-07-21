# Memory System Design

## Overview

The Memory system provides long-term knowledge persistence for the agent platform. It captures experiences from completed tasks, scores them by importance, deduplicates content, and retrieves relevant memories for injection into future planning prompts. This enables the agent to learn from past executions, avoid repeating mistakes, and leverage discovered patterns.

The system is organized into four components under `packages/memory/`:

| Component | File | Responsibility |
|---|---|---|
| MemoryService | `memory_service.py` | Orchestrates the write lifecycle: summarize, score, deduplicate, persist, audit |
| MemoryRetriever | `retriever.py` | Retrieves relevant memories for planner injection with token budget enforcement |
| MemorySummarizer | `summarizer.py` | Generates concise summaries from task results (LLM or rule-based) |
| ImportanceScorer | `importance_scorer.py` | Computes importance scores based on type, success, and complexity |

Persistence is handled by `MemoryRepository` (`packages/db/repositories/memory_repo.py`) backed by the `memories` table in SQLAlchemy.

---

## Memory Types

The system defines 9 memory types via the `MemoryType` enum in `packages/db/models.py`. Each type carries a different base importance weight and serves a distinct purpose.

### Enterprise Types (available in both editions)

| Type | Enum Value | Base Weight | Auto-Created | Description |
|---|---|---|---|---|
| Execution Experience | `EXECUTION_EXPERIENCE` | 0.6 | Yes | General experience gained from executing a task |
| Workflow Pattern | `WORKFLOW_PATTERN` | 0.8 | Yes | Discovered reusable workflow patterns from repeated task structures |
| Domain Knowledge | `DOMAIN_KNOWLEDGE` | 0.7 | No | Domain-specific factual knowledge extracted during execution |
| Error Solution | `ERROR_SOLUTION` | 0.9 | Yes | Error-cause and resolution pairs -- the highest-weight type |

### Personal Edition Types (edition = `"personal"` only)

| Type | Enum Value | Base Weight | Auto-Created | Description |
|---|---|---|---|---|
| User Preference | `USER_PREFERENCE` | 0.75 | Yes | Individual user preferences (e.g., coding style, tool choices) |
| Personal Project | `PERSONAL_PROJECT` | 0.7 | No | Context about personal projects the user is working on |
| File Knowledge | `FILE_KNOWLEDGE` | 0.5 | Yes | Knowledge extracted from files the user has shared |
| Reminder | `REMINDER` | 0.6 | No | User-set reminders |
| Daily Context | `DAILY_CONTEXT` | 0.4 | Yes | Auto-captured daily context (time, weather, schedule) |

---

## Memory Lifecycle

### 1. Creation

Memories are created after task completion via `MemoryService.write_from_task()`. The caller provides a `MemoryWriteRequest` containing:

- `task_id` -- the source task UUID
- `goal` -- the task goal text
- `steps_summary` -- list of step dicts with `step_id`, `tool_name`, `status`
- `success` -- whether the task succeeded
- `memory_type` -- which `MemoryType` to assign (defaults to `EXECUTION_EXPERIENCE`)

### 2. Summarization

The `MemorySummarizer` produces a `MemorySummary` with `title`, `summary`, `importance_score`, and `confidence_score`.

**LLM path** (when `provider_router` is provided):
- Sends a system + user prompt requesting JSON output with title (max 200 chars), summary (max 500 chars), importance_score (0.0-1.0), and confidence_score (0.0-1.0).
- Uses `provider_router.generate_json()` for structured output.
- Falls back to rule-based on failure.

**Rule-based path** (default, no LLM required):
- Title: goal text, truncated to 200 chars.
- Summary: concatenation of success status, goal, tool chain, and step count, truncated to 500 chars.
- Importance: 0.7 if successful, 0.8 if failed (failures are more important to remember).
- Confidence: 0.9 if successful, 0.7 if failed.

### 3. Importance Scoring

The `ImportanceScorer` adjusts the raw importance from summarization using a weighted formula:

```
final_score = 0.4 * base_importance + 0.6 * type_weight
```

**Modifiers applied after the base calculation:**

| Modifier | Condition | Adjustment |
|---|---|---|
| Failure boost | `success == False` | +0.15 (capped at 1.0) |
| High complexity | `step_count > 5` | +0.1 (capped at 1.0) |
| Medium complexity | `step_count > 3` | +0.05 (capped at 1.0) |
| Duplicate penalty | `is_unique == False` | -0.3 (floored at 0.0) |

The final score is clamped to `[0.0, 1.0]` and rounded to 2 decimal places.

### 4. Deduplication

Before persisting, the service computes a SHA-256 content hash over the normalized JSON of `{goal, steps_summary, success}` (keys sorted, `ensure_ascii=False`). It queries for an existing active memory with the same hash for the same user. If found, the write is skipped and `None` is returned.

The hash is stored in the `content_hash` column (String(64)) for efficient lookup.

### 5. Storage

The `MemoryRepository.create()` method persists the memory to the `memories` table with all fields including `content` (JSON column with the raw goal/steps/success), `content_hash`, `importance_score`, `confidence_score`, and `source_task_id`.

### 6. Retrieval

See the [Retrieval](#memory-retrieval) section below.

### 7. Expiration and Deactivation

Memories support two deactivation mechanisms:

- **Soft delete** (`disable_memory`): sets `is_active = False`. Disabled memories are excluded from all retrieval queries.
- **Hard delete** (`delete_memory`): permanently removes the row from the database.
- **TTL expiration**: the `expires_at` column (DateTime, nullable) can be set per-memory. Expired memories can be pruned by a background process (not yet implemented).

All retrieval and search operations filter on `is_active = True`.

---

## Memory Retrieval

The `MemoryRetriever` class retrieves relevant memories for injection into planner prompts. It is configured via `configs/memory.yaml`.

### Configuration

```yaml
memory:
  retrieval:
    max_results: 5          # maximum memories to return
    max_total_tokens: 1500  # token budget for injected context
    min_importance: 0.3     # minimum importance score to include
    min_confidence: 0.5     # minimum confidence score to include
    strategies:
      - keyword
      - recent_task
```

### Retrieval Strategy

The retriever uses a tiered fill strategy:

1. **Semantic search** (if `sentence-transformers` is installed): encodes the goal and top 50 candidate memories using `all-MiniLM-L6-v2`, ranks by cosine similarity, takes top N.
2. **Keyword search** (always available): extracts up to 5 keywords from the goal (after removing stop words), performs ILIKE search on `title` and `summary` for each keyword (3 results per keyword), deduplicates.
3. **Recent high-importance fallback**: fills remaining slots with the highest-importance active memories, ordered by `importance_score DESC, created_at DESC`.

After collecting candidates, the retriever:

1. Filters by `importance_score >= min_importance` AND `confidence_score >= min_confidence`.
2. Sorts by **time-adjusted score** (see below).
3. Truncates to `max_results`.
4. Enforces the token budget.

### Time-Adjusted Scoring

The retriever applies time decay and recency boosting to rank memories:

```
adjusted_score = base_importance * (DECAY_FACTOR_PER_DAY ^ age_days)
```

- `DECAY_FACTOR_PER_DAY = 0.95` -- each day reduces the score by 5%.
- `RECENCY_BOOST_DAYS = 7` -- memories younger than 7 days receive a `* 1.3` multiplier.
- Handles both tz-aware and tz-naive `created_at` values.

### Token Budget Enforcement

Token estimation uses a rough heuristic of 1 token per 4 characters. Each memory entry contributes `len(title) + len(summary) + 50` characters of overhead. Memories are included in priority order until the cumulative estimate exceeds `max_total_tokens`. The `MemoryRetrievalResult.truncated` flag indicates whether memories were dropped due to budget.

### Result Format

```python
class MemoryRetrievalResult(BaseModel):
    memories: list[dict[str, Any]]  # list of {id, title, summary, memory_type, importance_score}
    total_count: int                # count before budget truncation
    token_estimate: int             # estimated tokens of included memories
    truncated: bool                 # True if budget was exceeded
```

---

## Memory to Planner Integration Flow

The memory system feeds into the planner through the `MemoryRetriever.retrieve()` method. The intended integration flow is:

```
User submits a new task goal
        |
        v
  MemoryRetriever.retrieve(db, goal=goal, user_id=..., edition=...)
        |
        v
  MemoryRetrievalResult (top relevant memories within token budget)
        |
        v
  Planner receives memories as context in its prompt
        |
        v
  Planner generates a plan informed by past experience
        |
        v
  Executor runs the plan
        |
        v
  On completion: MemoryService.write_from_task() stores new memory
```

Key design decisions:
- Retrieval is **read-only** -- it never modifies memories.
- The token budget ensures planner prompts do not exceed context window limits.
- Time decay ensures stale memories naturally fall out of relevance.
- Deduplication prevents the memory store from growing with redundant entries.

---

## API Endpoints

All memory endpoints are mounted under `/api/v1/memory` (configured in `apps/api_server/main.py`).

| Method | Path | Description | Parameters |
|---|---|---|---|
| GET | `/api/v1/memory/search` | Search memories by keyword, type, or source task | `keyword`, `memory_type`, `source_task_id`, `limit` |
| GET | `/api/v1/memory` | List memories with pagination | `page`, `page_size`, `memory_type`, `is_active` |
| GET | `/api/v1/memory/{memory_id}` | Get a single memory by ID | -- |
| POST | `/api/v1/memory/{memory_id}/disable` | Soft-delete a memory (set `is_active=False`) | -- |
| DELETE | `/api/v1/memory/{memory_id}` | Permanently delete a memory | -- |

Memory writing is not exposed as a direct REST endpoint. It is triggered internally by the executor after task completion, or by the `PersonalContextService` for user-facing preference/reminder management.

---

## Edition-Specific Behavior

### Enterprise Edition

- Available memory types: `EXECUTION_EXPERIENCE`, `WORKFLOW_PATTERN`, `DOMAIN_KNOWLEDGE`, `ERROR_SOLUTION`.
- Default edition for all memory operations.
- Memories are scoped to the enterprise context.
- Retrieval focuses on workflow patterns and error solutions to improve task automation.

### Personal Edition

- All 9 memory types are available, including `USER_PREFERENCE`, `PERSONAL_PROJECT`, `FILE_KNOWLEDGE`, `REMINDER`, `DAILY_CONTEXT`.
- Managed through `PersonalContextService` which provides typed accessors:
  - `get_user_preferences()` -- retrieve saved user preferences.
  - `get_project_context()` -- retrieve personal project context.
  - `get_active_reminders()` -- retrieve pending reminders.
  - `get_daily_context()` -- retrieve today's context aggregated from daily context memories and active reminders.
  - `save_preference(key, value)` -- persist a user preference as a `USER_PREFERENCE` memory.
  - `save_reminder(title, description)` -- persist a reminder as a `REMINDER` memory.
- Personal edition memories use `edition="personal"` for isolation from enterprise memories.

---

## Data Model

The `Memory` SQLAlchemy model (`packages/db/models.py`):

| Column | Type | Description |
|---|---|---|
| `id` | String(36) | UUID primary key |
| `user_id` | String(100) | Owner user, default `"default"` |
| `edition` | Enum(Edition) | `enterprise` or `personal` |
| `memory_type` | Enum(MemoryType) | One of 9 memory types |
| `title` | String(500) | Short title from summarization |
| `summary` | Text | Detailed summary from summarization |
| `content` | JSON | Raw task content: `{goal, steps, success}` |
| `content_hash` | String(64) | SHA-256 for deduplication |
| `importance_score` | Float | Final importance score [0.0, 1.0] |
| `confidence_score` | Float | Confidence in accuracy [0.0, 1.0] |
| `source_task_id` | String(36) | Link to the originating task |
| `is_active` | Boolean | Soft-delete flag, default `True` |
| `expires_at` | DateTime | Optional TTL expiration |
| `created_at` | DateTime | Auto-set on creation |
| `updated_at` | DateTime | Auto-set on update |

Index: `ix_memories_user_active` on `(user_id, is_active)` for efficient retrieval queries.

---

## File Reference

| File | Purpose |
|---|---|
| `packages/memory/memory_service.py` | Write lifecycle orchestration |
| `packages/memory/retriever.py` | Retrieval with keyword/semantic/budget strategies |
| `packages/memory/summarizer.py` | LLM and rule-based summarization |
| `packages/memory/importance_scorer.py` | Importance scoring algorithm |
| `packages/memory/schemas.py` | Pydantic schemas: `MemoryWriteRequest`, `MemorySummary`, `MemoryRetrievalResult` |
| `packages/db/repositories/memory_repo.py` | SQLAlchemy CRUD operations |
| `packages/db/models.py` | `Memory` model and `MemoryType` enum |
| `packages/personal_context/personal_context_service.py` | Personal edition memory management |
| `configs/memory.yaml` | Retrieval thresholds and type configuration |
| `apps/api_server/routes/memory.py` | REST API endpoints |
