"""add missing indexes and user updated_at

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-05-23 12:00:00.000000

Adds:
- users.updated_at column
- memories ix_memories_dedup composite index
- memories ix_memories_source_task_id index
- conversations ix_conversations_user_id index
- tasks ix_tasks_created_at index
- llm_cost_records ix_llm_cost_provider_date composite index
"""

from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.create_index("ix_memories_dedup", "memories", ["content_hash", "user_id", "is_active"])
    op.create_index("ix_memories_source_task_id", "memories", ["source_task_id"])
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])
    op.create_index("ix_llm_cost_provider_date", "llm_cost_records", ["provider", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_cost_provider_date", table_name="llm_cost_records")
    op.drop_index("ix_tasks_created_at", table_name="tasks")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_index("ix_memories_source_task_id", table_name="memories")
    op.drop_index("ix_memories_dedup", table_name="memories")

    op.drop_column("users", "updated_at")
