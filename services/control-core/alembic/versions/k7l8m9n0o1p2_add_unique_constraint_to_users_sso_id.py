"""Add unique constraint to users.sso_id

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-06-05
"""

from alembic import op
from sqlalchemy import inspect

revision = "k7l8m9n0o1p2"
down_revision = "j6k7l8m9n0o1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing non-unique index if it exists
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if "ix_users_sso_id" in existing_indexes:
        op.drop_index("ix_users_sso_id", table_name="users")
    # Create with unique constraint
    op.create_index("ix_users_sso_id", "users", ["sso_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_sso_id", table_name="users")
    op.create_index("ix_users_sso_id", "users", ["sso_id"], unique=False)
