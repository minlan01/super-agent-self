"""Execution domain schemas — v1 (frozen).

Per spec v1.1 §4.3 Core Execution Contract. Defines the 12 core schemas that
form the v1 protocol boundary:

    Command → PlanVersion → PolicyDecision → ApprovalRequest
        → CapabilityGrant → Lease → EffectRecord → ToolReceipt → AuditRecord

Plus ActorScope (identity carrier) and ExternalReference (legacy mapping).

Design rules (spec §2.3):
1. Every schema carries schema_version for protocol negotiation.
2. ActorScope is mandatory on every write command; request bodies never carry
   forgeable identity (no user_id/tenant_id accepted from client).
3. CapabilityGrant is an opaque handle; only its digest is persisted.
4. EffectRecord is the FIRST persistence step before any adapter invocation.
5. UNKNOWN_OUTCOME is a first-class state — never collapsed into failed.

These schemas are transport-layer Pydantic models. DB ORM mappings (P0.5+)
will reuse the enums from enums.py but define their own SQLAlchemy columns.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import (
    SCHEMA_VERSION,
    ApprovalInvalidationReason,
    ApprovalResolution,
    ApprovalStatus,
    Capability,
    Classification,
    CommandStatus,
    CommandType,
    ContentProvenance,
    EffectClass,
    EffectStatus,
    ErrorCode,
    GrantStatus,
    PolicyOutcome,
    ReceiptStatus,
    RiskLevel,
    RunStatus,
    StepRunStatus,
    TaskStatus,
    WorkerStatus,
)

# Default timezone convention: all datetimes are UTC naive. We document this
# rather than pulling in zoneinfo to keep the protocol layer dependency-free.
EPOCH = datetime(1970, 1, 1)
GRANT_DEFAULT_TTL_SECONDS = 300        # 5 minutes
APPROVAL_DEFAULT_TTL_SECONDS = 86400   # 24 hours
LEASE_DEFAULT_TTL_SECONDS = 30         # WorkerBroker LEASE_TTL


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class _V1Base(BaseModel):
    """Common config for all v1 schemas."""
    model_config = ConfigDict(
        frozen=False,             # ORM-friendly; callers can patch
        extra="forbid",           # reject unknown fields — strict contract
        use_enum_values=False,    # keep enum types for validation
        str_strip_whitespace=True,
        ser_json_timedelta="iso8601",
    )


def _now() -> datetime:
    """UTC now, naive. Avoids tz-aware comparison pitfalls in tests and
    sidesteps the datetime.utcnow() deprecation."""
    return datetime.now(tz=None)


def _uuid() -> UUID:
    return uuid4()


def _hex64(s: str) -> str:
    """Validate a 64-char lowercase hex string (SHA-256 digest format)."""
    if len(s) != 64 or any(c not in "0123456789abcdef" for c in s):
        raise ValueError(f"expected 64-char hex digest, got len={len(s)}")
    return s


# ---------------------------------------------------------------------------
# 1. ActorScope — identity carrier (spec §2.3 + §4.2)
# ---------------------------------------------------------------------------

class ResourceScope(_V1Base):
    """Bound resource scope for an action. Crosses into Grant binding."""
    workspace_id: str | None = None
    root_paths: list[str] = Field(default_factory=list)
    network_egress_allowlist: list[str] = Field(default_factory=list)
    external_refs: dict[str, str] = Field(default_factory=dict)


class ActorScope(_V1Base):
    """Identity of the actor issuing a command. Bound from auth context,
    NEVER accepted from request body (anti-forgery, spec §2.3)."""
    tenant_id: str = Field(..., min_length=1, description="Mandatory tenant")
    workspace_id: str = Field(default="default")
    principal_id: str = Field(..., min_length=1, description="user id")
    roles: frozenset[str] = Field(default_factory=frozenset)
    permissions: frozenset[str] = Field(default_factory=frozenset)
    auth_method: str = Field(..., description="oidc / api_key / local")
    device_id: str | None = None
    os_session_id: str | None = None
    resource_scope: ResourceScope = Field(default_factory=ResourceScope)


# ---------------------------------------------------------------------------
# 2. Command — the Command Bus write model (spec §4.3)
# ---------------------------------------------------------------------------

class Command(_V1Base):
    """A durable command. Every state mutation starts here."""
    command_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    command_type: CommandType
    aggregate_id: UUID = Field(..., description="target Task id")
    actor_scope: ActorScope
    payload: dict[str, Any] = Field(..., description="command-specific payload")
    idempotency_key: str | None = Field(default=None, max_length=128)
    expected_revision: int | None = Field(
        default=None, ge=0, description="optimistic concurrency token"
    )
    deadline: datetime | None = None
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    created_at: datetime = Field(default_factory=_now)
    status: CommandStatus = CommandStatus.ACCEPTED
    applied_at: datetime | None = None


# ---------------------------------------------------------------------------
# 3. PlanVersion — immutable plan digest (spec §4.3)
# ---------------------------------------------------------------------------

class PlanVersion(_V1Base):
    """A frozen, digest-stamped plan. Re-execution never overwrites history."""
    plan_version_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    task_id: UUID
    version: int = Field(..., ge=1)
    plan_digest: str = Field(..., description="SHA-256 of normalized plan JSON")
    plan_json: dict[str, Any]
    created_at: datetime = Field(default_factory=_now)

    @field_validator("plan_digest")
    @classmethod
    def _validate_digest(cls, v: str) -> str:
        return _hex64(v)


# ---------------------------------------------------------------------------
# 4. Task + 5. Run + 6. StepRun (spec §4.3)
# ---------------------------------------------------------------------------

class Task(_V1Base):
    """Stable intent. Survives retries. Only mutated via Orchestrator."""
    task_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    tenant_id: str
    goal: str = Field(..., min_length=1)
    status: TaskStatus = TaskStatus.PENDING
    current_plan_version_id: UUID | None = None
    revision: int = Field(default=0, ge=0, description="bumped on each write")
    risk_level: RiskLevel = RiskLevel.LOW
    external_reference: "ExternalReference | None" = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Run(_V1Base):
    """One execution attempt of a Task. Retries create new Runs, never overwrite."""
    run_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    task_id: UUID
    attempt_number: int = Field(..., ge=1)
    plan_version_id: UUID
    status: RunStatus = RunStatus.DISPATCHED
    started_at: datetime = Field(default_factory=_now)
    completed_at: datetime | None = None
    error_code: ErrorCode | None = None
    error_detail: str | None = None


class StepRun(_V1Base):
    """One step's execution attempt within a Run. Retries bump ordinal."""
    step_run_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    run_id: UUID
    task_id: UUID
    ordinal: int = Field(..., ge=1)
    tool_name: str = Field(..., min_length=1)
    args: dict[str, Any]
    normalized_args_hash: str = Field(..., description="SHA-256 of canonical args")

    status: StepRunStatus = StepRunStatus.PENDING
    risk_level: RiskLevel = RiskLevel.LOW
    effect_class: EffectClass = EffectClass.READ_ONLY
    sandbox_profile_digest: str | None = None
    capability_manifest_digest: str | None = None

    approval_request_id: UUID | None = None
    grant_id: UUID | None = None
    lease_id: UUID | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("normalized_args_hash")
    @classmethod
    def _validate_hash(cls, v: str) -> str:
        return _hex64(v)


