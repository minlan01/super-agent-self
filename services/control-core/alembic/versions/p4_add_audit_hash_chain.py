"""P4 audit hash chain columns

Revision ID: p4_audit_chain
Revises: p4_task_step_approval
Create Date: 2026-08-22

Adds prev_entry_hash / entry_hash to audit_events. Existing rows keep
NULL (pre-chain history); the verifier anchors at the first hashed row.
"""
from alembic import op
import sqlalchemy as sa

revision = "p4_audit_chain"
down_revision = "p4_task_step_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("prev_entry_hash", sa.String(64), nullable=True))
    op.add_column("audit_events", sa.Column("entry_hash", sa.String(64), nullable=True))
    op.create_index("ix_audit_events_entry_hash", "audit_events", ["entry_hash"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_entry_hash", table_name="audit_events")
    op.drop_column("audit_events", "entry_hash")
    op.drop_column("audit_events", "prev_entry_hash")
