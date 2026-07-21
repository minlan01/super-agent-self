# Security Model

The Controlled Agent Platform implements a multi-layered security model designed to keep AI-driven tool execution bounded, auditable, and safe. This document describes every security mechanism in detail.

## 1. Seven Forbidden Behaviors

The following tool categories are permanently disabled and cannot be enabled through configuration:

| Tool | Category | Risk Level | Reason |
|------|----------|------------|--------|
| `shell.run` | system | critical | Arbitrary command execution |
| `desktop.control` | desktop | critical | GUI automation (Phase 3+) |
| `system.modify` | system | critical | System settings modification |

These are enforced at two levels:

1. **Tool Registry**: The tools are defined with `enabled: false` in `configs/tools.yaml`
2. **Policy Engine**: They appear in the `forbidden_tools` list in `configs/policy.yaml`

Even if an LLM generates a plan referencing `shell.run`, the policy engine will reject it at the "Tool is not forbidden" check (check 3 of the 7-check pipeline).

## 2. Capability Token Mechanism

Every approved tool execution receives a **Capability Token** -- a signed, short-lived authorization that cryptographically binds the execution to a specific context.

### Token Structure

```python
@dataclass
class CapabilityToken:
    task_id: str          # Which task this belongs to
    step_id: str          # Which step within the task
    tool_name: str        # Which tool is authorized
    args_hash: str        # SHA256 of args, truncated to 16 chars
    issued_at: float      # Unix timestamp
    expire_minutes: int   # Default: 5
```

### Signing

Tokens are signed using HMAC-SHA256:

```python
# Key: SECRET_KEY from environment
# Payload: JSON with task_id, step_id, tool_name, args_hash, issued_at, expire_minutes
# Signature: HMAC-SHA256(key, sorted_json_payload)
# Encoding: Base64 URL-safe of JSON payload with signature field appended
```

### Verification

The `TokenIssuer.verify()` method checks:

1. **Token format**: Base64 decodes to valid JSON
2. **Signature integrity**: HMAC-SHA256 comparison using `hmac.compare_digest` (timing-safe)
3. **Field binding**: `task_id`, `step_id`, and `tool_name` must match exactly
4. **Args hash**: SHA256 of current args must match the stored `args_hash`
5. **Expiry**: `current_time > issued_at + expire_minutes * 60`

Any mismatch results in rejection with a descriptive reason string.

### Token Lifecycle

```
PolicyEngine.check()
    |
    +--> All 7 checks pass
    |       |
    |       +--> TokenIssuer.issue(task_id, step_id, tool_name, args)
    |               Returns base64-encoded signed token
    |               |
    |               v
    |         ExecutorService stores token_hash (SHA256 of token, first 32 chars)
    |         in task_step.capability_token_hash for audit
    |
    +--> Any check fails
            Returns PolicyResult(allowed=False, reason=...)
```

### Configuration (`configs/policy.yaml`)

```yaml
policy:
  token:
    algorithm: "HS256"        # HMAC-SHA256
    expire_minutes: 5         # Token validity window
    max_uses: 1               # Single-use enforcement (by design)
```

## 3. Six-Layer Prompt Injection Defense

The platform uses six independent layers to mitigate prompt injection attacks:

### Layer 1: System Prompt Isolation

The planner prompt is built through structured templates (`packages/planner/prompt_templates.py`). User input (the goal) is injected into a clearly delineated section, separated from system instructions. The prompt enforces JSON-only output format.

### Layer 2: Output Schema Enforcement

The `PlannerService` calls `provider_router.generate_json()` which forces the LLM to respond in JSON format. Any non-JSON response (including injection attempts) fails parsing and triggers a retry.

### Layer 3: Tool Argument Validation

Before execution, every tool argument is validated:
- **JSON Schema**: Each tool has a `params_schema` in `configs/tools.yaml` with `additionalProperties: false`, preventing injection of unexpected fields
- **Type checking**: Schema enforces types (string, integer, boolean, array)
- **Required fields**: Missing required parameters cause plan validation to fail

### Layer 4: Structured Plan Parsing

The `PlanValidator` validates the entire plan structure:
- Each step must reference a registered tool
- Tool arguments must conform to the tool's parameter schema
- Steps are sequentially numbered
- Invalid plans are rejected and retried (up to 2 retries), with the error message fed back to the LLM

### Layer 5: Capability Token Binding

Even after a plan passes validation, each step's execution is authorized via a capability token that binds:
- The specific task ID
- The specific step ID
- The specific tool name
- A hash of the specific arguments

If any field changes between policy check and execution, the token verification fails.

### Layer 6: Audit Logging

Every policy decision is logged as an `AuditEvent`:
- `POLICY_APPROVED`: Tool passed all checks
- `POLICY_REJECTED`: Tool was blocked (with reason)

This creates a complete, tamper-evident record of all security decisions.

## 4. Policy Engine: 7-Check Pipeline

