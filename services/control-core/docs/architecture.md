# Architecture

## Overview

The Controlled Agent Platform is a dual-edition, self-evolving agent system that decomposes user goals into planned steps, validates each step through a policy engine, and executes them with full auditability. It learns from completed tasks by extracting reusable skills and persisting memories.

Version: **3.0.0**

## Core Components

### Task System (`packages/agent_core/`)

The task system manages the full lifecycle of a user goal through a state machine.

- **Task Model**: Stores goal, edition, status, risk level, and final result/error
- **TaskStep Model**: Each planned action becomes a step with tool name, args, risk level, capability token hash, and execution result
- **TaskStateMachine**: Enforces valid status transitions:

```
PENDING --> PLANNING --> AWAITING_APPROVAL --> EXECUTING --> COMPLETED
                       |                     |              |
                       +--> CANCELLED        +--> CANCELLED +--> FAILED
                             |                     |
                             +--> FAILED           +--> FAILED
```

Terminal states: `COMPLETED`, `FAILED`, `CANCELLED`.

### Planner (`packages/planner/`)

Generates execution plans via the LLM gateway.

- **PlannerService**: Sends the goal + available tools + memories + skills to the LLM, parses the JSON plan, and validates it with retry logic (up to 2 retries by default)
- **PlanValidator**: Ensures every step references a registered tool and that args match the tool's JSON schema
- **Prompt Templates**: Builds structured prompts with tool summaries, edition constraints, and injected context
- **Personal Prompts**: Injects user preferences, reminders, memories, and skills for personal edition planning

### Policy Engine (`packages/policy/`)

A security gate that checks every tool execution before it runs.

- **PolicyEngine**: 7-check pipeline (see Security Model for details)
- **ToolRegistry**: Loads tool definitions from `configs/tools.yaml` with name, category, risk level, edition availability, and parameter schema
- **CapabilityToken**: HMAC-SHA256 signed token binding execution to a specific task_id, step_id, tool_name, and args hash (5-minute expiry)
- **Risk Rules**: Functions for path containment, forbidden URL patterns, risk level limits, and args hash verification

### Executor (`packages/executor/`)

Executes validated plan steps sequentially.

- **ExecutorService**: Iterates plan steps, runs policy check for each, executes via ToolRunner, and stops on first failure (remaining steps are marked `SKIPPED`)
- **ToolRunner**: Dispatches to concrete tool implementations by name
- **Tool Implementations** (`packages/executor/tools/`):
  - `base.py`: `ExecutionContext` dataclass (task_id, step_id, edition)
  - `file_tools.py`: `file.write_docx`, `file.write_markdown`, `file.read`, `file.list`
  - `browser_tools.py`: `browser.open`, `browser.click`, `browser.extract_text`, `browser.screenshot`
  - `personal_tools.py`: `file.search`, `file.summarize` (personal edition)
  - `browser_enhanced.py`: `browser.bookmark`, `browser.monitor` (personal edition)
  - `desktop_tools.py`: `desktop.click`, `desktop.type`, `desktop.screenshot` (safety-restricted)

### Memory (`packages/memory/`)

Long-term experience storage that feeds back into future planning.

- **MemoryService**: Writes memories from completed tasks with deduplication via content hashing
- **MemoryRetriever**: Retrieves relevant memories for planner injection using keyword search + recent high-importance fallback, with token budget enforcement (default 1500 tokens)
- **MemorySummarizer**: Generates summaries and importance/confidence scores
- **ImportanceScorer**: Combines base importance, task success, and step count into a final score
- **Memory Types**: `execution_experience`, `workflow_pattern`, `domain_knowledge`, `error_solution`, `user_preference`, `personal_project`, `file_knowledge`, `reminder`, `daily_context`

### Skills (`packages/skills/`)

Self-evolving reusable workflow templates extracted from successful tasks.

- **SkillService**: Coordinates extraction, approval, retrieval, and metrics tracking
- **SkillExtractor**: Extracts skill templates from successful tasks (min 2 completed steps), generalizing specific args into templates
- **SkillRegistryService**: CRUD for skills with lifecycle transitions: `candidate` -> `stable` -> `disabled` / `deprecated`
- **SkillEvaluator**: Tracks success rate per skill, auto-disables on 3+ consecutive failures or success rate below 70%
- **Planner Integration**: Approved stable skills are matched by keyword to the current goal and injected as plan suggestions (max 5 skills)

### Orchestrator (`packages/agent_core/orchestrator.py`)

Connects all components for the full task lifecycle.

```
Orchestrator.run(goal, edition, user_id)
  1. Create task (PENDING)
  2. Transition to PLANNING
  3. PlannerService.plan(goal, tools, memories, skills) -> Plan
  4. Transition to EXECUTING
  5. ExecutorService.execute_plan(task_id, plan, context)
     For each step:
       a. PolicyEngine.check(tool_name, args, edition) -> PolicyResult
       b. If rejected: mark step REJECTED, stop
       c. If approved: store capability token hash, execute via ToolRunner
  6. Transition to COMPLETED or FAILED
```

