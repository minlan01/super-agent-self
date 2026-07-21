# Edition System

## Overview

The platform ships in two editions -- **Enterprise** and **Personal** -- each with its own YAML configuration that governs which tools are available, what memory types are used, how long data is retained, and how the policy engine enforces approvals.

Editions exist so that the same codebase can serve two fundamentally different use-cases:

- **Enterprise**: a controlled, security-first agent platform for teams. Shell access and desktop control are forbidden; private network URLs are blocked; memory retention is short (90 days); approvals require a written reason.
- **Personal** (a.k.a. "Personal Jarvis"): an individual assistant with richer memory types (reminders, daily context, user preferences), longer retention (365 days), and additional personal-only tools such as file search and file summarization.

The active edition is selected at deployment time and flows through every layer of the system -- from the policy engine to the memory retriever to the planner prompts.

## Edition Configuration Files

Edition definitions live in `configs/editions/` as YAML files. Each file must contain at minimum the `edition` key; all other sections are optional and fall back to sensible defaults.

```
configs/editions/
  enterprise.yaml
  personal.yaml
```

### YAML Schema

```yaml
edition: <string>              # Unique edition identifier (e.g. "enterprise")
name: <string>                 # Human-readable name
description: <string>          # Short description

tools:
  enabled: [<string>]          # Tool names available in this edition
  disabled: [<string>]         # Tool names explicitly forbidden

policy:
  max_risk_level: <low|medium|high>   # Highest risk the edition tolerates
  require_approval_for: [<level>]     # Risk levels that need human approval
  forbidden_tools: [<string>]         # Tools that are never allowed
  forbidden_paths: [<string>]         # File-system paths the agent cannot access
  allowed_url_patterns: [<regex>]     # URL patterns the agent may visit
  forbidden_url_patterns: [<regex>]   # URL patterns the agent must not visit

memory:
  types: [<string>]            # Memory types this edition may store
  retention_days: <int>        # How long memories are kept (default: 90)

approval:
  auto_approve_low_risk: <bool>        # Auto-approve low-risk actions (default: true)
  require_reason: <bool>               # Require a reason for approvals (default: false)
  confirm_before: [<string>]           # Tool names that always need confirmation
```

### Enterprise Edition (`configs/editions/enterprise.yaml`)

```yaml
edition: enterprise
name: Enterprise Edition
description: Enterprise-grade controlled Agent platform

tools:
  enabled:
    - browser.open
    - browser.click
    - browser.extract_text
    - browser.screenshot
    - file.write_docx
    - file.write_markdown
    - file.read
    - file.list
  disabled:
    - shell.run
    - desktop.control
    - system.modify

policy:
  max_risk_level: medium
  require_approval_for:
    - high
  forbidden_tools:
    - shell.run
    - desktop.control
  forbidden_paths:
    - /etc
    - /root
    - C:\Windows
    - C:\Program Files
  allowed_url_patterns:
    - "https?://.*"
  forbidden_url_patterns:
    - "https?://localhost.*"
    - "https?://127\\.0\\.0\\..*"
    - "https?://192\\.168\\..*"
    - "https?://10\\..*"

memory:
  types:
    - execution_experience
    - workflow_pattern
    - domain_knowledge
    - error_solution
  retention_days: 90

approval:
  auto_approve_low_risk: true
  require_reason: true
```

### Personal Edition (`configs/editions/personal.yaml`)

```yaml
edition: personal
name: Personal Jarvis Edition
description: Personal AI assistant with extended capabilities (Phase 2+)

tools:
  enabled:
    - browser.open
    - browser.click
    - browser.extract_text
    - browser.screenshot
    - file.write_docx
    - file.write_markdown
    - file.read
    - file.list
    - file.search
    - file.summarize
  disabled:
    - shell.run
    - desktop.control
    - system.modify

policy:
  max_risk_level: medium
  require_approval_for:
    - high
    - medium
  forbidden_tools:
    - shell.run
    - desktop.control
  forbidden_paths:
    - /etc
    - /root
    - C:\Windows
    - C:\Program Files
  allowed_url_patterns:
    - "https?://.*"
  forbidden_url_patterns:
    - "https?://localhost.*"

memory:
  types:
    - execution_experience
    - user_preference
    - personal_project
    - file_knowledge
    - reminder
    - daily_context
    - workflow_pattern
  retention_days: 365

approval:
  auto_approve_low_risk: true
  require_reason: false
  confirm_before:
    - file.delete
    - message.send
    - form.submit
```

## EditionManager API

`EditionManager` (in `packages/agent_core/edition_manager.py`) is the single entry point for reading edition configuration at runtime. It loads all YAML files from the editions directory on construction.

### Construction

```python
from packages.agent_core.edition_manager import EditionManager

mgr = EditionManager()                       # defaults to configs/editions/
mgr = EditionManager(editions_dir="/custom")  # custom directory
```

If the directory does not exist, the manager logs a warning and operates with an empty set of editions (no crash).

### Public Methods