# ---------------------------------------------------------------------------
# 7. PolicyDecision (spec §4.3 + D2)
# ---------------------------------------------------------------------------

class ApprovalSpec(_V1Base):
    """Returned by Policy when outcome=WAIT_APPROVAL."""
    step_run_id: UUID
    normalized_args_hash: str
    risk_level: RiskLevel
    resource_scope: ResourceScope
    policy_digest: str
    security_context_digest: str
    expires_at: datetime

    @field_validator("policy_digest", "security_context_digest", "normalized_args_hash")
    @classmethod
    def _validate_digests(cls, v: str) -> str:
        return _hex64(v)


class GrantSpec(_V1Base):
    """Returned by Policy when outcome=GRANT. Carries the material needed by
    GrantIssuer to mint the CapabilityGrant handle."""
    step_run_id: UUID
    risk_level: RiskLevel
    resource_scope: ResourceScope
    effect_class: EffectClass
    approval_resolution_id: UUID | None = None
    security_context_digest: str
    ttl_seconds: int = GRANT_DEFAULT_TTL_SECONDS

    @field_validator("security_context_digest")
    @classmethod
    def _validate_digest(cls, v: str) -> str:
        return _hex64(v)


class PolicyDecision(_V1Base):
    """The three-state outcome of PolicyEngine.decide(). Replaces the old
    PolicyResult(allowed, requires_approval, token) tuple."""
    schema_version: str = SCHEMA_VERSION
    step_run_id: UUID
    outcome: PolicyOutcome
    reason: str = Field(..., min_length=1)
    risk_level: RiskLevel
    policy_digest: str
    decided_at: datetime = Field(default_factory=_now)
    approval_spec: ApprovalSpec | None = None
    grant_spec: GrantSpec | None = None

    @field_validator("policy_digest")
    @classmethod
    def _validate_digest(cls, v: str) -> str:
        return _hex64(v)

    def model_post_init(self, __context: Any) -> None:
        """Invariant: approval_spec iff WAIT_APPROVAL; grant_spec iff GRANT."""
        if self.outcome == PolicyOutcome.WAIT_APPROVAL and self.approval_spec is None:
            raise ValueError("WAIT_APPROVAL requires approval_spec")
        if self.outcome == PolicyOutcome.GRANT and self.grant_spec is None:
            raise ValueError("GRANT requires grant_spec")
        if self.outcome == PolicyOutcome.DENY and (
            self.approval_spec is not None or self.grant_spec is not None
        ):
            raise ValueError("DENY must not carry approval_spec or grant_spec")


