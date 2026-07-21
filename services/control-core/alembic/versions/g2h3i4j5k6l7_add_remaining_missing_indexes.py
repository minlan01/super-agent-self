"""add remaining missing indexes

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-06-03 12:00:00.000000

Adds:
- tasks ix_tasks_user_id index
- memories ix_memories_edition index
- memories ix_memories_memory_type index
- task_templates ix_task_templates_edition index
- skill_subscriptions ix_skill_subscriptions_skill_id index
- llm_cost_records ix_llm_cost_records_model index

Note: ix_skill_ratings_skill_id already created in c3d4e5f6a7b8
"""

from alembic import op


revision = "g2h3i4j5k6l7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_memories_edition", "memories", ["edition"])
    op.create_index("ix_memories_memory_type", "memories", ["memory_type"])
    op.create_index("ix_task_templates_edition", "task_templates", ["edition"])
    op.create_index("ix_skill_subscriptions_skill_id", "skill_subscriptions", ["skill_id"])
    op.create_index("ix_llm_cost_records_model", "llm_cost_records", ["model"])


def downgrade() -> None:
    op.drop_index("ix_llm_cost_records_model", table_name="llm_cost_records")
    op.drop_index("ix_skill_subscriptions_skill_id", table_name="skill_subscriptions")
    op.drop_index("ix_task_templates_edition", table_name="task_templates")
    op.drop_index("ix_memories_memory_type", table_name="memories")
    op.drop_index("ix_memories_edition", table_name="memories")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
