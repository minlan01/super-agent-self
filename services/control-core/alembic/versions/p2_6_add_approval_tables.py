"""P2.6 add approval_requests + approval_votes

Revision ID: p2_approval
Revises: p2_exec_contract
Create Date: 2026-07-24
"""
from alembic import op
import sqlalchemy as sa

revision = "p2_approval"
down_revision = "p2_exec_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("step_run_id", sa.String(36), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("normalized_args_hash", sa.String(64), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("resource_scope", sa.JSON, nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("security_context_digest", sa.String(64), nullable=False),
        sa.Column("requester_principal_id", sa.String(100), nullable=False),
        sa.Column("requester_workspace_id", sa.String(100), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "APPROVED", "REJECTED", "EXPIRED",
                                     "INVALIDATED", name="approvalrequeststatus"),
                   nullable=False, server_default="PENDING"),
        sa.Column("required_quorum", sa.Integer, nullable=False, server_default="1"),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("resolution_id", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_approval_req_tenant", "approval_requests", ["tenant_id"])
    op.create_index("ix_approval_req_tenant_step", "approval_requests", ["tenant_id", "step_run_id"])
    op.create_index("ix_approval_req_status", "approval_requests", ["status"])
    op.create_index("ix_approval_req_requester", "approval_requests", ["requester_principal_id"])

    op.create_table(
        "approval_votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("voter_principal_id", sa.String(100), nullable=False),
        sa.Column("decision", sa.Enum("APPROVE", "REJECT", name="votedecision"),
                   nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("voted_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("request_id", "voter_principal_id", name="uq_one_vote_per_voter"),
    )
    op.create_index("ix_approval_vote_tenant", "approval_votes", ["tenant_id"])
    op.create_index("ix_approval_vote_request", "approval_votes", ["request_id"])
    op.create_index("ix_approval_vote_voter", "approval_votes", ["voter_principal_id"])


def downgrade() -> None:
    op.drop_table("approval_votes")
    op.drop_table("approval_requests")
