"""Add task user_id+status composite index

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-06-05
"""

from alembic import op

revision = "j6k7l8m9n0o1"
down_revision = "i5j6k7l8m9n0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_tasks_user_id_status", "tasks", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_tasks_user_id_status", table_name="tasks")