The `PolicyEngine.check()` method runs these checks in order:

```
Check 1: Tool Registration
  - Is the tool registered in ToolRegistry?
  - Reject if: tool_name not found
  - Config: configs/tools.yaml

Check 2: Tool Enabled
  - Is the tool's enabled flag set to true?
  - Reject if: tool is disabled

Check 3: Forbidden Tools
  - Is the tool in the forbidden_tools list?
  - Reject if: tool matches a forbidden entry
  - Config: configs/policy.yaml -> policy.forbidden_tools

Check 4: Edition Availability
  - Is the tool available for the current edition?
  - Reject if: tool.edition is set and does not include current edition
  - Example: file.search is [personal] only

Check 5: Risk Level
  - Is the tool's risk level within the maximum allowed?
  - Reject if: tool.risk_level > max_allowed_risk
  - Levels: low < medium < high < critical
  - Config: configs/policy.yaml -> policy.max_allowed_risk

Check 6: Path/URL Safety (for file and browser tools)
  - File tools: Check path against forbidden_path_prefixes
  - Browser tools: Check URL against forbidden_url_patterns
  - Reject if: path or URL matches a forbidden pattern

Check 7: Capability Token Issuance
  - If all checks pass, issue a signed capability token
  - Determine if approval is needed (based on require_approval_risk_levels)
  - Return PolicyResult(allowed=True, token=..., requires_approval=...)
```

## 5. Workspace Sandboxing

### Path Restrictions

File tools (`file.write_docx`, `file.write_markdown`, `file.read`, `file.list`) have their paths validated against forbidden prefixes:

```yaml
# configs/policy.yaml
policy:
  forbidden_path_prefixes:
    - /etc/
    - /root/
    - C:\Windows\
    - C:\Program Files\
    - C:\Users\
```

The `check_forbidden_path()` function in `risk_rules.py` normalizes both the path and prefix (backslash to forward slash) before comparison.

### Workspace Containment

When `workspace_only: true` is set in policy config, `check_path_in_workspace()` ensures file operations stay within the workspace directory. Relative paths are allowed; absolute paths outside the workspace are rejected.

### URL Restrictions

Browser tools (`browser.open`, `browser.click`, etc.) have their URLs validated against forbidden patterns:

```yaml
# configs/policy.yaml
policy:
  forbidden_url_patterns:
    - "https?://localhost(:\\d+)?(/.*)?$"
    - "https?://127\\.0\\.0\\.\\d+(:\\d+)?(/.*)?$"
    - "https?://192\\.168\\.\\d+\\.\\d+(:\\d+)?(/.*)?$"
    - "https?://10\\.\\d+\\.\\d+\\.\\d+(:\\d+)?(/.*)?$"
```

This blocks access to:
- Localhost services
- Loopback addresses
- Private network ranges (192.168.x.x, 10.x.x.x)

### Tool Parameter Schema

Every tool definition includes a strict JSON schema with `additionalProperties: false`:

```yaml
file.read:
  params_schema:
    type: object
    required: [path]
    properties:
      path:
        type: string
        description: "Relative path under workspace"
    additionalProperties: false    # Rejects any extra fields
```

This prevents injection of unexpected parameters that could alter tool behavior.

## 6. Approval System

High-risk operations require human approval before execution.

### Approval Triggers

Configured per edition:
- **Enterprise**: High-risk tools require approval
- **Personal**: High and medium-risk tools require approval

### Approval Types

| Type | Trigger | Description |
|------|---------|-------------|
| `skill` | New skill candidate | Auto-extracted skills need approval before becoming stable |
| `high_risk_step` | High-risk tool execution | Steps with `risk_level=high` are held for approval |

### Approval Flow

```
Policy check determines requires_approval=true
    |
    v
Approval record created (status=PENDING)
    |
    v
Human reviews via API: POST /api/v1/approvals/{id}/resolve
    |
    +--> approved=true  --> Step proceeds to execution
    +--> approved=false --> Step is rejected
```

## 7. Risk Assessment

### Risk Levels

| Level | Numeric | Description | Approval Required |
|-------|---------|-------------|-------------------|
| `low` | 0 | Read-only, safe operations | No |
| `medium` | 1 | Limited write operations | Personal edition only |
| `high` | 2 | Significant write operations | Yes |
| `critical` | 3 | System-level operations | Always (but these are forbidden) |

### Tool Risk Assignments

| Tool | Category | Risk Level |
|------|----------|------------|
| `browser.open` | browser | low |
| `browser.click` | browser | low |
| `browser.extract_text` | browser | low |
| `browser.screenshot` | browser | low |
| `file.write_docx` | file | low |
| `file.write_markdown` | file | low |
| `file.read` | file | low |
| `file.list` | file | low |
| `file.search` | file | low |
| `file.summarize` | file | low |
| `shell.run` | system | critical (disabled) |
| `desktop.control` | desktop | critical (disabled) |
| `system.modify` | system | critical (disabled) |
