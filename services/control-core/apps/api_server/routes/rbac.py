"""RBAC management API — roles, permissions, user assignments."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload, selectinload

from packages.agent_core.schemas import (
    ResponseBase,
    RoleCreate,
    RoleDetailResponse,
    RoleListResponse,
    RoleResponse,
    RoleUpdate,
    PermissionListResponse,
    PermissionResponse,
    UserRoleAssign,
    UserRoleRevoke,
    UserRolesResponse,
    UserDetailResponse,
    UserListResponse,
    UserPermissionsResponse,
)
from packages.auth.rbac import get_rbac_service
from packages.db.models import AuditEventType, Role, RolePermission, User
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.rbac_repo import RBACRepository
from packages.db.pagination import paginate
from packages.agent_core.schemas import AuditEventCreate
from apps.api_server.dependencies import get_db

from apps.api_server.dependencies import get_current_user, require_permission

router = APIRouter()


def _role_to_response(role) -> RoleResponse:
    """Convert a Role ORM object to RoleResponse, resolving permissions through join table."""
    perms = []
    for rp in role.permissions:
        p = rp.permission
        if p:
            perms.append(PermissionResponse(
                id=p.id, name=p.name, resource=p.resource,
                action=p.action, description=p.description,
                created_at=p.created_at, updated_at=p.updated_at,
            ))
    return RoleResponse(
        id=role.id, name=role.name, description=role.description,
        is_default=role.is_default, is_system=role.is_system,
        permissions=perms,
        created_at=role.created_at, updated_at=role.updated_at,
    )


# ── Roles ────────────────────────────────────────────────────────────────


@router.get("/roles", response_model=RoleListResponse, dependencies=[Depends(require_permission("roles", "read"))])
def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    from sqlalchemy import select
    query = select(Role).options(selectinload(Role.permissions).selectinload(RolePermission.permission)).order_by(Role.name)
    result = paginate(db, query, page=page, page_size=page_size)
    return RoleListResponse(data=[_role_to_response(r) for r in result.items], **result.to_dict())


@router.get("/roles/{role_id}", response_model=RoleDetailResponse, dependencies=[Depends(require_permission("roles", "read"))])
def get_role(role_id: str, db: Session = Depends(get_db)):
    role = RBACRepository.get_role_by_id(db, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return RoleDetailResponse(data=_role_to_response(role))


@router.post("/roles", response_model=RoleDetailResponse, dependencies=[Depends(require_permission("roles", "write"))])
def create_role(body: RoleCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if RBACRepository.get_role_by_name(db, body.name):
        raise HTTPException(status_code=409, detail="Role already exists")
    role = RBACRepository.create_role(db, name=body.name, description=body.description,
                                       is_default=body.is_default)
    if body.permission_ids:
        RBACRepository.batch_assign_permissions(db, role.id, body.permission_ids)
    db.flush()
    db.refresh(role)
    get_rbac_service().invalidate_all_cache()
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.ROLE_CREATED,
        actor=user.id if user else "system",
        detail={"role_id": role.id, "role_name": role.name},
    ))
    return RoleDetailResponse(data=_role_to_response(role))


@router.put("/roles/{role_id}", response_model=RoleDetailResponse, dependencies=[Depends(require_permission("roles", "write"))])
def update_role(role_id: str, body: RoleUpdate, db: Session = Depends(get_db)):
    role = RBACRepository.update_role(db, role_id, **body.model_dump(exclude_none=True))
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    db.flush()
    db.refresh(role)
    get_rbac_service().invalidate_all_cache()
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.ROLE_UPDATED,
        detail={"role_id": role_id, "updates": body.model_dump(exclude_none=True)},
    ))
    return RoleDetailResponse(data=_role_to_response(role))


@router.delete("/roles/{role_id}", response_model=ResponseBase, dependencies=[Depends(require_permission("roles", "admin"))])
def delete_role(role_id: str, db: Session = Depends(get_db)):
    if not RBACRepository.delete_role(db, role_id):
        raise HTTPException(status_code=404, detail="Role not found or is a system role")
    db.flush()
    get_rbac_service().invalidate_all_cache()
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.ROLE_DELETED,
        detail={"role_id": role_id},
    ))
    return ResponseBase(message="Role deleted")


# ── Permissions ──────────────────────────────────────────────────────────


@router.get("/permissions", response_model=PermissionListResponse, dependencies=[Depends(require_permission("roles", "read"))])
def list_permissions(resource: str | None = None, db: Session = Depends(get_db)):
    perms = RBACRepository.list_permissions(db, resource=resource)
    return PermissionListResponse(data=[PermissionResponse.model_validate(p) for p in perms])


@router.post("/permissions/{permission_id}/assign/{role_id}", response_model=ResponseBase, dependencies=[Depends(require_permission("roles", "write"))])
def assign_permission_to_role(role_id: str, permission_id: str, db: Session = Depends(get_db)):
    RBACRepository.assign_permission_to_role(db, role_id, permission_id)
    db.flush()
    get_rbac_service().invalidate_all_cache()
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.PERMISSION_GRANTED,
        detail={"role_id": role_id, "permission_id": permission_id},
    ))
    return ResponseBase(message="Permission assigned")


@router.delete("/permissions/{permission_id}/revoke/{role_id}", response_model=ResponseBase, dependencies=[Depends(require_permission("roles", "write"))])
def revoke_permission_from_role(role_id: str, permission_id: str, db: Session = Depends(get_db)):
    RBACRepository.revoke_permission_from_role(db, role_id, permission_id)
    db.flush()
    get_rbac_service().invalidate_all_cache()
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.PERMISSION_REVOKED,
        detail={"role_id": role_id, "permission_id": permission_id},
    ))
    return ResponseBase(message="Permission revoked")


# ── User-Role Assignments ───────────────────────────────────────────────


@router.post("/users/assign", response_model=ResponseBase, dependencies=[Depends(require_permission("users", "admin"))])
def assign_roles(body: UserRoleAssign, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Single SELECT to validate all role ids exist.
    roles_by_id = RBACRepository.get_roles_by_ids(db, body.role_ids)
    missing = [rid for rid in body.role_ids if rid not in roles_by_id]
    if missing:
        raise HTTPException(status_code=404, detail="One or more roles not found")
    # Bulk-insert missing assignments via add_all.
    RBACRepository.batch_assign_roles_to_user(
        db,
        user_id=body.user_id,
        role_ids=body.role_ids,
        granted_by=user.id if user else None,
    )
    get_rbac_service().invalidate_user_cache(body.user_id)
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.ROLE_ASSIGNED,
        actor=user.id if user else "system",
        detail={"user_id": body.user_id, "role_ids": body.role_ids},
    ))
    return ResponseBase(message=f"Assigned {len(body.role_ids)} role(s)")


@router.post("/users/revoke", response_model=ResponseBase, dependencies=[Depends(require_permission("users", "admin"))])
def revoke_roles(body: UserRoleRevoke, db: Session = Depends(get_db)):
    # Bulk DELETE in a single query.
    RBACRepository.batch_revoke_roles_from_user(db, body.user_id, body.role_ids)
    get_rbac_service().invalidate_user_cache(body.user_id)
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.ROLE_REVOKED,
        detail={"user_id": body.user_id, "role_ids": body.role_ids},
    ))
    return ResponseBase(message=f"Revoked {len(body.role_ids)} role(s)")


@router.get("/users/{user_id}/roles", response_model=UserRolesResponse, dependencies=[Depends(require_permission("roles", "read"))])
def get_user_roles(user_id: str, db: Session = Depends(get_db)):
    assignments = RBACRepository.get_user_assignments(db, user_id)
    results = []
    for a in assignments:
        results.append({
            "id": a.id,
            "user_id": a.user_id,
            "role_id": a.role_id,
            "role_name": a.role.name if a.role else "unknown",
            "granted_by": a.granted_by,
            "created_at": a.created_at,
        })
    return UserRolesResponse(data=results)


@router.get("/users/{user_id}/permissions", response_model=UserPermissionsResponse, dependencies=[Depends(require_permission("roles", "read"))])
def get_user_permissions(user_id: str, db: Session = Depends(get_db)):
    rbac = get_rbac_service()
    permissions = rbac.get_user_permissions(db, user_id)
    return UserPermissionsResponse(data=permissions)


# ── Seeding ──────────────────────────────────────────────────────────────


@router.post("/seed", response_model=ResponseBase, dependencies=[Depends(require_permission("system", "admin"))])
def seed_rbac(db: Session = Depends(get_db)):
    """Seed default roles and permissions (idempotent)."""
    from packages.db.repositories.rbac_repo import RBACRepository
    result = RBACRepository.seed_default_roles_and_permissions(db)
    db.flush()
    get_rbac_service().invalidate_all_cache()
    return ResponseBase(message=f"Seeded {len(result)} roles")


# ── Users list with roles ───────────────────────────────────────────────


@router.get("/users", response_model=UserListResponse, dependencies=[Depends(require_permission("users", "read"))])
def list_users_with_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    from packages.db.models import Permission, RolePermission, UserRoleAssignment

    # Paginated user query with eager role assignments
    query = select(User).options(joinedload(User.role_assignments)).order_by(User.username)
    result = paginate(db, query, page=page, page_size=page_size)
    users = result.items

    if not users:
        return UserListResponse(data=[], **result.to_dict())

    # Batch-fetch permissions for all users on this page (single query)
    user_ids = [u.id for u in users]
    perm_rows = db.execute(
        select(
            UserRoleAssignment.user_id,
            Permission.resource,
            Permission.action,
        )
        .join(RolePermission, RolePermission.role_id == UserRoleAssignment.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(UserRoleAssignment.user_id.in_(user_ids))
    ).all()

    # Group permissions by user_id
    user_perms: dict[str, list[str]] = {}
    for uid, resource, action in perm_rows:
        user_perms.setdefault(uid, []).append(f"{resource}:{action}")

    # Batch-fetch all roles once
    all_roles = RBACRepository.list_roles(db)
    role_map = {r.id: r for r in all_roles}

    results = []
    for u in users:
        user_roles = []
        for assignment in u.role_assignments:
            role = role_map.get(assignment.role_id)
            if role:
                user_roles.append(role)

        permissions = list(set(user_perms.get(u.id, [])))  # dedupe

        results.append(UserDetailResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            role=u.role.value if hasattr(u.role, "value") else str(u.role),
            is_active=u.is_active,
            created_at=u.created_at.isoformat() if hasattr(u.created_at, "isoformat") else str(u.created_at),
            auth_method=u.auth_method.value if hasattr(u, "auth_method") and hasattr(u.auth_method, "value") else "local",
            sso_provider=u.sso_provider if hasattr(u, "sso_provider") else None,
            roles=[_role_to_response(r) for r in user_roles],
            permissions=permissions,
        ))
    return UserListResponse(data=results, **result.to_dict())