### LLM Gateway (`packages/llm_gateway/`)

- **ProviderRouter**: Routes requests to configured LLM providers (mock, deepseek, openrouter, openai)
- **Mock Provider**: Returns deterministic responses for testing
- **DeepSeek Provider**: Calls DeepSeek API via httpx with JSON mode (shared AsyncClient connection pool)
- **OpenRouter / OpenAI Providers**: Multi-provider support with intelligent model routing

### Edition Manager (`packages/agent_core/edition_manager.py`)

Loads edition-specific configurations from YAML files and provides:

- `get_enabled_tools()`: Tools available for the edition
- `get_memory_types()`: Allowed memory types
- `get_max_risk_level()`: Maximum allowed risk level
- `get_retention_days()`: Memory retention period

### Personal Context (`packages/personal_context/`)

Personal edition context services:

- **PersonalContextService**: Aggregates user preferences, project context, reminders, and daily context
- **ReminderService**: Create, list, and dismiss time-based reminders

### Voice System (`packages/voice/`)

Speech-to-text, text-to-speech, and voice command routing:

- **SpeechToText**: Whisper-based transcription with fallback detection
- **TextToSpeech**: pyttsx3 (offline) and edge-tts (online) synthesis
- **VoiceCommandRouter**: Intent-based command routing (cancel, status, remind, browse, read, save, search)

### Vision System (`packages/vision/`)

OCR and screen capture:

- **OCRService**: Tesseract-based text extraction with graceful fallback
- **ScreenCapture**: Full-screen or region capture tool
- **ImageOCR**: OCR tool with path traversal protection

### Evaluation (`packages/evaluation/`)

Post-task quality assessment:

- **TaskEvaluator**: Calculates step success rate, efficiency, quality score, and risk metrics
- **System Metrics**: Overall task completion rates and quality tracking

### Observability (`packages/observability/`)

Structured logging for production:

- **JSONFormatter**: JSON-formatted log lines with task context
- **setup_logging()**: Configure root logger with JSON or text output
- **get_task_logger()**: Logger with pre-attached task_id and edition

## Data Flow

```
User Goal
    |
    v
[Create Task] --> PENDING
    |
    v
[Plan] --> PLANNING
    |  - Inject memories (MemoryRetriever)
    |  - Inject skills (SkillService.get_skills_for_planner)
    |  - LLM generates JSON plan
    |  - PlanValidator checks tools + schemas
    |
    v
[Execute] --> EXECUTING
    |  For each step:
    |    [Policy Check] --> 7-check pipeline
    |      |  1. Tool registered?
    |      |  2. Tool enabled?
    |      |  3. Not forbidden?
    |      |  4. Edition available?
    |      |  5. Risk within limit?
    |      |  6. Path/URL safe?
    |      |  7. Issue Capability Token
    |      |
    |      +--> APPROVED: execute tool
    |      +--> REJECTED: stop execution
    |
    v
[Complete] --> COMPLETED
    |  - MemoryService.write_from_task() (if successful)
    |  - SkillService.on_task_completed() (extract skill)
    |
    v
Result + Audit Trail
```

## Database Schema

10 tables in SQLAlchemy ORM (`packages/db/models.py`):

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `tasks` | Top-level task records | goal, status, edition, risk_level, result, error |
| `task_steps` | Individual execution steps | task_id, step_order, tool_name, args, status, capability_token_hash |
| `audit_events` | Full audit trail | task_id, step_id, event_type, actor, detail (JSON) |
| `memories` | Long-term experience store | user_id, edition, memory_type, title, summary, content (JSON), content_hash, importance_score |
| `skills` | Reusable workflow templates | edition, name, version, status, definition (JSON), success_rate, total_runs |
| `skill_runs` | Skill execution history | skill_id, task_id, success, metrics (JSON) |
| `approvals` | Human approval queue | approval_type, target_id, status, requested_by, approved_by |
| `edition_profiles` | Edition configuration store | edition, name, config (JSON) |
| `conversations` | Chat conversation sessions | user_id, edition, title |
| `conversation_messages` | Individual chat messages | conversation_id, role, content |
| `users` | User accounts for auth | username, email, hashed_password, role, is_active |

## API Server (`apps/api_server/`)

FastAPI application with route modules:

