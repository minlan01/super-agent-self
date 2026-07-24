"""P2 add execution contract tables

Revision ID: p2_exec_contract
Revises: 50bdde4cc851
Create Date: 2026-07-24

Adds 5 tables implementing spec §4.3 execution contract persistence:
  - capability_grants (opaque handle digest, consume/revoke)
  - leases (fencing_token, renew/release/expire)
  - effect_records (PREPARED->DISPATCHING->terminal state machine)
  - tool_receipts (adapter result)
  - dispatch_attempts (audit-grade dispatch trace)
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "p2_exec_contract"
down_revision = "50bdde4cc851"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── capability_grants ──
    op.create_table(
        "capability_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("step_run_id", sa.String(36), nullable=False),
        sa.Column("handle_digest", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("bound_args_hash", sa.String(64), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("resource_scope", sa.JSON, nullable=False),
        sa.Column("security_context_digest", sa.String(64), nullable=False),
        sa.Column("approval_resolution_id", sa.String(36), nullable=True),
        sa.Column("key_id", sa.String(50), nullable=False, server_default="default"),
        sa.Column("status", sa.Enum("ISSUED", "CONSUMED", "EXPIRED", "REVOKED", name="grantstatusdb"),
                   nullable=False, server_default="ISSUED"),
        sa.Column("issued_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("consumed_at", sa.DateTime, nullable=True),
        sa.Column("max_uses", sa.Integer, nullable=False, server_default="1"),
        sa.Column("audience", sa.String(100), nullable=False, server_default="tool_gateway"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_grants_tenant", "capability_grants", ["tenant_id"])
    op.create_index("ix_grants_tenant_step", "capability_grants", ["tenant_id", "step_run_id"])
    op.create_index("ix_grants_handle_digest", "capability_grants", ["handle_digest"], unique=True)
    op.create_index("ix_grants_status", "capability_grants", ["status"])
    op.create_index("ix_grants_expires", "capability_grants", ["expires_at"])

    # ── leases ──
    op.create_table(
        "leases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("step_run_id", sa.String(36), nullable=False),
        sa.Column("fencing_token", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.Enum("ACTIVE", "INACTIVE", "EXPIRED", name="leasestatus"),
                   nullable=False, server_default="ACTIVE"),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_leases_tenant", "leases", ["tenant_id"])
    op.create_index("ix_leases_tenant_step", "leases", ["tenant_id", "step_run_id"])
    op.create_index("ix_leases_worker", "leases", ["worker_id"])
    op.create_index("ix_leases_status", "leases", ["status"])
    op.create_index("ix_leases_expires", "leases", ["expires_at"])

    # ── effect_records ──
    op.create_table(
        "effect_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("step_run_id", sa.String(36), nullable=False),
        sa.Column("grant_id", sa.String(36), nullable=False),
        sa.Column("lease_id", sa.String(36), nullable=False),
        sa.Column("fencing_token", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.Enum("PREPARED", "DISPATCHING", "CONFIRMED", "FAILED",
                                     "UNKNOWN_OUTCOME", "RECONCILED", name="effectstatusdb"),
                   nullable=False, server_default="PREPARED"),
        sa.Column("effect_class", sa.Enum("READ_ONLY", "PROVIDER_IDEMPOTENT",
                                           "RECONCILABLE", "NON_RETRYABLE", name="effectclassdb"),
                   nullable=False, server_default="READ_ONLY"),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("provider_idempotency_key", sa.String(128), nullable=True),
        sa.Column("security_context_digest", sa.String(64), nullable=False),
        sa.Column("before_hash", sa.String(64), nullable=True),
        sa.Column("after_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("finalized_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_effects_tenant", "effect_records", ["tenant_id"])
    op.create_index("ix_effects_tenant_step", "effect_records", ["tenant_id", "step_run_id"])
    op.create_index("ix_effects_grant", "effect_records", ["grant_id"])
    op.create_index("ix_effects_lease", "effect_records", ["lease_id"])
    op.create_index("ix_effects_status", "effect_records", ["status"])

    # ── tool_receipts ──
    op.create_table(
        "tool_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("effect_id", sa.String(36), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("args_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.Enum("SUCCEEDED", "FAILED", "UNKNOWN", name="receiptstatusdb"),
                   nullable=False),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("content_provenance", sa.String(50), nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("ended_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_receipts_tenant", "tool_receipts", ["tenant_id"])
    op.create_index("ix_receipts_effect", "tool_receipts", ["effect_id"])
    op.create_index("ix_receipts_status", "tool_receipts", ["status"])

    # ── dispatch_attempts ──
    op.create_table(
        "dispatch_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("effect_id", sa.String(36), nullable=False),
        sa.Column("attempt_ordinal", sa.Integer, nullable=False, server_default="1"),
        sa.Column("lease_id", sa.String(36), nullable=False),
        sa.Column("fencing_token", sa.Integer, nullable=False, server_default="0"),
        sa.Column("grant_digest", sa.String(64), nullable=False),
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("adapter_name", sa.String(100), nullable=False),
        sa.Column("dispatched_at", sa.DateTime, nullable=False),
        sa.Column("result_status", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_dispatch_tenant", "dispatch_attempts", ["tenant_id"])
    op.create_index("ix_dispatch_effect", "dispatch_attempts", ["effect_id"])
    op.create_index("ix_dispatch_lease", "dispatch_attempts", ["lease_id"])


def downgrade() -> None:
    op.drop_table("dispatch_attempts")
    op.drop_table("tool_receipts")
    op.drop_table("effect_records")
    op.drop_table("leases")
    op.drop_table("capability_grants")