| Method | Signature | Description |
|---|---|---|
| `get_config` | `(edition: str) -> dict` | Returns the full YAML config dict for the given edition, or `{}` if unknown. |
| `get_enabled_tools` | `(edition: str) -> list[str]` | Tool names listed under `tools.enabled`. |
| `get_disabled_tools` | `(edition: str) -> list[str]` | Tool names listed under `tools.disabled`. |
| `get_max_risk_level` | `(edition: str) -> str` | `policy.max_risk_level`, defaults to `"medium"`. |
| `get_memory_types` | `(edition: str) -> list[str]` | `memory.types`, the memory types this edition may use. |
| `get_retention_days` | `(edition: str) -> int` | `memory.retention_days`, defaults to `90`. |
| `auto_approve_low_risk` | `(edition: str) -> bool` | `approval.auto_approve_low_risk`, defaults to `True`. |
| `is_personal` | `(edition: str) -> bool` | `True` when `edition == "personal"`. |
| `is_enterprise` | `(edition: str) -> bool` | `True` when `edition == "enterprise"`. |
| `list_editions` | `() -> list[str]` | All loaded edition identifiers. |
| `get_name` | `(edition: str) -> str` | Human-readable name from the YAML, or title-cased key as fallback. |
| `get_description` | `(edition: str) -> str` | Description string from the YAML. |

### REST API

The API server exposes edition information through two endpoints (see `apps/api_server/routes/editions.py`):

```
GET /api/v1/editions
GET /api/v1/editions/{edition}
```

The list endpoint returns name and description for every edition. The detail endpoint returns the full breakdown of tools, policy, and memory settings, plus `is_personal` and `is_enterprise` booleans.

## How Editions Affect Other Components

### Policy Engine

The `PolicyEngine.check()` method accepts an `edition` parameter (default `"enterprise"`). During a check it:

1. Verifies the tool is registered in the `ToolRegistry`.
2. Calls `ToolRegistry.is_available_for_edition(tool_name, edition)` -- if the tool definition has an `edition` field (a list of edition names, or `None` for "all editions"), the tool must be listed there.
3. Applies the edition's `max_risk_level` cap.
4. Checks against the edition's `forbidden_tools`, `forbidden_paths`, and `forbidden_url_patterns`.

```python
# In packages/policy/tool_registry.py
@dataclass
class ToolDefinition:
    name: str
    description: str
    risk_level: str
    parameters: dict
    edition: list[str] | None = None  # None = all editions

    def is_available_for_edition(self, edition: str) -> bool:
        if self.edition is None:
            return True
        return edition in self.edition
```

### Memory

Both `MemoryService` and `MemoryRetriever` accept an `edition` parameter when storing and querying memories. The edition value is stored on each `Memory` row and used as a filter during retrieval, so memories created under one edition are invisible to another.

The edition YAML determines:
- **Which memory types** can be stored (e.g. `reminder` and `daily_context` are Personal-only).
- **Retention period** -- 90 days for Enterprise, 365 days for Personal.

### Planner Prompts

In the Personal edition, the planner uses `build_personal_planning_prompt()` from `packages/planner/personal_prompts.py`. This prompt includes sections for past experiences, user preferences, active reminders, and available skills -- information that is gathered from the memory and personal-context subsystems and only relevant when `is_personal()` is `True`.

### Skills

The `ToolRegistry` tracks each tool's edition affinity via the `edition` field on `ToolDefinition`. Tools that are personal-only (e.g. `file.search`, `file.summarize`) are registered with `edition: ["personal"]`. The planner and executor query `list_tools(edition=...)` to build the tool set that the LLM is allowed to use for the current edition.

## Comparison Table

| Feature | Enterprise | Personal |
|---|---|---|
| **Name** | Enterprise Edition | Personal Jarvis Edition |
| **Max risk level** | medium | medium |
| **Approval required for** | high | high, medium |
| **Approval reason required** | yes | no |
| **Confirm-before actions** | -- | file.delete, message.send, form.submit |
| **Auto-approve low risk** | yes | yes |
| **Memory retention** | 90 days | 365 days |
| **Memory types** | execution_experience, workflow_pattern, domain_knowledge, error_solution | execution_experience, user_preference, personal_project, file_knowledge, reminder, daily_context, workflow_pattern |
| **Unique tools** | (none) | file.search, file.summarize |
| **Forbidden tools** | shell.run, desktop.control, system.modify | shell.run, desktop.control, system.modify |
| **Private network URLs blocked** | yes (127.0.0.0/8, 192.168.0.0/16, 10.0.0.0/8) | no (only localhost) |
| **Forbidden paths** | /etc, /root, C:\Windows, C:\Program Files | /etc, /root, C:\Windows, C:\Program Files |

## Adding a New Edition

To introduce a custom edition:

1. Create a new YAML file in `configs/editions/` (e.g. `starter.yaml`).
2. Define `edition`, `tools`, `policy`, `memory`, and `approval` sections as needed.
3. The `EditionManager` will auto-discover it on next startup (it globs `*.yaml`).
4. Register any edition-specific tools in the `ToolRegistry` with `edition: ["starter"]`.
5. Update the policy engine, memory service, and planner if the new edition requires unique behavior.
