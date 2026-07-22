"""Tests for v1 execution-domain schemas.

Per spec P0.1 acceptance: each schema has valid / invalid / boundary tests,
covering the core invariants:
- ActorScope mandatory on commands
- PolicyDecision three-state invariant (approval_spec iff WAIT_APPROVAL)
- CapabilityGrant digest-only + break_glass rule
- EffectRecord UNKNOWN_OUTCOME first-class
- hash/digest format validation (64-char hex)
- optimistic concurrency (expected_revision)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.protocol.schemas.enums import (
    SCHEMA_VERSION,
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
)
from packages.protocol.schemas.v1 import (
    APPROVAL_DEFAULT_TTL_SECONDS,
    GRANT_DEFAULT_TTL_SECONDS,
    ActorScope,
    ApprovalRequest,
    ApprovalSpec,
    AuditRecord,
    CapabilityGrant,
    CapabilityReport,
    Command,
    EffectRecord,
    ExternalReference,
    GrantSpec,
    Lease,
    PlanVersion,
    PolicyDecision,
    ResourceScope,
    Run,
    StepRun,
    Task,
    ToolReceipt,
)

HEX64 = "a" * 64
HEX64_B = "b" * 64
BAD_DIGEST = "xyz"   # not 64 hex
NOW = datetime.now(tz=None)  # naive UTC convention per schema


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def actor() -> ActorScope:
    return ActorScope(
        tenant_id="tnt-1",
        workspace_id="ws-1",
        principal_id="user-1",
        roles=frozenset({"operator"}),
        permissions=frozenset({"task:submit"}),
        auth_method="oidc",
    )


@pytest.fixture
def resource_scope() -> ResourceScope:
    return ResourceScope(
        workspace_id="ws-1",
        root_paths=["/workspace/proj"],
        network_egress_allowlist=[],
    )


# ---------------------------------------------------------------------------
# ActorScope
# ---------------------------------------------------------------------------

class TestActorScope:
    def test_valid(self, actor: ActorScope) -> None:
        assert actor.tenant_id == "tnt-1"
        assert "operator" in actor.roles

    def test_missing_tenant_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ActorScope(tenant_id="", principal_id="u", auth_method="oidc")

    def test_missing_principal_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ActorScope(tenant_id="t", principal_id="", auth_method="oidc")

    def test_no_auth_method_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ActorScope(tenant_id="t", principal_id="u")  # type: ignore[call-arg]

    def test_frozen_roles_are_frozenset(self, actor: ActorScope) -> None:
        assert isinstance(actor.roles, frozenset)
        assert isinstance(actor.permissions, frozenset)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class TestCommand:
    def test_valid_submit(self, actor: ActorScope) -> None:
        c = Command(
            command_type=CommandType.SUBMIT,
            aggregate_id=uuid4(),
            actor_scope=actor,
            payload={"goal": "demo"},
        )
        assert c.status == CommandStatus.ACCEPTED
        assert c.schema_version == SCHEMA_VERSION

    def test_extra_field_rejected(self, actor: ActorScope) -> None:
        with pytest.raises(ValidationError):
            Command(
                command_type=CommandType.SUBMIT,
                aggregate_id=uuid4(),
                actor_scope=actor,
                payload={},
                bogus_field="x",  # type: ignore[call-arg]
            )

    def test_optimistic_concurrency(self, actor: ActorScope) -> None:
        c = Command(
            command_type=CommandType.EXECUTE,
            aggregate_id=uuid4(),
            actor_scope=actor,
            payload={},
            expected_revision=5,
        )
        assert c.expected_revision == 5

    def test_negative_revision_rejected(self, actor: ActorScope) -> None:
        with pytest.raises(ValidationError):
            Command(
                command_type=CommandType.CANCEL,
                aggregate_id=uuid4(),
                actor_scope=actor,
                payload={},
                expected_revision=-1,
            )


# ---------------------------------------------------------------------------
# PlanVersion
# ---------------------------------------------------------------------------

class TestPlanVersion:
    def test_valid(self) -> None:
        pv = PlanVersion(
            task_id=uuid4(),
            version=1,
            plan_digest=HEX64,
            plan_json={"steps": []},
        )
        assert pv.version == 1

    def test_bad_digest_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanVersion(
                task_id=uuid4(),
                version=1,
                plan_digest=BAD_DIGEST,
                plan_json={},
            )

    def test_zero_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PlanVersion(
                task_id=uuid4(),
                version=0,
                plan_digest=HEX64,
                plan_json={},
            )


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

class TestTask:
    def test_default_status_pending(self) -> None:
        t = Task(tenant_id="t", goal="hello")
        assert t.status == TaskStatus.PENDING
        assert t.revision == 0

    def test_external_reference_optional(self) -> None:
        t = Task(
            tenant_id="t",
            goal="x",
            external_reference=ExternalReference(
                source_system="tianshu", source_id="task-7"
            ),
        )
        assert t.external_reference is not None
        assert t.external_reference.source_system == "tianshu"

    def test_empty_goal_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Task(tenant_id="t", goal="")


# ---------------------------------------------------------------------------
# Run / StepRun
# ---------------------------------------------------------------------------

class TestRun:
    def test_attempt_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Run(
                task_id=uuid4(),
                attempt_number=0,
                plan_version_id=uuid4(),
            )

    def test_needs_attention_is_first_class(self) -> None:
        r = Run(task_id=uuid4(), attempt_number=1, plan_version_id=uuid4())
        r.status = RunStatus.NEEDS_ATTENTION
        assert r.status == RunStatus.NEEDS_ATTENTION


class TestStepRun:
    def test_valid(self) -> None:
        sr = StepRun(
            run_id=uuid4(),
            task_id=uuid4(),
            ordinal=1,
            tool_name="file.read",
            args={"path": "/x"},
            normalized_args_hash=HEX64,
        )
        assert sr.status == StepRunStatus.PENDING
        assert sr.effect_class == EffectClass.READ_ONLY

    def test_bad_hash_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepRun(
                run_id=uuid4(),
                task_id=uuid4(),
                ordinal=1,
                tool_name="file.read",
                args={},
                normalized_args_hash="not-a-hash",
            )

    def test_zero_ordinal_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StepRun(
                run_id=uuid4(),
                task_id=uuid4(),
                ordinal=0,
                tool_name="x",
                args={},
                normalized_args_hash=HEX64,
            )


# ---------------------------------------------------------------------------
# PolicyDecision (the critical three-state invariant)
# ---------------------------------------------------------------------------

class TestPolicyDecision:
    def _base(self, outcome: PolicyOutcome) -> PolicyDecision:
        return PolicyDecision(
            step_run_id=uuid4(),
            outcome=outcome,
            reason="test",
            risk_level=RiskLevel.HIGH,
            policy_digest=HEX64,
        )

    def test_deny_must_not_carry_specs(self) -> None:
        d = self._base(PolicyOutcome.DENY)
        assert d.approval_spec is None
        assert d.grant_spec is None

    def test_wait_approval_requires_approval_spec(self) -> None:
        with pytest.raises(ValueError, match="WAIT_APPROVAL requires approval_spec"):
            self._base(PolicyOutcome.WAIT_APPROVAL)

    def test_wait_approval_with_spec_ok(self) -> None:
        sid = uuid4()
        d = PolicyDecision(
            step_run_id=sid,
            outcome=PolicyOutcome.WAIT_APPROVAL,
            reason="high risk",
            risk_level=RiskLevel.HIGH,
            policy_digest=HEX64,
            approval_spec=ApprovalSpec(
                step_run_id=sid,
                normalized_args_hash=HEX64,
                risk_level=RiskLevel.HIGH,
                resource_scope=ResourceScope(),
                policy_digest=HEX64,
                security_context_digest=HEX64,
                expires_at=NOW + timedelta(seconds=APPROVAL_DEFAULT_TTL_SECONDS),
            ),
        )
        assert d.approval_spec is not None

    def test_grant_requires_grant_spec(self) -> None:
        with pytest.raises(ValueError, match="GRANT requires grant_spec"):
            self._base(PolicyOutcome.GRANT)

    def test_deny_with_specs_rejected(self) -> None:
        # A DENY carrying approval_spec must be rejected even via construct.
        sid = uuid4()
        with pytest.raises(ValueError, match="DENY must not carry"):
            PolicyDecision.model_construct(
                step_run_id=sid,
                outcome=PolicyOutcome.DENY,
                reason="test",
                risk_level=RiskLevel.LOW,
                policy_digest=HEX64,
                decided_at=NOW,
                approval_spec=ApprovalSpec(
                    step_run_id=sid,
                    normalized_args_hash=HEX64,
                    risk_level=RiskLevel.LOW,
                    resource_scope=ResourceScope(),
                    policy_digest=HEX64,
                    security_context_digest=HEX64,
                    expires_at=NOW + timedelta(seconds=60),
                ),
                grant_spec=None,
            )


# ---------------------------------------------------------------------------
# CapabilityGrant (digest-only + break_glass rule)
# ---------------------------------------------------------------------------

class TestCapabilityGrant:
    def _make(self, **overrides) -> CapabilityGrant:  # type: ignore[no-untyped-def]
        defaults = dict(
            step_run_id=uuid4(),
            handle_digest=HEX64,
            nonce="n" * 8,
            bound_args_hash=HEX64,
            risk_level=RiskLevel.HIGH,
            resource_scope=ResourceScope(),
            security_context_digest=HEX64,
            approval_resolution_id=uuid4(),
            expires_at=NOW + timedelta(seconds=GRANT_DEFAULT_TTL_SECONDS),
        )
        defaults.update(overrides)
        return CapabilityGrant(**defaults)

    def test_valid(self) -> None:
        g = self._make()
        assert g.status == GrantStatus.ISSUED
        assert g.max_uses == 1

    def test_break_glass_allows_no_approval(self) -> None:
        g = self._make(key_id="break_glass", approval_resolution_id=None)
        assert g.key_id == "break_glass"

    def test_non_break_glass_requires_approval(self) -> None:
        with pytest.raises(ValueError, match="approval_resolution_id"):
            self._make(approval_resolution_id=None)

    def test_expiry_before_issued_rejected(self) -> None:
        # Pin issued_at explicitly so the post_init comparison is deterministic.
        with pytest.raises(ValueError, match="expires_at must be after"):
            self._make(
                issued_at=NOW + timedelta(seconds=60),
                expires_at=NOW,
            )

    def test_bad_digest_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make(handle_digest=BAD_DIGEST)


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------

class TestLease:
    def test_valid(self) -> None:
        lz = Lease(
            worker_id="w-1",
            step_run_id=uuid4(),
            fencing_token=42,
            expires_at=NOW + timedelta(seconds=30),
        )
        assert lz.fencing_token == 42

    def test_expiry_in_past_rejected(self) -> None:
        # Pin created_at so the comparison is deterministic.
        with pytest.raises(ValueError, match="expires_at must be after"):
            Lease(
                worker_id="w-1",
                step_run_id=uuid4(),
                fencing_token=0,
                created_at=NOW + timedelta(seconds=60),
                expires_at=NOW,
            )


# ---------------------------------------------------------------------------
# EffectRecord + ToolReceipt (UNKNOWN_OUTCOME first-class)
# ---------------------------------------------------------------------------

class TestEffectRecord:
    def _make(self, **overrides) -> EffectRecord:  # type: ignore[no-untyped-def]
        defaults = dict(
            step_run_id=uuid4(),
            grant_id=uuid4(),
            lease_id=uuid4(),
            fencing_token=1,
            effect_class=EffectClass.NON_RETRYABLE,
            security_context_digest=HEX64,
        )
        defaults.update(overrides)
        return EffectRecord(**defaults)

    def test_default_prepared(self) -> None:
        e = self._make()
        assert e.status == EffectStatus.PREPARED

    def test_unknown_outcome_first_class(self) -> None:
        e = self._make()
        e.status = EffectStatus.UNKNOWN_OUTCOME
        assert e.status == EffectStatus.UNKNOWN_OUTCOME
        # critical: unknown != failed
        assert e.status != EffectStatus.FAILED

    def test_bad_digest_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._make(security_context_digest=BAD_DIGEST)


class TestToolReceipt:
    def test_succeeded(self) -> None:
        r = ToolReceipt(
            effect_id=uuid4(),
            tool_name="file.read",
            args_hash=HEX64,
            status=ReceiptStatus.SUCCEEDED,
        )
        assert r.status == ReceiptStatus.SUCCEEDED

    def test_unknown_allowed(self) -> None:
        r = ToolReceipt(
            effect_id=uuid4(),
            tool_name="browser.click",
            args_hash=HEX64,
            status=ReceiptStatus.UNKNOWN,
        )
        assert r.status == ReceiptStatus.UNKNOWN

    def test_bad_hash_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolReceipt(
                effect_id=uuid4(),
                tool_name="x",
                args_hash="short",
                status=ReceiptStatus.SUCCEEDED,
            )


# ---------------------------------------------------------------------------
# AuditRecord + ExternalReference + CapabilityReport
# ---------------------------------------------------------------------------

class TestAuditRecord:
    def test_valid(self, actor: ActorScope) -> None:
        a = AuditRecord(
            classification=Classification.CONFIDENTIAL,
            actor=actor,
            action="task.submit",
            resource={"task_id": str(uuid4())},
        )
        assert a.prev_hash is None  # first record

    def test_optional_hex_validation(self, actor: ActorScope) -> None:
        with pytest.raises(ValidationError):
            AuditRecord(
                classification=Classification.INTERNAL,
                actor=actor,
                action="x",
                resource={},
                prev_hash="not-hex",
            )


class TestExternalReference:
    def test_default_resolved(self) -> None:
        r = ExternalReference(source_system="tianshu", source_id="t-7")
        assert r.status == "resolved"

    def test_unresolved(self) -> None:
        r = ExternalReference(
            source_system="wizard", source_id="s-1", status="unresolved"
        )
        assert r.status == "unresolved"


class TestCapabilityReport:
    def test_valid(self) -> None:
        r = CapabilityReport(
            capabilities=frozenset({Capability.SECRET_STORE, Capability.LOCAL_IPC}),
            platform="windows",
            platform_version="10.0.26200",
        )
        assert Capability.SECRET_STORE in r.capabilities

    def test_unsupported_reasons(self) -> None:
        r = CapabilityReport(
            capabilities=frozenset(),
            platform="linux",
            platform_version="6.19",
            unsupported_reasons={Capability.SCREEN_CAPTURE: "no portal"},
        )
        assert Capability.SCREEN_CAPTURE in r.unsupported_reasons