# ---------------------------------------------------------------------------
# 8. ApprovalRequest + 9. CapabilityGrant (spec §4.3)
# ---------------------------------------------------------------------------

class ApprovalRequest(_V1Base):
    """Persisted approval gate. resolve() triggers a Resume Command (spec D3)."""
    approval_request_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    step_run_id: UUID
    actor_scope: ActorScope
    normalized_args_hash: str
    risk_level: RiskLevel
    policy_digest: str
    resource_scope: ResourceScope
    security_context_digest: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    expires_at: datetime
    created_at: datetime = Field(default_factory=_now)
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution: ApprovalResolution | None = None

    @field_validator(
        "normalized_args_hash", "policy_digest", "security_context_digest"
    )
    @classmethod
    def _validate_digests(cls, v: str) -> str:
        return _hex64(v)


class CapabilityGrant(_V1Base):
    """Opaque handle authorizing a single Tool invocation.

    The plaintext handle is returned to the caller; only its digest is
    persisted (spec §4.3 + v3 §4A). Verifies: nonce, bound_args_hash,
    resource_scope, security_context_digest, expiry, max_uses=1.
    """
    grant_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    step_run_id: UUID
    handle_digest: str = Field(..., description="SHA-256 of the opaque handle")
    nonce: str = Field(..., min_length=8)
    bound_args_hash: str
    risk_level: RiskLevel
    resource_scope: ResourceScope
    security_context_digest: str
    approval_resolution_id: UUID | None = None
    key_id: str = "default"
    status: GrantStatus = GrantStatus.ISSUED
    issued_at: datetime = Field(default_factory=_now)
    expires_at: datetime = Field(...)
    consumed_at: datetime | None = None
    max_uses: int = 1

    @field_validator(
        "handle_digest", "bound_args_hash", "security_context_digest"
    )
    @classmethod
    def _validate_digests(cls, v: str) -> str:
        return _hex64(v)

    def model_post_init(self, __context: Any) -> None:
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if self.approval_resolution_id is None and self.key_id != "break_glass":
            raise ValueError(
                "high-risk Grant requires approval_resolution_id "
                "(break_glass key_id is the only exemption)"
            )


# ---------------------------------------------------------------------------
# 10. Lease (spec §4.3 + §4.2)
# ---------------------------------------------------------------------------

class Lease(_V1Base):
    """A Worker's claim on a StepRun. Carries fencing_token (monotonic per worker)
    to prevent stale workers from committing results (spec §4.3)."""
    lease_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    worker_id: str
    step_run_id: UUID
    fencing_token: int = Field(..., ge=0)
    expires_at: datetime
    created_at: datetime = Field(default_factory=_now)
    last_heartbeat_at: datetime | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.expires_at <= self.created_at:
            raise ValueError("lease expires_at must be after created_at")


# ---------------------------------------------------------------------------
# 11. EffectRecord + 12. ToolReceipt (spec §4.3 + v3 M9)
# ---------------------------------------------------------------------------

