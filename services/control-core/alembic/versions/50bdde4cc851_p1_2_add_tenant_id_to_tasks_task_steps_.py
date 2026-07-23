"""p1_2 add tenant_id to tasks task_steps users

Revision ID: 50bdde4cc851
Revises: m1n2o3p4q5r6
Create Date: 2026-07-23 10:41:46.048028
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50bdde4cc851'
down_revision: Union[str, None] = 'm1n2o3p4q5r6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tenant_id to tasks, task_steps, users (P1.2 G I-01).

    All default to 'default' tenant — single-user personal Profile.
    P3+ introduces real multi-tenancy; the column + index are in place now
    so Repositories can enforce filtering from day one.
    """
    op.add_column("tasks", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"))
    op.add_column("task_steps", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"))
    op.add_column("users", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"))

    # Composite indexes for the most common filtered queries
    op.create_index("ix_tasks_tenant_status", "tasks", ["tenant_id", "status"])
    op.create_index("ix_tasks_tenant_created", "tasks", ["tenant_id", "created_at"])
    op.create_index("ix_task_steps_tenant", "task_steps", ["tenant_id"])
    op.create_index("ix_users_tenant", "users", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_users_tenant", table_name="users")
    op.drop_index("ix_task_steps_tenant", table_name="task_steps")
    op.drop_index("ix_tasks_tenant_created", table_name="tasks")
    op.drop_index("ix_tasks_tenant_status", table_name="tasks")
    op.drop_column("users", "tenant_id")
    op.drop_column("task_steps", "tenant_id")
    op.drop_column("tasks", "tenant_id")
