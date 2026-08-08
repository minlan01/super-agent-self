"""FastAPI dependencies — shared across route modules."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import Depends, Header, Query, Request
from sqlalchemy.orm import Session

from packages.auth.rbac import get_rbac_service
from packages.config import get_settings
from packages.db.models import UserRole
from packages.db.session import get_db

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from packages.db.models import User

__all__ = [
    "get_db", "CommonQueryParams", "get_orchestrator", "get_provider_router",
    "get_current_user", "get_user_edition",
    "require_permission", "get_rbac_service",
    "get_current_actor_scope",
]


class CommonQueryParams:
    """Reusable pagination parameters."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    ) -> None:
        self.page = page
        self.page_size = page_size


_provider_router_instance: Any = None
_orchestrator_instance: Any = None


def get_provider_router():
    """Singleton ProviderRouter — reads config once."""
    global _provider_router_instance
    if _provider_router_instance is None:
        from packages.llm_gateway.provider_router import ProviderRouter
        _provider_router_instance = ProviderRouter()
    return _provider_router_instance


def get_orchestrator():
    """Singleton Orchestrator with all dependencies wired once."""
    global _orchestrator_instance
    if _orchestrator_instance is not None:
        return _orchestrator_instance

    import packages.agent_core.sub_agent  # noqa: F401

    import packages.executor.tools._auto_import  # noqa: F401
    from packages.agent_core.orchestrator import Orchestrator
    from packages.agent_core.sub_agent import set_sub_agent_runner
    from packages.execution.orchestrator import ExecutionOrchestrator
    from packages.executor.executor_service import ExecutorService
    from packages.executor.tool_runner import ToolRunner
    from packages.executor.tools.delegate_tool import SubAgentRunner
    from packages.planner.planner_service import PlannerService
    from packages.policy.capability_token import TokenIssuer
    from packages.policy.policy_engine import PolicyEngine
    from packages.policy.unified_registry import UnifiedToolRegistry

    registry = UnifiedToolRegistry.get_instance()
    registry.finalize()

    provider_router = get_provider_router()
    planner = PlannerService(provider_router, registry)
    secret_key = get_settings().security.secret_key
    token_issuer = TokenIssuer(secret_key=secret_key)
    tool_runner = ToolRunner(token_issuer, registry=registry)
    policy_engine = PolicyEngine(registry, token_issuer)

    # ── P3.0-4: Wire ExecutionOrchestrator for ToolGateway routing ──
    execution_orchestrator = ExecutionOrchestrator.from_defaults(
        policy_engine=policy_engine,
        tool_lookup=registry,
    )

    executor = ExecutorService(
        tool_runner=tool_runner,
        policy_engine=policy_engine,
        planner=planner,
        execution_orchestrator=execution_orchestrator,
    )
    _orchestrator_instance = Orchestrator(planner, executor)

    sub_agent_runner = SubAgentRunner(planner, executor)
    set_sub_agent_runner(sub_agent_runner)

    return _orchestrator_instance


# ── Auth dependency ───────────────────────────────────────────────────────


def _resolve_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
    request: Request = None,  # type: ignore[assignment]
) -> User | None:
    """Internal dependency that resolves the authenticated User.

    When ``REQUIRE_AUTH=false`` (the default), returns a default admin user
    so all existing endpoints remain backward-compatible without tokens.

    When ``REQUIRE_AUTH=true``, validates the Bearer token from the
    ``Authorization`` header or ``access_token`` httpOnly cookie and
    returns the real user from the database.
    """
    from packages.db.models import User

    settings = get_settings()

    if not settings.security.require_auth:
        # Return a lightweight stub user — NOT attached to any DB session.
        # Code paths should never call db.refresh() / db.add() on this object.
        return User(
            id="default-admin",
            username="admin",
            email=None,
            hashed_password="!",
            role=UserRole.ADMIN,
            is_active=True,
        )

    token: str | None = None

    if authorization:
        token = authorization
        if token.lower().startswith("bearer "):
            token = token[7:]
    elif request is not None:
        token = request.cookies.get("access_token")

    if not token:
        return None

    from packages.auth.auth_service import verify_token
    from packages.db.repositories.auth_repo import AuthRepository

    payload = verify_token(token)
    if payload is None:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    return AuthRepository.get_by_id(db, user_id)


# Re-export as the public name used by route modules
get_current_user = _resolve_current_user


# ── ActorScope binding (P1.1, G S-05) ────────────────────────────────────


