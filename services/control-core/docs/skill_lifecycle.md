# Skill Lifecycle

## Overview

The Skill system is the self-evolving core of the Myself-Agent platform. It automatically extracts reusable workflow templates from successfully completed tasks, stores them as versioned "skills," and injects them into future planning to improve efficiency and consistency over time.

A **skill** is a named, versioned template consisting of an ordered sequence of tool calls (steps) with generalized argument placeholders. Skills enable the agent to recognize recurring task patterns and reuse proven execution plans rather than re-planning from scratch every time.

### Source Files

| Component | Path |
|---|---|
| Service (orchestrator) | `packages/skills/skill_service.py` |
| Extractor | `packages/skills/skill_extractor.py` |
| Registry (CRUD, versioning) | `packages/skills/skill_registry.py` |
| Evaluator (metrics, degradation) | `packages/skills/skill_evaluator.py` |
| Schemas | `packages/skills/schemas.py` |
| DB Repository | `packages/db/repositories/skill_repo.py` |
| DB Models | `packages/db/models.py` (`Skill`, `SkillRun`, `SkillStatus`) |
| API Routes | `apps/api_server/routes/skills.py` |
| Configuration | `configs/skills.yaml` |

---

## Lifecycle States

Every skill progresses through a defined set of states tracked by the `SkillStatus` enum:

```
                  approve
  CANDIDATE ──────────────> STABLE
      │                       │
      │ (re-extraction        │ (degradation
      │  bumps version)       │  triggers disable)
      │                       │
      └───────────────────────┤
                              v
                           DISABLED ──rollback──> STABLE
                              │
                              │ (max versions
                              │  exceeded)
                              v
                          DEPRECATED
```

| State | Description | Behavior |
|---|---|---|
| **candidate** | Newly extracted skill awaiting human approval. Not yet available for planning. | Can be approved or left as-is. Re-extraction of the same skill name creates a new version (still candidate). |
| **stable** | Approved and active. Injected into planning prompts when keyword-matched. | Monitored by the evaluator for degradation. Eligible for planner injection. |
| **disabled** | Removed from active use due to poor performance or manual intervention. | Not injected into planning. Can be rolled back to stable. |
| **deprecated** | Automatically set when version count exceeds the maximum (5). | Only the oldest stable version is deprecated to make room for newer ones. |

---

## Skill Extraction Flow

Extraction happens automatically when a task completes successfully. The `SkillService.on_task_completed()` method coordinates the process.

### Prerequisites

A skill is only extracted when **all** of the following conditions are met:

1. The task completed successfully (`success=True`).
2. At least **2 completed steps** are present in the task (configurable via `min_steps` parameter, default `2`).
3. The steps have status `"completed"` or `"approved"`.

### Extraction Process

```
Task completes
    │
    v
SkillExtractor.extract(goal, steps, success)
    │
    ├─ Filter completed/approved steps
    ├─ Check min_steps threshold (>= 2)
    ├─ Generate name from goal (meaningful words, stop-word filtered)
    ├─ Build steps_template with generalized args
    ├─ Extract tags from tool name prefixes
    │
    v
SkillExtractionResult { extracted: true, skill: SkillDefinition }
    │
    v
SkillRegistryService.create(definition, edition, source_task_id)
    │
    ├─ Dedup check: find existing skill by name + edition
    │   ├─ No match: create new skill v1 (candidate)
    │   └─ Match found: compare definition hash
    │       ├─ Hash unchanged: return existing (skip)
    │       └─ Hash changed: create new version N+1 (candidate)
    │
    v
AuditEvent: SKILL_EXTRACTED
```

### Name Generation

Skill names are derived from the task goal by:
1. Lowercasing and splitting on punctuation/whitespace.
2. Removing stop words (`the`, `a`, `an`, `and`, `or`, `to`, `from`, `for`, `with`, `in`, `on`, `of`).
3. Taking the first 5 meaningful words (length > 2), joined with underscores.
4. Falling back to an MD5-based hash if no meaningful words remain.
5. Truncating to 200 characters maximum.

