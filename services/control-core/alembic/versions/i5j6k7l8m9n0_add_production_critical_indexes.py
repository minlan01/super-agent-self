"""add production-critical indexes

Revision ID: i5j6k7l8m9n0
Revises: h3i4j5k6l7m8
Create Date: 2026-06-03 14:00:00.000000

Adds:
- task_steps ix_task_steps_status index
- conversation_messages ix_conv_messages_created_at index

Note: ix_llm_cost_records_model already added in g2h3i4j5k6l7
"""

from alembic import op


revision = "i5j6k7l8m9n0"
down_revision = "h3i4j5k6l7m8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_task_steps_status", "task_steps", ["status"])
    op.create_index("ix_conv_messages_created_at", "conversation_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_conv_messages_created_at", table_name="conversation_messages")
    op.drop_index("ix_task_steps_status", table_name="task_steps")
