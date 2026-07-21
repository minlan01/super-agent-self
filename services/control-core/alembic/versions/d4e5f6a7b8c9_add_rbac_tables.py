"""add rbac tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-19 12:00:00.000000

Adds 4 RBAC tables + SSO fields on users:
- roles (20)
- permissions (21)
- role_permissions (22)
- user_role_assignments (23)

Also adds SSO fields to users table:
- sso_id (String 255, nullable)
- sso_provider (String 50, nullable)
- auth_method (Enum 'local'/'sso', default 'local')
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add SSO fields to users table
    op.add_column('users', sa.Column('sso_id', sa.String(255), nullable=True))
    op.add_column('users', sa.Column('sso_provider', sa.String(50), nullable=True))
    op.add_column('users', sa.Column('auth_method', sa.String(20), server_default='local', nullable=False))

    # 20. roles
    op.create_table(
        'roles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('is_default', sa.Boolean, server_default='0', nullable=False),
        sa.Column('is_system', sa.Boolean, server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('name', name='uq_role_name'),
    )

    # 21. permissions
    op.create_table(
        'permissions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('resource', sa.String(100), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('resource', 'action', name='uq_permission_resource_action'),
    )

    # 22. role_permissions
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.String(36), sa.ForeignKey('roles.id'), primary_key=True),
        sa.Column('permission_id', sa.String(36), sa.ForeignKey('permissions.id'), primary_key=True),
    )

    # 23. user_role_assignments
    op.create_table(
        'user_role_assignments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('role_id', sa.String(36), sa.ForeignKey('roles.id'), nullable=False),
        sa.Column('granted_by', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
    )
    op.create_index('ix_user_role_assignments_user_id', 'user_role_assignments', ['user_id'])
    op.create_index('ix_user_role_assignments_role_id', 'user_role_assignments', ['role_id'])


def downgrade() -> None:
    op.drop_index('ix_user_role_assignments_role_id', table_name='user_role_assignments')
    op.drop_index('ix_user_role_assignments_user_id', table_name='user_role_assignments')
    op.drop_table('user_role_assignments')
    op.drop_table('role_permissions')
    op.drop_table('permissions')
    op.drop_table('roles')

    # Drop index on sso_id before dropping the column (required by SQLite)
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if "ix_users_sso_id" in existing_indexes:
        op.drop_index("ix_users_sso_id", table_name="users")

    op.drop_column('users', 'auth_method')
    op.drop_column('users', 'sso_provider')
    op.drop_column('users', 'sso_id')