Example: `"Generate a comprehensive API documentation from OpenAPI spec"` becomes `generate_comprehensive_api_documentation_openapi`.

### Argument Generalization

Specific argument values are generalized into templates during extraction:

- URLs (`http://...` or `https://...`) become `{{url}}`.
- Strings longer than 50 characters become `{{<key_name>}}`.
- All other values are kept as-is.

This allows the skill template to be reusable across similar tasks with different concrete inputs.

### Tag Extraction

Tags are derived from the root tool name of each step. For a step using `file_system.read_file`, the tag `file_system` is extracted. Duplicate tags are deduplicated.

---

## Skill Approval Workflow

Newly extracted skills enter the **candidate** state and require **human approval** before they can be used by the Planner. This is a deliberate safety gate -- unapproved skills cannot influence plan generation.

### Approval Process

1. A candidate skill is created via `SkillRegistryService.create()`.
2. An `Approval` record is created in the `approvals` table with `approval_type=SKILL` and `status=PENDING`.
3. A human reviewer reviews the skill definition (steps, tags, description).
4. The reviewer calls `POST /api/v1/skills/{skill_id}/approve`.
5. `SkillRegistryService.approve()` transitions the skill from `candidate` to `stable`.
6. An audit event `SKILL_APPROVED` is recorded.

### Constraints

- Only skills with status `candidate` can be approved. Attempting to approve a skill in any other state raises `ValueError`.
- Re-extraction of an existing skill name creates a new **version** in `candidate` status, even if a prior version is already `stable`. The new version must be approved independently.

---

## Skill Reuse in Planning

Once a skill reaches `stable` status, it becomes available for injection into the Planner's prompt. This allows the LLM to reference proven execution patterns when constructing plans for similar tasks.

### Matching Logic

`SkillService.get_skills_for_planner(db, goal, edition)` performs the following:

1. Queries all `stable` skills for the given edition.
2. For each skill, checks if **any tag** appears as a substring of the goal (case-insensitive).
3. Additionally checks if **any word** from the skill name (split on underscores) appears in the goal.
4. Returns at most **5** matching skills, each containing `id`, `name`, `description`, `steps_template`, and `success_rate`.

### Planner Integration

Skills are passed to `PlannerService.plan()` as an optional `skills` parameter. The `build_planning_prompt()` function in `packages/planner/prompt_templates.py` formats them into a section titled **"Approved Skills (Reusable Plans)"** within the system prompt, listing up to 5 skills with their names and descriptions.

```python
# PlannerService.plan() signature
async def plan(
    self,
    goal: str,
    edition: str = "enterprise",
    memories: list[dict] | None = None,
    skills: list[dict] | None = None,  # <-- injected here
) -> Plan
```

### Example Prompt Section

```
## Approved Skills (Reusable Plans)
- generate_api_documentation_openapi: Auto-extracted skill from task: Generate a comprehensive API documentation from OpenAPI spec
- deploy_container_docker: Auto-extracted skill from task: Deploy application to production with Docker
```

---

## Skill Metrics and Auto-Degradation

The `SkillEvaluator` continuously monitors the performance of stable skills and automatically degrades those that underperform.

### Tracked Metrics

Each skill tracks:
- **`success_rate`** (float): Ratio of successful runs to total runs (0.0 - 1.0).
- **`total_runs`** (int): Total number of recorded executions.
- **`consecutive_failures`** (computed at check time): Number of most recent consecutive failures.

### Run Recording

`SkillService.record_skill_run()` delegates to `SkillEvaluator.record_run()`:

1. A `SkillRun` record is created via `SkillRepository.add_run()` with `skill_id`, `task_id`, `success`, optional `metrics`, and optional `error`.
2. The skill's `success_rate` and `total_runs` are recalculated from all runs.
3. A degradation check is performed immediately.

### Degradation Rules

A stable skill is degraded when **either** condition is met:

| Condition | Threshold | Default |
|---|---|---|
| Consecutive failures | `>= consecutive_failures_limit` | **3** |
| Success rate (with 3+ runs) | `< min_success_rate` | **< 70%** |

