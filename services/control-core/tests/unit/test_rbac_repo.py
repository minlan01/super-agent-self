"""Unit tests for RBAC repository — Role, Permission, Assignment CRUD."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.db.models import Base, Role, Permission, RolePermission, UserRoleAssignment, User, UserRole, AuthMethod
from packages.db.repositories.rbac_repo import RBACRepository


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


class TestRoleCRUD:
    def test_create_role(self, db):
        role = RBACRepository.create_role(db, name="test_role", description="Test role")
        assert role.id is not None
        assert role.name == "test_role"
        assert role.is_default is False
        assert role.is_system is False

    def test_get_role_by_id(self, db):
        created = RBACRepository.create_role(db, name="test_role")
        found = RBACRepository.get_role_by_id(db, created.id)
        assert found is not None
        assert found.name == "test_role"

    def test_get_role_by_name(self, db):
        RBACRepository.create_role(db, name="viewer")
        found = RBACRepository.get_role_by_name(db, "viewer")
        assert found is not None
        assert found.name == "viewer"

    def test_get_role_not_found(self, db):
        assert RBACRepository.get_role_by_id(db, "nonexistent") is None
        assert RBACRepository.get_role_by_name(db, "nonexistent") is None

    def test_list_roles(self, db):
        RBACRepository.create_role(db, name="role_a")
        RBACRepository.create_role(db, name="role_b")
        roles = RBACRepository.list_roles(db)
        assert len(roles) == 2
        assert roles[0].name == "role_a"  # alphabetical

    def test_update_role(self, db):
        role = RBACRepository.create_role(db, name="old_name")
        updated = RBACRepository.update_role(db, role.id, name="new_name", description="Updated")
        assert updated.name == "new_name"
        assert updated.description == "Updated"

    def test_update_role_not_found(self, db):
        assert RBACRepository.update_role(db, "nonexistent", name="x") is None

    def test_delete_role(self, db):
        role = RBACRepository.create_role(db, name="deletable")
        assert RBACRepository.delete_role(db, role.id) is True
        assert RBACRepository.get_role_by_id(db, role.id) is None

    def test_delete_system_role_fails(self, db):
        role = RBACRepository.create_role(db, name="admin", is_system=True)
        assert RBACRepository.delete_role(db, role.id) is False

    def test_delete_nonexistent_role(self, db):
        assert RBACRepository.delete_role(db, "nonexistent") is False


class TestPermissionCRUD:
    def test_create_permission(self, db):
        perm = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        assert perm.id is not None
        assert perm.resource == "tasks"
        assert perm.action == "read"

    def test_get_permission_by_resource_action(self, db):
        RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        found = RBACRepository.get_permission_by_resource_action(db, "tasks", "read")
        assert found is not None
        assert found.name == "tasks:read"

    def test_list_permissions(self, db):
        RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        RBACRepository.create_permission(db, name="memory:read", resource="memory", action="read")
        perms = RBACRepository.list_permissions(db)
        assert len(perms) == 2

    def test_list_permissions_filter_by_resource(self, db):
        RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        RBACRepository.create_permission(db, name="memory:read", resource="memory", action="read")
        perms = RBACRepository.list_permissions(db, resource="tasks")
        assert len(perms) == 1
        assert perms[0].resource == "tasks"

    def test_delete_permission(self, db):
        perm = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        assert RBACRepository.delete_permission(db, perm.id) is True


class TestRolePermissionAssignment:
    def test_assign_permission_to_role(self, db):
        role = RBACRepository.create_role(db, name="test_role")
        perm = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        rp = RBACRepository.assign_permission_to_role(db, role.id, perm.id)
        assert rp is not None

    def test_assign_duplicate_permission_idempotent(self, db):
        role = RBACRepository.create_role(db, name="test_role")
        perm = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        RBACRepository.assign_permission_to_role(db, role.id, perm.id)
        rp2 = RBACRepository.assign_permission_to_role(db, role.id, perm.id)
        assert rp2 is not None  # Returns existing

    def test_revoke_permission_from_role(self, db):
        role = RBACRepository.create_role(db, name="test_role")
        perm = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        RBACRepository.assign_permission_to_role(db, role.id, perm.id)
        assert RBACRepository.revoke_permission_from_role(db, role.id, perm.id) is True

    def test_get_role_permissions(self, db):
        role = RBACRepository.create_role(db, name="test_role")
        p1 = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        p2 = RBACRepository.create_permission(db, name="tasks:write", resource="tasks", action="write")
        RBACRepository.assign_permission_to_role(db, role.id, p1.id)
        RBACRepository.assign_permission_to_role(db, role.id, p2.id)
        perms = RBACRepository.get_role_permissions(db, role.id)
        assert len(perms) == 2

    def test_batch_assign_permissions(self, db):
        role = RBACRepository.create_role(db, name="test_role")
        p1 = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        p2 = RBACRepository.create_permission(db, name="tasks:write", resource="tasks", action="write")
        results = RBACRepository.batch_assign_permissions(db, role.id, [p1.id, p2.id])
        assert len(results) == 2


class TestUserRoleAssignment:
    @pytest.fixture
    def user_and_role(self, db):
        from packages.db.repositories.auth_repo import AuthRepository
        user = AuthRepository.create_user(db, username="testuser", password="pass123")
        role = RBACRepository.create_role(db, name="test_role")
        return user, role

    def test_assign_role_to_user(self, db, user_and_role):
        user, role = user_and_role
        assignment = RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
        assert assignment is not None
        assert assignment.user_id == user.id
        assert assignment.role_id == role.id

    def test_assign_duplicate_role_idempotent(self, db, user_and_role):
        user, role = user_and_role
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
        a2 = RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
        assert a2 is not None

    def test_revoke_role_from_user(self, db, user_and_role):
        user, role = user_and_role
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
        assert RBACRepository.revoke_role_from_user(db, user.id, role.id) is True

    def test_get_user_roles(self, db, user_and_role):
        user, role = user_and_role
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
        roles = RBACRepository.get_user_roles(db, user.id)
        assert len(roles) == 1
        assert roles[0].name == "test_role"

    def test_get_user_permissions(self, db, user_and_role):
        user, role = user_and_role
        perm = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        RBACRepository.assign_permission_to_role(db, role.id, perm.id)
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
        perms = RBACRepository.get_user_permissions(db, user.id)
        assert len(perms) == 1
        assert perms[0].resource == "tasks"

    def test_get_user_permission_strings(self, db, user_and_role):
        user, role = user_and_role
        perm = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        RBACRepository.assign_permission_to_role(db, role.id, perm.id)
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
        strings = RBACRepository.get_user_permission_strings(db, user.id)
        assert "tasks:read" in strings

    def test_has_permission(self, db, user_and_role):
        user, role = user_and_role
        perm = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        RBACRepository.assign_permission_to_role(db, role.id, perm.id)
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
        assert RBACRepository.has_permission(db, user.id, "tasks", "read") is True
        assert RBACRepository.has_permission(db, user.id, "tasks", "write") is False
        assert RBACRepository.has_permission(db, user.id, "memory", "read") is False

    def test_has_any_permission(self, db, user_and_role):
        user, role = user_and_role
        perm = RBACRepository.create_permission(db, name="tasks:read", resource="tasks", action="read")
        RBACRepository.assign_permission_to_role(db, role.id, perm.id)
        RBACRepository.assign_role_to_user(db, user_id=user.id, role_id=role.id)
        assert RBACRepository.has_any_permission(db, user.id, "tasks", ["read", "write"]) is True
        assert RBACRepository.has_any_permission(db, user.id, "tasks", ["write", "admin"]) is False


class TestDefaultRole:
    def test_get_default_role(self, db):
        RBACRepository.create_role(db, name="admin")
        RBACRepository.create_role(db, name="user", is_default=True)
        default = RBACRepository.get_default_role(db)
        assert default is not None
        assert default.name == "user"

    def test_no_default_role(self, db):
        RBACRepository.create_role(db, name="admin")
        assert RBACRepository.get_default_role(db) is None

    def test_assign_default_role(self, db):
        from packages.db.repositories.auth_repo import AuthRepository
        RBACRepository.create_role(db, name="user", is_default=True)
        user = AuthRepository.create_user(db, username="testuser", password="pass123")
        assignment = RBACRepository.assign_default_role(db, user.id)
        assert assignment is not None


class TestSeed:
    def test_seed_creates_roles_and_permissions(self, db):
        result = RBACRepository.seed_default_roles_and_permissions(db)
        assert "admin" in result
        assert "user" in result
        assert "operator" in result
        assert "viewer" in result
        roles = RBACRepository.list_roles(db)
        assert len(roles) >= 4

    def test_seed_is_idempotent(self, db):
        RBACRepository.seed_default_roles_and_permissions(db)
        RBACRepository.seed_default_roles_and_permissions(db)
        roles = RBACRepository.list_roles(db)
        names = [r.name for r in roles]
        assert names.count("admin") == 1

    def test_seed_admin_has_all_permissions(self, db):
        RBACRepository.seed_default_roles_and_permissions(db)
        admin_role = RBACRepository.get_role_by_name(db, "admin")
        perms = RBACRepository.get_role_permissions(db, admin_role.id)
        assert len(perms) >= 52  # Should have all permissions

    def test_seed_viewer_has_only_read(self, db):
        RBACRepository.seed_default_roles_and_permissions(db)
        viewer_role = RBACRepository.get_role_by_name(db, "viewer")
        perms = RBACRepository.get_role_permissions(db, viewer_role.id)
        for p in perms:
            assert ":read" in p.name, f"Viewer should only have read permissions, got {p.name}"