class EffectRecord(_V1Base):
    """Side-effect protocol record. Four phases:
    PREPARE (before adapter call) → ACQUIRE_DISPATCH (verify grant, mint token)
    → CALL_ADAPTER (invoke tool) → FINALIZE (record receipt).

    UNKNOWN_OUTCOME is a first-class state (spec v3 M9).
    """
    effect_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    step_run_id: UUID
    grant_id: UUID
    lease_id: UUID
    fencing_token: int
    status: EffectStatus = EffectStatus.PREPARED
    effect_class: EffectClass
    provider_idempotency_key: str | None = None
    security_context_digest: str
    created_at: datetime = Field(default_factory=_now)
    finalized_at: datetime | None = None

    @field_validator("security_context_digest")
    @classmethod
    def _validate_digest(cls, v: str) -> str:
        return _hex64(v)


class ToolReceipt(_V1Base):
    """Standardized result of a Tool invocation. The adapter always returns one;
    status=unknown is allowed when the tool could not determine outcome."""
    receipt_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    effect_id: UUID
    tool_name: str
    args_hash: str
    status: ReceiptStatus
    result: dict[str, Any] | None = None
    error_code: ErrorCode | None = None
    error_message: str | None = None
    content_provenance: ContentProvenance | None = None
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime = Field(default_factory=_now)

    @field_validator("args_hash")
    @classmethod
    def _validate_hash(cls, v: str) -> str:
        return _hex64(v)


# ---------------------------------------------------------------------------
# AuditRecord (spec §4.3 + §9)
# ---------------------------------------------------------------------------

class AuditRecord(_V1Base):
    """Append-only audit row. Hash-chained for tamper-evidence (spec §9)."""
    audit_record_id: UUID = Field(default_factory=_uuid)
    schema_version: str = SCHEMA_VERSION
    classification: Classification
    actor: ActorScope
    action: str
    resource: dict[str, Any]
    command_id: UUID | None = None
    task_id: UUID | None = None
    run_id: UUID | None = None
    step_run_id: UUID | None = None
    approval_id: UUID | None = None
    grant_id: UUID | None = None
    lease_id: UUID | None = None
    effect_id: UUID | None = None
    receipt_id: UUID | None = None
    prev_hash: str | None = None
    signature: str | None = None
    key_id: str | None = None
    created_at: datetime = Field(default_factory=_now)

    @field_validator("prev_hash", "signature")
    @classmethod
    def _optional_hex64(cls, v: str | None) -> str | None:
        return v if v is None else _hex64(v)


# ---------------------------------------------------------------------------
# ExternalReference (legacy data mapping, spec §2.5 + §6A)
# ---------------------------------------------------------------------------

class ExternalReference(_V1Base):
    """Maps legacy entities (tianshu tasks, wizard.db scenarios) into the new
    schema. status=unresolved means the mapping is provisional (spec §6A)."""
    source_system: str = Field(..., description="tianshu / wizard / openclaw ...")
    source_id: str
    status: str = Field(default="resolved", description="resolved|unresolved|conflict|tombstoned")
    imported_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# Capability discovery (spec §4.4)
# ---------------------------------------------------------------------------

class CapabilityReport(_V1Base):
    """Returned by PlatformAdapter.get_capabilities(). UI/API use this to
    present accurate state — never silent fallback (spec §5.2)."""
    schema_version: str = SCHEMA_VERSION
    capabilities: frozenset[Capability]
    platform: str = Field(..., description="windows / linux / macos")
    platform_version: str
    unsupported_reasons: dict[Capability, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Re-export
# ---------------------------------------------------------------------------

__all__ = [
    # base
    "SCHEMA_VERSION",
    "EPOCH",
    "GRANT_DEFAULT_TTL_SECONDS",
    "APPROVAL_DEFAULT_TTL_SECONDS",
    "LEASE_DEFAULT_TTL_SECONDS",
    # 1
    "ActorScope",
    "ResourceScope",
    # 2
    "Command",
    # 3
    "PlanVersion",
    # 4-6
    "Task",
    "Run",
    "StepRun",
    # 7
    "PolicyDecision",
    "ApprovalSpec",
    "GrantSpec",
    # 8-9
    "ApprovalRequest",
    "CapabilityGrant",
    # 10
    "Lease",
    # 11-12
    "EffectRecord",
    "ToolReceipt",
    # audit + misc
    "AuditRecord",
    "ExternalReference",
    "CapabilityReport",
]


# Forward ref resolve
Task.model_rebuild()