### Degradation Action

Configured in `configs/skills.yaml` under `skills.degradation.action`:

- **`disable`** (default): Sets skill status to `DISABLED`. The skill is removed from planning but can be rolled back.
- **`downgrade`**: Sets skill status to `DEPRECATED`. A more permanent removal.

### Configuration

```yaml
# configs/skills.yaml
skills:
  degradation:
    consecutive_failures: 3    # Max consecutive failures before degradation
    min_success_rate: 0.7       # Minimum success rate (70%)
    action: disable             # "disable" or "downgrade"
```

These values are loaded by `SkillEvaluator.__init__()` from the YAML config and can be customized per deployment.

### Audit Trail

When a skill is degraded, an audit event is recorded with type `TASK_FAILED` and detail:
```json
{
  "action": "skill_degraded",
  "skill_id": "...",
  "skill_name": "...",
  "reason": "3 consecutive failures (limit: 3)",
  "new_status": "disabled"
}
```

---

## Skill Versioning and Rollback

### Versioning

When a skill with the same name is re-extracted from a new task, the system creates a new version rather than overwriting the existing one:

1. The definition hash (SHA-256 of tool names in the steps template, truncated to 16 hex chars) is compared.
2. If the hash matches, the existing skill is returned unchanged (no new version).
3. If the hash differs, a new version (`existing.version + 1`) is created in `candidate` status.

### Max Versions

The system retains a maximum of **5 versions** per skill name (configurable via `max_versions` in `configs/skills.yaml` and `SkillRegistryService(max_versions=...)`). When the limit is exceeded:

- The **oldest version** with `STABLE` status is automatically set to `DEPRECATED`.
- This frees capacity for the newest version.

### Rollback

A `DISABLED` skill can be restored to `STABLE` status via the rollback mechanism:

- **API**: `POST /api/v1/skills/{skill_id}/rollback`
- **Service**: `SkillService.rollback_skill()` delegates to `SkillRegistryService.rollback()`
- **Constraint**: Only skills with status `DISABLED` can be rolled back. Attempting to rollback a skill in any other state raises `ValueError`.
- **Behavior**: The skill status is set back to `STABLE`, making it immediately available for planner injection again.

---

## API Endpoints

All skill endpoints are mounted under `/api/v1/skills` (configured in `apps/api_server/main.py`).

### List Skills

```
GET /api/v1/skills?edition=enterprise&status=stable&page=1&page_size=20
```

**Query Parameters:**
- `edition` (optional): Filter by edition (`enterprise` or `personal`).
- `status` (optional): Filter by status (`candidate`, `stable`, `disabled`, `deprecated`).
- `page` (optional): Page number (default 1).
- `page_size` (optional): Items per page (default 20).

**Response:** `SkillListResponse` with array of `SkillResponse` objects.

### Get Skill Detail

```
GET /api/v1/skills/{skill_id}
```

**Response:** `SkillResponse` with full skill data including definition, metrics, and version info.

**Error:** `404` if skill not found.

### Approve Skill

```
POST /api/v1/skills/{skill_id}/approve
```

Transitions a candidate skill to stable.

**Response:** `ResponseBase` with confirmation message.

**Errors:** `404` if skill not found or not in candidate status.

### Disable Skill

```
POST /api/v1/skills/{skill_id}/disable
```

Manually disables a skill (sets status to `DISABLED`).

**Response:** `ResponseBase` with confirmation message.

**Error:** `404` if skill not found.

### Rollback Skill

```
POST /api/v1/skills/{skill_id}/rollback
```

Restores a disabled skill back to stable status.

**Response:** `ResponseBase` with confirmation message.

**Errors:** `404` if skill not found. `ValueError` if skill is not in `DISABLED` status.

---

## Integration with Other Subsystems

### Planner

Skills are injected into the planning prompt as a `"## Approved Skills (Reusable Plans)"` section. The Planner receives skill metadata (name, description, success rate) and can use this information to generate plans that align with proven patterns. The integration flows through:

