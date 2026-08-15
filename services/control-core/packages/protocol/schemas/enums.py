"""Execution domain enumerations — v1 schema (frozen).

Per spec v1.1 §4.3 Core Execution Contract + §4.4 Platform Interface.

These enums are the single source of truth for execution-domain state values.
They are versioned together as schema v1 and MUST NOT be mutated in place;
new values require a schema bump (v2, v3, ...).

Imported by:
- packages/protocol/schemas/v1.py (the 12 schemas)
- packages/db/models.py (future ORM mappings, P0.5+)
- packages/agent_core/orchestrator.py (future ExecutionControl, P0.5+)
"""

from __future__ import annotations

from enum import StrEnum

# ---------------------------------------------------------------------------
# Schema version (for protocol negotiation)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"
"""Immutable version tag for this schema set. Bump on any breaking change."""


# ---------------------------------------------------------------------------
# Task lifecycle (unchanged from existing TaskStatus, re-declared for v1 freeze)
# ---------------------------------------------------------------------------

class TaskStatus(StrEnum):
    """Task lifecycle state. DAG, not linear."""
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Run / StepRun lifecycle (NEW — Run and StepRun are separate from Task)
# ---------------------------------------------------------------------------

class RunStatus(StrEnum):
    """A single execution attempt of a Task. Retries create new Runs."""
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_ATTENTION = "needs_attention"
    """Run finished but at least one Effect has unknown_outcome — human review."""
    COMPLETED_WITH_UNKNOWN = "completed_with_unknown"
    """All Effects confirmed/failed deterministically but ≥1 was unknown then resolved."""


class StepRunStatus(StrEnum):
    """A single step's execution attempt within a Run."""
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    """Effect is unknown_outcome; awaiting human/automated reconciliation."""


# ---------------------------------------------------------------------------
# Policy outcome (three-state, replaces boolean allowed + requires_approval)
# ---------------------------------------------------------------------------

class PolicyOutcome(StrEnum):
    """The three allowed outcomes of PolicyEngine.decide()."""
    DENY = "deny"
    WAIT_APPROVAL = "wait_approval"
    GRANT = "grant"


# ---------------------------------------------------------------------------
# Approval lifecycle
# ---------------------------------------------------------------------------

class ApprovalStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class ApprovalResolution(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalInvalidationReason(StrEnum):
    CONTEXT_CHANGED = "context_changed"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


# ---------------------------------------------------------------------------
# Capability Grant (opaque handle bound to a single execution)
# ---------------------------------------------------------------------------

class GrantStatus(StrEnum):
    ISSUED = "issued"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REVOKED = "revoked"


# ---------------------------------------------------------------------------
# Worker / Lease
# ---------------------------------------------------------------------------

class WorkerStatus(StrEnum):
    REGISTERED = "registered"
    ACTIVE = "active"
    DRAINING = "draining"
    OFFLINE = "offline"


# ---------------------------------------------------------------------------
# Effect / Receipt — the side-effect protocol (spec §4.3 + v3 M9)
# ---------------------------------------------------------------------------

class EffectClass(StrEnum):
    """Classifies a tool's side-effect semantics. Drives retry policy."""
    READ_ONLY = "read_only"
    """No external state change. Safe to retry freely."""
    PROVIDER_IDEMPOTENT = "provider_idempotent"
    """Provider supports idempotency key; retry with same key dedupes downstream."""
    RECONCILABLE = "reconcilable"
    """Not idempotent, but outcome can be verified by a reconcile operation."""
    NON_RETRYABLE = "non_retryable"
    """Not idempotent and not reconcilable. Unknown outcome → manual review only."""


class EffectStatus(StrEnum):
    """Six-state machine for a single side-effect. UNKNOWN_OUTCOME is first-class."""
    PREPARED = "prepared"
    """EffectRecord persisted before adapter invocation."""
    DISPATCHING = "dispatching"
    """Grant verified, fencing token issued, adapter invoked, awaiting receipt."""
    CONFIRMED = "confirmed"
    """ToolReceipt.status=succeeded, durably recorded."""
    FAILED = "failed"
    """ToolReceipt.status=failed (deterministic failure)."""
    UNKNOWN_OUTCOME = "unknown_outcome"
    """Could not confirm or fail (e.g. timeout, worker crash, missing receipt).
    First-class state — MUST NOT collapse into failed. Drives reconciliation queue."""
    MANUAL_REVIEW = "manual_review"
    """Promoted from unknown_outcome (operator or policy decided no auto-resolve)."""


class ReceiptStatus(StrEnum):
    """Status reported by the Tool adapter in the ToolReceipt."""
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Risk / classification / data classification
# ---------------------------------------------------------------------------

class RiskLevel(StrEnum):
    """Risk classification per spec §6 Risk Model."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Classification(StrEnum):
    """Data classification for DomainEvent/AuditRecord payloads (spec §11)."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SECRET = "secret"


class ContentProvenance(StrEnum):
    """Where a piece of content originated (spec v3 §4A)."""
    USER_INPUT = "user_input"
    TOOL_OUTPUT = "tool_output"
    LLM_GENERATED = "llm_generated"


# ---------------------------------------------------------------------------
# Command (Command Bus write model)
# ---------------------------------------------------------------------------

class CommandType(StrEnum):
    SUBMIT = "submit"
    EXECUTE = "execute"
    RESUME = "resume"
    CANCEL = "cancel"


class CommandStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PROCESSING = "processing"
    APPLIED = "applied"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Platform capability (spec §4.4)
# ---------------------------------------------------------------------------

class Capability(StrEnum):
    """Platform capability identifiers returned by capability discovery.
    Unsupported capabilities return CAPABILITY_UNAVAILABLE, never silent fallback."""
    SECRET_STORE = "secret_store"
    LOCAL_IPC = "local_ipc"
    SESSION_MONITOR = "session_monitor"
    PROCESS_SANDBOX = "process_sandbox"
    TERMINAL_SESSION = "terminal_session"
    WINDOW_PROVIDER = "window_provider"
    SCREEN_CAPTURE = "screen_capture"
    PERMISSION_BROKER = "permission_broker"
    AUTO_START = "auto_start"
    UPDATER = "updater"


# ---------------------------------------------------------------------------
# Stable error codes (spec §3.5.1 subset — extended in errors.py)
# ---------------------------------------------------------------------------

class ErrorCode(StrEnum):
    # A-segment: business
    POLICY_DENIED = "A020001"
    APPROVAL_REQUIRED = "A030001"
    APPROVAL_EXPIRED = "A030002"
    APPROVAL_REJECTED = "A030003"
    GRANT_INVALID = "A060001"
    GRANT_CONSUMED = "A060002"
    GRANT_TAMPERED = "A060003"
    LEASE_EXPIRED = "A050001"
    STALE_LEASE = "A050002"
    EFFECT_UNKNOWN_OUTCOME = "A090001"
    EFFECT_NON_RETRYABLE = "A090002"
    # v3 §4A
    STALE_SECURITY_CONTEXT = "A060004"
    # Platform
    CAPABILITY_UNAVAILABLE = "A990001"
    SANDBOX_UNAVAILABLE = "A990002"
    STALE_UI_STATE = "A990003"
    # B-segment: system
    INTERNAL_ERROR = "B999001"
    DB_UNAVAILABLE = "B999002"
    REDIS_UNAVAILABLE = "B999003"
    # C-segment: HTTP (non-exhaustive)
    HTTP_BAD_REQUEST = "C400001"
    HTTP_UNAUTHORIZED = "C401001"
    HTTP_FORBIDDEN = "C403001"
    HTTP_NOT_FOUND = "C404001"
    HTTP_CONFLICT = "C409001"
    HTTP_UNPROCESSABLE = "C422001"
    HTTP_TOO_MANY_REQUESTS = "C429001"