async def get_current_actor_scope(
    user: User | None = Depends(_resolve_current_user),
    db: Session = Depends(get_db),
) -> "ActorScope":
    """Resolve the authenticated user into an ActorScope and bind it to the
    request ContextVar.

    This is the canonical way routes obtain identity. The returned ActorScope
    is also bound via ``bind_actor_scope`` so Repositories can read
    ``get_current_actor_scope()`` without explicit threading.

    Anti-forgery (spec §2.3): the ActorScope is derived from the JWT-validated
    User, NEVER from the request body. Routes that previously accepted a
    ``user_id`` field in their body must switch to ``Depends(get_current_actor_scope)``.
    """
    from packages.auth.actor_scope import ActorScope, bind_actor_scope

    # Determine identity. When auth is disabled (dev mode), use a default.
    if user is None:
        # Auth required but no valid token → 401
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Resolve roles/permissions via RBAC
    roles: frozenset[str] = frozenset()
    permissions: frozenset[str] = frozenset()
    try:
        from packages.auth.rbac import RBACService
        rbac = RBACService(db)
        role_names = rbac.get_user_roles(user.id)
        roles = frozenset(role_names)
        permissions = frozenset(
            rbac.get_role_permissions(r) for r in role_names
        ) if role_names else frozenset()
    except Exception:
        # RBAC not configured → at least carry the role from User.role
        roles = frozenset({str(user.role.value) if hasattr(user.role, "value") else str(user.role)})

    # tenant_id resolution: P1 uses "default" tenant for single-user personal Profile.
    # P3+ will introduce real multi-tenancy. This is the ONLY place tenant_id
    # is derived — never accept it from request body.
    tenant_id = getattr(user, "tenant_id", None) or "default"

    scope = ActorScope(
        tenant_id=tenant_id,
        principal_id=str(user.id),
        workspace_id=getattr(user, "workspace_id", None) or "default",
        roles=roles,
        permissions=permissions,
        auth_method=getattr(user, "auth_method", "local").value
        if hasattr(getattr(user, "auth_method", None), "value")
        else str(getattr(user, "auth_method", "local")),
    )
    bind_actor_scope(scope)
    return scope


# ── Edition context dependency ────────────────────────────────────────────


def get_user_edition(
    user: User | None = Depends(_resolve_current_user),
    db: Session = Depends(get_db),
    x_edition: str | None = Header(None, alias="X-Edition"),
) -> str:
    """Resolve the effective edition for the current request.

    Priority:
    1. ``X-Edition`` header (explicit per-request override)
    2. User's stored preference (if auth enabled and user has a profile)
    3. Global default from settings (``settings.edition``)

    Returns one of ``"personal"`` or ``"enterprise"``.
    """
    # 1. Explicit header override
    if x_edition in ("personal", "enterprise"):
        return x_edition

    # 2. User-level preference
    if user is not None and hasattr(user, "id") and user.id != "default-admin":
        try:
            from packages.db.repositories.edition_repo import EditionRepository

            profile = EditionRepository.get_active(db, user.id)
            if profile is not None:
                ed = profile.edition
                return ed.value if hasattr(ed, "value") else ed
        except Exception as e:
            logger.warning("Failed to retrieve edition profile for user %s: %s", user.id, e)

    # 3. Global default
    settings = get_settings()
    return getattr(settings, "edition", "enterprise")


# ── RBAC permission dependency ────────────────────────────────────────────


def require_permission(resource: str, action: str = "read"):
    """FastAPI dependency factory that checks RBAC permissions.

    Usage::

        @router.get("/tasks", dependencies=[Depends(require_permission("tasks", "read"))])

    When RBAC is disabled, all requests pass through.
    When auth is disabled (REQUIRE_AUTH=false), the default admin gets all permissions.
    """
    from fastapi import HTTPException

    async def _check_permission(
        user: User | None = Depends(_resolve_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        # If auth is disabled, return the synthetic admin (all perms)
        settings = get_settings()
        if not settings.security.require_auth:
            if user is None:
                raise HTTPException(status_code=401, detail="Authentication required")
            return user

        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled")

        rbac = get_rbac_service()

        # Legacy admin bypass: if user has UserRole.ADMIN and bypass is enabled, allow all
        if rbac.legacy_admin_bypass and user.role == UserRole.ADMIN:
            return user

        # Check RBAC permission
        if rbac.rbac_enabled:
            has_perm = rbac.check_permission(db, user.id, resource, action)
            if not has_perm:
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission denied: {resource}:{action}",
                )

        return user

    return _check_permission


def require_admin():
    """Shorthand for require_permission("system", "admin").

    Replaces the ad-hoc _require_admin functions in admin.py and marketplace.py.
    """
    return require_permission("system", "admin")
