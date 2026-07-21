"""add_task_templates_and_dependencies

Revision ID: a1b2c3d4e5f6
Revises: 84cab4f1b67a
Create Date: 2026-05-13 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '84cab4f1b67a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('task_templates',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('goal_template', sa.Text(), nullable=False),
    sa.Column('edition', sa.Enum('ENTERPRISE', 'PERSONAL', name='edition'), nullable=False),
    sa.Column('is_builtin', sa.Boolean(), nullable=False),
    sa.Column('parameters', sa.JSON(), nullable=True),
    sa.Column('usage_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('task_dependencies',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('task_id', sa.String(length=36), nullable=False),
    sa.Column('depends_on_id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
    sa.ForeignKeyConstraint(['depends_on_id'], ['tasks.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'depends_on_id', name='uq_task_dep')
    )
    op.create_index('ix_task_deps_task_id', 'task_dependencies', ['task_id'], unique=False)
    op.create_index('ix_task_deps_depends_on_id', 'task_dependencies', ['depends_on_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_task_deps_depends_on_id', table_name='task_dependencies')
    op.drop_index('ix_task_deps_task_id', table_name='task_dependencies')
    op.drop_table('task_dependencies')
    op.drop_table('task_templates')
