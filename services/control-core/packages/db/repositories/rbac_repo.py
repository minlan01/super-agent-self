"""RBAC repository — Role, Permission, and UserRoleAssignment CRUD."""

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from packages.db.models import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRoleAssignment,
)


class RBACRepository:
    """Repository for RBAC operations — roles, permissions, assignments."""

    # ── Role CRUD ──────────────────────────────────────────────────────

    @staticmethod
    def create_role(db: Session, *, name: str, description: str | None = None,
                    is_default: bool = False, is_system: bool = False) -> Role:
        role = Role(name=name, description=description, is_default=is_default, is_system=is_system)
        db.add(role)
        db.flush()
        return role

    @staticmethod
    def get_role_by_id(db: Session, role_id: str) -> Role | None:
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions).selectinload(RolePermission.permission))
            .where(Role.id == role_id)
        )
        return db.scalar(stmt)

    @staticmethod
    def get_role_by_name(db: Session, name: str) -> Role | None:
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions).selectinload(RolePermission.permission))
            .where(Role.name == name)
        )
        return db.scalar(stmt)

    @staticmethod
    def list_roles(db: Session) -> list[Role]:
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions).selectinload(RolePermission.permission))
            .order_by(Role.name)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def update_role(db: Session, role_id: str, **kwargs) -> Role | None:
        role = db.get(Role, role_id)
        if not role:
            return None
        for key, value in kwargs.items():
            if hasattr(role, key) and value is not None:
                setattr(role, key, value)
        db.flush()
        return role

    @staticmethod
    def delete_role(db: Session, role_id: str) -> bool:
        role = db.get(Role, role_id)
        if not role or role.is_system:
            return False
        db.delete(role)
        db.flush()
        return True

    # ── Permission CRUD ────────────────────────────────────────────────

    @staticmethod
    def create_permission(db: Session, *, name: str, resource: str,
                          action: str, description: str | None = None) -> Permission:
        perm = Permission(name=name, resource=resource, action=action, description=description)
        db.add(perm)
        db.flush()
        return perm

    @staticmethod
    def get_permission_by_id(db: Session, permission_id: str) -> Permission | None:
        stmt = select(Permission).where(Permission.id == permission_id)
        return db.scalar(stmt)

    @staticmethod
    def get_permission_by_resource_action(db: Session, resource: str, action: str) -> Permission | None:
        stmt = select(Permission).where(
            and_(Permission.resource == resource, Permission.action == action)
        )
        return db.scalar(stmt)

    @staticmethod
    def list_permissions(db: Session, resource: str | None = None) -> list[Permission]:
        stmt = select(Permission)
        if resource:
            stmt = stmt.where(Permission.resource == resource)
        stmt = stmt.order_by(Permission.resource, Permission.action)
        return list(db.scalars(stmt).all())

    @staticmethod
    def delete_permission(db: Session, permission_id: str) -> bool:
        perm = db.get(Permission, permission_id)
        if not perm:
            return False
        db.delete(perm)
        db.flush()
        return True

    # ── Role-Permission Assignment ─────────────────────────────────────

    @staticmethod
    def assign_permission_to_role(db: Session, role_id: str, permission_id: str) -> RolePermission | None:
        stmt = select(RolePermission).where(
            and_(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id)
        )
        existing = db.scalar(stmt)
        if existing:
            return existing
        rp = RolePermission(role_id=role_id, permission_id=permission_id)
        db.add(rp)
        db.flush()
        return rp

    @staticmethod
    def revoke_permission_from_role(db: Session, role_id: str, permission_id: str) -> bool:
        stmt = select(RolePermission).where(
            and_(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id)
        )
        rp = db.scalar(stmt)
        if not rp:
            return False
        db.delete(rp)
        db.flush()
        return True

    @staticmethod
    def get_role_permissions(db: Session, role_id: str) -> list[Permission]:
        stmt = (
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def batch_assign_permissions(db: Session, role_id: str, permission_ids: list[str]) -> list[RolePermission]:
        if not permission_ids:
            return []
        # Single query to find all existing assignments
        stmt = select(RolePermission).where(
            RolePermission.role_id == role_id,
            RolePermission.permission_id.in_(permission_ids),
        )
        existing = {rp.permission_id: rp for rp in db.scalars(stmt).all()}
        # Bulk insert only new assignments
        new_ids = set(permission_ids) - set(existing.keys())
        new_rps = [RolePermission(role_id=role_id, permission_id=pid) for pid in new_ids]
        if new_rps:
            db.add_all(new_rps)
            db.flush()
        results = list(existing.values()) + new_rps
        return results

    # ── User-Role Assignment ───────────────────────────────────────────

    @staticmethod
    def assign_role_to_user(db: Session, *, user_id: str, role_id: str,
                            granted_by: str | None = None) -> UserRoleAssignment | None:
        stmt = select(UserRoleAssignment).where(
            and_(UserRoleAssignment.user_id == user_id, UserRoleAssignment.role_id == role_id)
        )
        existing = db.scalar(stmt)
        if existing:
            return existing
        assignment = UserRoleAssignment(user_id=user_id, role_id=role_id, granted_by=granted_by)
        db.add(assignment)
        db.flush()
        return assignment

    @staticmethod
    def get_roles_by_ids(db: Session, role_ids: list[str]) -> dict[str, Role]:
        """Bulk-fetch roles for existence validation.  Returns ``{id: Role}``.

        Does NOT eagerly load permissions — callers that need permissions
        should use :meth:`get_role_by_id`.
        """
        if not role_ids:
            return {}
        stmt = select(Role).where(Role.id.in_(role_ids))
        return {r.id: r for r in db.scalars(stmt).all()}

    @staticmethod
    def batch_assign_roles_to_user(
        db: Session,
        *,
        user_id: str,
        role_ids: list[str],
        granted_by: str | None = None,
    ) -> list[UserRoleAssignment]:
        """Assign multiple roles to a user idempotently.

        Loads existing assignments in one query, then bulk-inserts only the
        missing ones via ``add_all``.
        """
        if not role_ids:
            return []
        stmt = select(UserRoleAssignment).where(
            UserRoleAssignment.user_id == user_id,
            UserRoleAssignment.role_id.in_(role_ids),
        )
        existing = {a.role_id: a for a in db.scalars(stmt).all()}
        missing = [rid for rid in role_ids if rid not in existing]
        new_rows = [
            UserRoleAssignment(user_id=user_id, role_id=rid, granted_by=granted_by)
            for rid in missing
        ]
        if new_rows:
            db.add_all(new_rows)
            db.flush()
        return list(existing.values()) + new_rows

    @staticmethod
    def batch_revoke_roles_from_user(
        db: Session,
        user_id: str,
        role_ids: list[str],
    ) -> int:
        """Revoke multiple roles from a user in a single bulk DELETE.

        Returns the number of rows deleted.
        """
        if not role_ids:
            return 0
        from sqlalchemy import delete
        result = db.execute(
            delete(UserRoleAssignment).where(
                UserRoleAssignment.user_id == user_id,
                UserRoleAssignment.role_id.in_(role_ids),
            )
        )
        db.flush()
        return result.rowcount or 0

    @staticmethod
    def revoke_role_from_user(db: Session, user_id: str, role_id: str) -> bool:
        stmt = select(UserRoleAssignment).where(
            and_(UserRoleAssignment.user_id == user_id, UserRoleAssignment.role_id == role_id)
        )
        assignment = db.scalar(stmt)
        if not assignment:
            return False
        db.delete(assignment)
        db.flush()
        return True

    @staticmethod
    def get_user_roles(db: Session, user_id: str) -> list[Role]:
        stmt = (
            select(Role)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user_id)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_user_permissions(db: Session, user_id: str) -> list[Permission]:
        """Get all unique permissions for a user through their assigned roles."""
        stmt = (
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
            .where(UserRoleAssignment.user_id == user_id)
            .distinct()
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_user_permission_strings(db: Session, user_id: str) -> list[str]:
        """Get permission strings in 'resource:action' format for a user."""
        permissions = RBACRepository.get_user_permissions(db, user_id)
        return [f"{p.resource}:{p.action}" for p in permissions]

    @staticmethod
    def has_permission(db: Session, user_id: str, resource: str, action: str) -> bool:
        """Check if a user has a specific permission."""
        stmt = (
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
            .where(
                and_(
                    UserRoleAssignment.user_id == user_id,
                    Permission.resource == resource,
                    Permission.action == action,
                )
            )
        )
        return db.scalar(stmt) is not None

    @staticmethod
    def has_any_permission(db: Session, user_id: str, resource: str, actions: list[str]) -> bool:
        """Check if a user has any of the specified actions for a resource."""
        stmt = (
            select(Permission)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == RolePermission.role_id)
            .where(
                and_(
                    UserRoleAssignment.user_id == user_id,
                    Permission.resource == resource,
                    Permission.action.in_(actions),
                )
            )
        )
        return db.scalar(stmt) is not None

    # ── Default Role ───────────────────────────────────────────────────

    @staticmethod
    def get_default_role(db: Session) -> Role | None:
        stmt = select(Role).where(Role.is_default == True)  # noqa: E712
        return db.scalar(stmt)

    @staticmethod
    def assign_default_role(db: Session, user_id: str, granted_by: str | None = None) -> UserRoleAssignment | None:
        default_role = RBACRepository.get_default_role(db)
        if not default_role:
            return None
        return RBACRepository.assign_role_to_user(db, user_id=user_id, role_id=default_role.id, granted_by=granted_by)

    # ── Bulk Operations ────────────────────────────────────────────────

    @staticmethod
    def seed_default_roles_and_permissions(db: Session) -> dict[str, list[str]]:
        """Seed default roles and permissions. Returns {role_name: [permission_names]}.

        Idempotent — skips existing roles and permissions.
        """
        # Define all permissions
        permission_defs = [
            # Tasks
            ("tasks:read", "tasks", "read", "View tasks"),
            ("tasks:write", "tasks", "write", "Create and edit tasks"),
            ("tasks:execute", "tasks", "execute", "Execute task plans"),
            ("tasks:admin", "tasks", "admin", "Full task management"),
            # Memory
            ("memory:read", "memory", "read", "View memories"),
            ("memory:write", "memory", "write", "Create and manage memories"),
            ("memory:admin", "memory", "admin", "Full memory management"),
            # Skills
            ("skills:read", "skills", "read", "View skills"),
            ("skills:write", "skills", "write", "Approve, disable, run skills"),
            ("skills:admin", "skills", "admin", "Full skill management"),
            # Audit
            ("audit:read", "audit", "read", "View audit logs"),
            ("audit:admin", "audit", "admin", "Full audit management"),
            # Approvals
            ("approvals:read", "approvals", "read", "View approvals"),
            ("approvals:write", "approvals", "write", "Resolve approvals"),
            ("approvals:admin", "approvals", "admin", "Full approval management"),
            # Users & Roles
            ("users:read", "users", "read", "View user profiles"),
            ("users:write", "users", "write", "Manage users"),
            ("users:admin", "users", "admin", "Full user management"),
            ("roles:read", "roles", "read", "View roles and permissions"),
            ("roles:write", "roles", "write", "Manage roles and permissions"),
            ("roles:admin", "roles", "admin", "Full RBAC management"),
            # System
            ("system:read", "system", "read", "View system info"),
            ("system:write", "system", "write", "Modify system config"),
            ("system:admin", "system", "admin", "Full system access"),
            # Analytics
            ("analytics:read", "analytics", "read", "View analytics"),
            # Export
            ("export:read", "export", "read", "Export data"),
            ("export:write", "export", "write", "Export with options"),
            # Chat
            ("chat:read", "chat", "read", "View conversations"),
            ("chat:write", "chat", "write", "Send chat messages"),
            # Notifications
            ("notifications:read", "notifications", "read", "View notifications"),
            ("notifications:write", "notifications", "write", "Manage notifications"),
            # Marketplace
            ("marketplace:read", "marketplace", "read", "Browse marketplace"),
            ("marketplace:write", "marketplace", "write", "Subscribe, rate skills"),
            ("marketplace:admin", "marketplace", "admin", "Manage marketplace"),
            # Cron
            ("cron:read", "cron", "read", "View scheduled jobs"),
            ("cron:write", "cron", "write", "Manage scheduled jobs"),
            ("cron:admin", "cron", "admin", "Full cron management"),
            # Templates
            ("templates:read", "templates", "read", "View templates"),
            ("templates:write", "templates", "write", "Manage templates"),
            ("templates:admin", "templates", "admin", "Full template management"),
            # Voice
            ("voice:read", "voice", "read", "Use voice recognition"),
            ("voice:write", "voice", "write", "Use voice synthesis"),
            # Search
            ("search:read", "search", "read", "Use web search"),
            # Files
            ("files:read", "files", "read", "Access workspace files"),
            # Health
            ("health:read", "health", "read", "View health status"),
            # Editions
            ("editions:read", "editions", "read", "View edition configs"),
            # Webhooks
            ("webhooks:read", "webhooks", "read", "View webhooks"),
            ("webhooks:write", "webhooks", "write", "Manage webhooks"),
            # Conversations
            ("conversations:read", "conversations", "read", "View conversations"),
            ("conversations:write", "conversations", "write", "Manage conversations"),
            # Messaging
            ("messaging:read", "messaging", "read", "View messaging channels"),
            ("messaging:write", "messaging", "write", "Send messages"),
            # Desktop
            ("desktop:read", "desktop", "read", "View desktop info and windows"),
            ("desktop:write", "desktop", "write", "File system and window operations"),
            ("desktop:admin", "desktop", "admin", "Full desktop management"),
            # Vision
            ("vision:read", "vision", "read", "OCR text extraction"),
            ("vision:write", "vision", "write", "Image analysis and understanding"),
            ("vision:admin", "vision", "admin", "Full vision management"),
            # Plugins
            ("plugins:read", "plugins", "read", "View plugins"),
            ("plugins:write", "plugins", "write", "Activate and manage plugins"),
            ("plugins:admin", "plugins", "admin", "Full plugin management"),
            # Agents
            ("agents:read", "agents", "read", "View agent status"),
            ("agents:write", "agents", "write", "Send messages and propose consensus"),
            ("agents:admin", "agents", "admin", "Full agent management"),
        ]

        created_permissions = {}
        for name, resource, action, desc in permission_defs:
            existing = RBACRepository.get_permission_by_resource_action(db, resource, action)
            if not existing:
                perm = RBACRepository.create_permission(db, name=name, resource=resource, action=action, description=desc)
                created_permissions[name] = perm
            else:
                created_permissions[name] = existing

        # Define roles and their permission patterns
        role_defs = {
            "admin": {
                "description": "Full system access",
                "is_default": False,
                "is_system": True,
                "permissions": [p for p in created_permissions.keys()],  # ALL permissions
            },
            "operator": {
                "description": "Can manage tasks and most resources",
                "is_default": False,
                "is_system": False,
                "permissions": [
                    p for p in created_permissions.keys()
                    if not any(exclude in p for exclude in [":admin", "system:write", "roles:write", "roles:admin", "users:admin"])
                ],
            },
            "viewer": {
                "description": "Read-only access to most resources",
                "is_default": False,
                "is_system": False,
                "permissions": [
                    p for p in created_permissions.keys()
                    if ":read" in p
                ],
            },
            "user": {
                "description": "Basic user — can create tasks, chat, use personal features",
                "is_default": True,
                "is_system": False,
                "permissions": [
                    "tasks:read", "tasks:write", "tasks:execute",
                    "memory:read",
                    "skills:read",
                    "audit:read",
                    "analytics:read",
                    "chat:read", "chat:write",
                    "notifications:read", "notifications:write",
                    "marketplace:read", "marketplace:write",
                    "cron:read", "cron:write",
                    "templates:read",
                    "voice:read", "voice:write",
                    "search:read",
                    "files:read",
                    "health:read",
                    "editions:read",
                    "conversations:read", "conversations:write",
                    "export:read",
                    "approvals:read",
                    "webhooks:read",
                    "messaging:read",
                    "desktop:read",
                    "vision:read",
                    "plugins:read",
                    "agents:read",
                ],
            },
        }

        result = {}
        for role_name, role_def in role_defs.items():
            role = RBACRepository.get_role_by_name(db, role_name)
            if not role:
                role = RBACRepository.create_role(
                    db, name=role_name, description=role_def["description"],
                    is_default=role_def["is_default"], is_system=role_def["is_system"],
                )

            # Assign permissions to role
            permission_ids = []
            for perm_name in role_def["permissions"]:
                if perm_name in created_permissions:
                    permission_ids.append(created_permissions[perm_name].id)
            RBACRepository.batch_assign_permissions(db, role.id, permission_ids)

            result[role_name] = role_def["permissions"]

        return result

    @staticmethod
    def get_user_assignments(db: Session, user_id: str) -> list[UserRoleAssignment]:
        stmt = (
            select(UserRoleAssignment)
            .options(joinedload(UserRoleAssignment.role))
            .where(UserRoleAssignment.user_id == user_id)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def list_all_assignments(db: Session, page: int = 1, page_size: int = 50) -> tuple[list[UserRoleAssignment], int]:
        """List all user-role assignments with pagination."""
        count_stmt = select(func.count()).select_from(UserRoleAssignment)
        total = db.scalar(count_stmt) or 0

        stmt = (
            select(UserRoleAssignment)
            .order_by(UserRoleAssignment.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(db.scalars(stmt).all()), total

    @staticmethod
    def get_users_with_role(db: Session, role_id: str) -> list[User]:
        stmt = (
            select(User)
            .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
            .where(UserRoleAssignment.role_id == role_id)
        )
        return list(db.scalars(stmt).all())
