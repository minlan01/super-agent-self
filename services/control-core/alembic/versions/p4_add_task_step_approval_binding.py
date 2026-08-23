"""P4 bind task steps to gateway approval requests."""

from alembic import op
import sqlalchemy as sa


revision = "p4_task_step_approval"
down_revision = "p2_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL stores StepStatus as a native enum; SQLite/MySQL use the
    # regular column representation and need no enum alteration here.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE stepstatus ADD VALUE IF NOT EXISTS 'AWAITING_APPROVAL'")
    op.add_column(
        "task_steps",
        sa.Column("approval_request_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_task_steps_approval_request_id",
        "task_steps",
        ["approval_request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_task_steps_approval_request_id", table_name="task_steps")
    op.drop_column("task_steps", "approval_request_id")
