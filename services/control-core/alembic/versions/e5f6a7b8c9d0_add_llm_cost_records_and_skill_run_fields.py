"""add llm_cost_records and skill_run fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-19 18:00:00.000000

Adds:
- llm_cost_records table (24) for persistent LLM cost tracking
- execution_time and estimated_cost_usd columns on skill_runs

"""

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add columns to skill_runs
    op.add_column("skill_runs", sa.Column("execution_time", sa.Float(), nullable=True))
    op.add_column("skill_runs", sa.Column("estimated_cost_usd", sa.Float(), nullable=True))

    # 2. Create llm_cost_records table
    op.create_table(
        "llm_cost_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_llm_cost_records_provider", "llm_cost_records", ["provider"])
    op.create_index("ix_llm_cost_records_created_at", "llm_cost_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_cost_records_created_at", table_name="llm_cost_records")
    op.drop_index("ix_llm_cost_records_provider", table_name="llm_cost_records")
    op.drop_table("llm_cost_records")
    op.drop_column("skill_runs", "estimated_cost_usd")
    op.drop_column("skill_runs", "execution_time")
