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
    executor = ExecutorService(tool_runner, policy_engine, planner=planner)
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