| Prefix | Routes | Description |
|--------|--------|-------------|
| `/api/v1/tasks` | CRUD + cancel + steps + audit | Task lifecycle management |
| `/api/v1/memory` | search, list, get, disable, delete | Memory exploration |
| `/api/v1/skills` | list, get, approve, disable, rollback | Skill management |
| `/api/v1/audit` | list with filters | Audit trail queries |
| `/api/v1/approvals` | list, get, resolve | Approval workflow |
| `/api/v1/personal` | reminders, context, preferences | Personal edition APIs |
| `/api/v1/editions` | list, get config | Edition configuration |
| `/api/v1/chat` | conversational interface | Intent-routed chat |
| `/api/v1/conversations` | list, get, delete | Conversation history |
| `/api/v1/cron` | CRUD, chain scheduling | Scheduled jobs |
| `/api/v1/voice` | STT, TTS, voice command | Voice interface |
| `/api/v1/export` | tasks, memories, audit (JSON/CSV) | Data export |
| `/api/v1/auth` | register, login, me | User authentication |
| `/ws/tasks/{task_id}` | WebSocket | Real-time task updates |

## Admin Web (`apps/enterprise_admin_web/`)

Vue 3 + Vite + Element Plus + Pinia admin interface:

- **Login**: User authentication with token persistence and route guards
- **Dashboard**: Stats cards, recent tasks, pending approvals, ECharts visualizations
- **TaskList**: Filterable task table with create/cancel actions
- **TaskDetail**: Step descriptions, execution timeline, audit events
- **AuditLog**: Filterable event log with pagination
- **MemoryList**: Search, filter, disable/delete memories
- **SkillList**: Status management, approve/disable/rollback
- **ApprovalList**: Pending/approved/rejected with resolve dialog
- **CronList**: Scheduled job management
- **ChatView**: Conversational AI interface
- **ConversationList**: Chat history browser
- **ExportView**: Data export (JSON/CSV)
- **HealthView**: System health monitoring

## Middleware

- **RateLimiter**: Sliding window rate limiter (60 req/min default, per client IP, health check exempt)
- **CORS**: Configurable origins (defaults to `*` for development)

## Authentication (`packages/auth/`)

User authentication with HMAC-SHA256 tokens:

- **AuthService**: Creates and verifies tokens using HMAC-SHA256 with configurable expiry
- **Token format**: `base64url(json_payload) + "." + hmac_signature`
- **Auth flow**: Register → Login → Bearer token in Authorization header
- **Security**: bcrypt password hashing, timing-safe comparison, configurable secret key
- **REQUIRE_AUTH**: Master switch (default `false` for backward compatibility)
- **Frontend**: Login.vue + Pinia auth store + Axios auth interceptor + router guards

## Configuration

All configuration lives under `configs/`:

| File | Purpose |
|------|---------|
| `app.yaml` | Application settings, CORS, workspace, security |
| `tools.yaml` | Tool definitions with risk levels and parameter schemas |
| `policy.yaml` | Policy rules: forbidden tools, path prefixes, URL patterns, approval thresholds |
| `memory.yaml` | Memory retrieval settings (max results, token budget, thresholds) |
| `skills.yaml` | Skill degradation settings (failure limits, success rate thresholds) |
| `models.yaml` | LLM model configuration |
| `cron.yaml` | Cron scheduler configuration |
| `search.yaml` | Search engine configuration (DuckDuckGo / Brave) |
| `mcp.yaml` | MCP server configuration |
| `editions/enterprise.yaml` | Enterprise edition profile |
| `editions/personal.yaml` | Personal edition profile |

## Security Model Overview

- **Capability Tokens**: Every tool execution requires an HMAC-SHA256 signed token binding it to the specific task, step, tool, and args
- **7-Forbidden Behaviors**: shell.run, desktop.control, system.modify are permanently disabled
- **6-Layer Injection Defense**: System prompt isolation, output schema enforcement, tool argument validation, structured plan parsing, capability token binding, audit logging
- **Workspace Sandboxing**: File tools are restricted to workspace paths; forbidden system paths (`/etc/`, `/root/`, `C:\Windows\`, etc.) are blocked
- **Rate Limiting**: 60 requests/minute per client IP by default
- **Desktop Safety**: pyautogui failsafe, text length limits (500 chars), dangerous key blocking

See `security_model.md` for full details.

## Edition System

The platform supports two editions with different capability profiles:

| Feature | Enterprise | Personal |
|---------|-----------|----------|
| Tools | browser.*, file.{write_docx, write_markdown, read, list} | Same + file.search, file.summarize, browser.bookmark, browser.monitor |
| Memory types | execution_experience, workflow_pattern, domain_knowledge, error_solution | All 9 types including user_preference, personal_project, reminder |
| Retention | 90 days | 365 days |
| Approval for | high risk | high + medium risk |
| Auto-approve low risk | Yes | Yes |
| Forbidden tools | shell.run, desktop.control, system.modify | Same |
| Forbidden URLs | localhost, 127.0.0.x, 192.168.x.x, 10.x.x.x | localhost only |
| Chat routing | Intent detection (task/reminder/preference/info) | Same + personal context injection |

Edition is configured per-task via the `edition` field and controls tool availability, policy thresholds, and memory behavior.

## Deployment

See `deployment.md` for Docker Compose setup, environment variables, and production configuration.
