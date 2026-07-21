"""add skill benchmark fields to skill_runs

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-06-03 13:00:00.000000

Adds:
- skill_runs.with_skill_duration (Float, nullable)
- skill_runs.without_skill_duration (Float, nullable)
"""

from alembic import op
import sqlalchemy as sa


revision = "h3i4j5k6l7m8"
down_revision = "g2h3i4j5k6l7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skill_runs", sa.Column("with_skill_duration", sa.Float(), nullable=True))
    op.add_column("skill_runs", sa.Column("without_skill_duration", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("skill_runs", "without_skill_duration")
    op.drop_column("skill_runs", "with_skill_duration")
