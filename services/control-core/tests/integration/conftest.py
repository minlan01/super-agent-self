"""Integration test conftest — shared auth helper for all integration clients.

P1 hardened the API: ``require_auth`` now defaults to True, so every
integration test client must send a valid Bearer token.  This module
provides ``make_auth_header(db)`` which creates (or reuses) an integration
test user, binds the seeded ``admin`` role (RBAC), and returns the
Authorization header value.

Files with a local ``client`` fixture call this helper to attach the header.
"""

from __future__ import annotations


def make_auth_header(db, *, role: str = "admin", username: str | None = None) -> dict[str, str]:
    """Create/reuse an integration test user and return auth headers.

    Safe to call repeatedly: reuses the existing user when the username
    already exists (unique constraint).  ``role`` selects the seeded RBAC
    role to bind ("admin" | "viewer" | ...); non-admin users exercise the
    ownership-filtering paths.
    """
    from sqlalchemy import select

    from packages.auth.auth_service import create_access_token
    from packages.auth.rbac import get_rbac_service
    from packages.db.models import Role, UserRoleAssignment, UserRole
    from packages.db.repositories.auth_repo import AuthRepository
    from packages.db.repositories.rbac_repo import RBACRepository

    # Ensure default roles/permissions exist, then bind the requested role.
    rbac = get_rbac_service()
    rbac.seed_if_empty(db)
    role_row = db.scalar(select(Role).where(Role.name == role))
    if role_row is None:
        for candidate in (role.capitalize(), f"{role}s", "system"):
            role_row = db.scalar(select(Role).where(Role.name == candidate))
            if role_row is not None:
                break

    username = username or f"it-{role}"
    user = AuthRepository.get_by_username(db, username)
    if user is None:
        user = AuthRepository.create_user(
            db, username=username, password="integration-pass-123",
        )
        user.role = UserRole.ADMIN if role == "admin" else UserRole.USER
        db.flush()

    if role_row is not None:
        already = db.scalar(
            select(UserRoleAssignment).where(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.role_id == role_row.id,
            )
        )
        if already is None:
            RBACRepository.assign_role_to_user(
                db, user_id=user.id, role_id=role_row.id,
                granted_by=user.id,
            )
    db.commit()

    # Invalidate any cached permissions for this user so the new role
    # binding is visible to RBACService immediately.
    try:
        rbac.invalidate_user_cache(user.id)
    except Exception:
        pass

    token = create_access_token({"sub": user.id, "username": user.username})
    return {"Authorization": f"Bearer {token}"}
