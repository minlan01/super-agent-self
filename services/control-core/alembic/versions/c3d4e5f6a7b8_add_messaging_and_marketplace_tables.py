"""add messaging and marketplace tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-18 12:00:00.000000

Adds 5 tables:
- messaging_channels (15)
- message_logs (16)
- skill_ratings (17)
- skill_subscriptions (18)
- skill_promotions (19)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 15. messaging_channels
    op.create_table(
        'messaging_channels',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=100), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('channel_id', sa.String(length=200), nullable=False),
        sa.Column('channel_name', sa.String(length=200), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'platform', 'channel_id', name='uq_messaging_channel'),
    )

    # 16. message_logs
    op.create_table(
        'message_logs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('channel_id', sa.String(length=36), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('platform', sa.String(length=20), nullable=False),
        sa.Column('sender_id', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('raw_payload', sa.JSON(), nullable=True),
        sa.Column('task_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['channel_id'], ['messaging_channels.id']),
    )
    op.create_index('ix_message_logs_channel_id', 'message_logs', ['channel_id'], unique=False)
    op.create_index('ix_message_logs_created_at', 'message_logs', ['created_at'], unique=False)

    # 17. skill_ratings
    op.create_table(
        'skill_ratings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=100), nullable=False),
        sa.Column('skill_id', sa.String(length=36), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('review', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['skill_id'], ['skills.id']),
        sa.UniqueConstraint('user_id', 'skill_id', name='uq_skill_rating'),
    )
    op.create_index('ix_skill_ratings_skill_id', 'skill_ratings', ['skill_id'], unique=False)

    # 18. skill_subscriptions
    op.create_table(
        'skill_subscriptions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=100), nullable=False),
        sa.Column('skill_id', sa.String(length=36), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['skill_id'], ['skills.id']),
        sa.UniqueConstraint('user_id', 'skill_id', name='uq_skill_subscription'),
    )

    # 19. skill_promotions
    op.create_table(
        'skill_promotions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('skill_id', sa.String(length=36), nullable=False),
        sa.Column('source_edition', sa.String(length=20), nullable=False),
        sa.Column('target_edition', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('reviewed_by', sa.String(length=100), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['skill_id'], ['skills.id']),
    )
    op.create_index('ix_skill_promotions_skill_id', 'skill_promotions', ['skill_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_skill_promotions_skill_id', table_name='skill_promotions')
    op.drop_table('skill_promotions')

    op.drop_table('skill_subscriptions')

    op.drop_index('ix_skill_ratings_skill_id', table_name='skill_ratings')
    op.drop_table('skill_ratings')

    op.drop_index('ix_message_logs_created_at', table_name='message_logs')
    op.drop_index('ix_message_logs_channel_id', table_name='message_logs')
    op.drop_table('message_logs')

    op.drop_table('messaging_channels')