1. `SkillService.get_skills_for_planner()` selects matching stable skills.
2. `PlannerService.plan(goal, skills=...)` receives the skills.
3. `build_planning_prompt()` formats skills into the LLM system prompt.

### Policy Engine

The Policy Engine enforces approval requirements. Skills in `candidate` status are blocked from planning injection by design -- the `get_skills_for_planner()` method only queries `status="stable"`. The policy configuration in `configs/skills.yaml` controls:

- `auto_extract`: Whether skills are extracted automatically from completed tasks.
- `approval_required`: Whether human approval is needed (enforced at the service level).
- `max_versions`: How many versions of a skill are retained.
- `auto_rollback_on_failure`: Configuration flag (not yet implemented in code).

### Memory System

Skills and Memory are complementary but distinct subsystems:
- **Memory** stores free-form past experiences (title + summary) that provide contextual knowledge to the Planner.
- **Skills** store structured, executable workflow templates with proven step sequences.

Both are injected into the planning prompt as separate sections, allowing the LLM to leverage both general knowledge (memory) and concrete execution patterns (skills) when generating plans.

### Audit System

The following audit events are recorded for skill operations:

| Event Type | Trigger | Detail Fields |
|---|---|---|
| `SKILL_EXTRACTED` | New skill created from task | `skill_id`, `skill_name`, `version` |
| `SKILL_APPROVED` | Skill approved to stable | `skill_id`, `skill_name` |
| `TASK_FAILED` | Skill degraded | `action`, `skill_id`, `skill_name`, `reason`, `new_status` |

### Executor

The Executor records skill run results via `SkillService.record_skill_run()` after executing a task that used a skill. Each run records success/failure, optional performance metrics, and any error messages. This feedback loop is what enables the auto-degradation system to function.

---

## Database Schema

### `skills` Table

| Column | Type | Description |
|---|---|---|
| `id` | `String(36)` | UUID primary key |
| `edition` | `Enum(Edition)` | `enterprise` or `personal` |
| `name` | `String(200)` | Unique per edition (within latest version) |
| `version` | `Integer` | Version number (starts at 1) |
| `status` | `Enum(SkillStatus)` | `candidate`, `stable`, `disabled`, `deprecated` |
| `definition` | `JSON` | Full skill definition (name, description, steps_template, tags, hash) |
| `description` | `Text` (nullable) | Human-readable description |
| `success_rate` | `Float` | Ratio of successful runs (0.0 - 1.0) |
| `total_runs` | `Integer` | Total execution count |
| `source_task_id` | `String(36)` (nullable) | Task that produced this skill |
| `created_at` | `DateTime` | Auto-set via `_TimestampMixin` |
| `updated_at` | `DateTime` | Auto-updated via `_TimestampMixin` |

### `skill_runs` Table

| Column | Type | Description |
|---|---|---|
| `id` | `String(36)` | UUID primary key |
| `skill_id` | `String(36)` | FK to `skills.id` |
| `task_id` | `String(36)` | FK to the task that used this skill |
| `success` | `Boolean` | Whether the run succeeded |
| `metrics` | `JSON` (nullable) | Optional performance metrics |
| `error` | `Text` (nullable) | Error message if failed |
| `created_at` | `DateTime` | Auto-set via `_TimestampMixin` |

Index: `ix_skill_runs_skill_id` on `skill_id`.

---

## Configuration Reference

Full configuration in `configs/skills.yaml`:

```yaml
skills:
  auto_extract: true              # Enable/disable automatic extraction
  states:                         # Defined lifecycle states
    - candidate
    - stable
    - disabled
    - deprecated
  approval_required: true         # Human approval gate
  degradation:
    consecutive_failures: 3       # Failures before auto-disable
    min_success_rate: 0.7         # Minimum success rate (70%)
    action: disable               # "disable" or "downgrade"
  max_versions: 5                 # Max versions per skill name
  auto_rollback_on_failure: false # Future: auto-rollback disabled skills
```
