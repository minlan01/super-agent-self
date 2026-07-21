"""Strawberry GraphQL schema definition."""

import strawberry
from strawberry.extensions import SchemaExtension
from strawberry.types import Info

from packages.graphql.resolvers import (
    get_audit_events,
    get_dashboard_stats,
    get_memories,
    get_skills,
    get_task,
    get_task_with_steps,
    get_tasks,
)

_MAX_DEPTH = 8


class _DepthLimitExtension(SchemaExtension):
    """Reject GraphQL queries that exceed the maximum allowed depth."""

    def on_request_start(self, *, execution_context):
        query = execution_context.graphql_document
        if query is None:
            return
        max_depth = 0
        def _walk(node, depth):
            nonlocal max_depth
            if hasattr(node, 'selection_set') and node.selection_set:
                for sel in node.selection_set.selections:
                    _walk(sel, depth + 1)
                max_depth = max(max_depth, depth + 1)
            elif hasattr(node, 'fields'):
                for field in node.fields:
                    _walk(field, depth + 1)
                max_depth = max(max_depth, depth + 1)
        for definition in query.definitions:
            _walk(definition, 0)
        if max_depth > _MAX_DEPTH:
            from graphql import GraphQLError
            raise GraphQLError(f"Query depth {max_depth} exceeds maximum allowed depth of {_MAX_DEPTH}")
from packages.graphql.types import (
    AuditEventType,
    DashboardStats,
    MemoryType,
    SkillType,
    TaskType,
    TaskWithSteps,
)


def _db_from_context(info: Info):
    """Extract the SQLAlchemy Session from Strawberry context, if available."""
    db = info.context.get("db") if isinstance(info.context, dict) else None
    return db or None


def _user_from_context(info: Info):
    """Extract the authenticated User from Strawberry context, if available."""
    user = info.context.get("user") if isinstance(info.context, dict) else None
    return user or None


def _require_permission(info: Info, resource: str, action: str = "read"):
    """Check RBAC permission for the current user; raise GraphQLError on denial.

    Mirrors the logic of ``require_permission`` from the REST dependencies so
    that GraphQL resolvers enforce the same access control.
    """
    from graphql import GraphQLError

    from packages.auth.rbac import get_rbac_service
    from packages.config import get_settings
    from packages.db.models import UserRole

    user = _user_from_context(info)
    settings = get_settings()

    # When auth is disabled the synthetic admin always passes
    if not settings.security.require_auth:
        if user is None:
            raise GraphQLError("Authentication required")
        return

    if user is None:
        raise GraphQLError("Authentication required")

    if not user.is_active:
        raise GraphQLError("Account is disabled")

    rbac = get_rbac_service()

    # Legacy admin bypass
    if rbac.legacy_admin_bypass and user.role == UserRole.ADMIN:
        return

    # Check RBAC permission
    if rbac.rbac_enabled:
        db = _db_from_context(info)
        has_perm = rbac.check_permission(db, user.id, resource, action)
        if not has_perm:
            raise GraphQLError(f"Permission denied: {resource}:{action}")


_MAX_PAGE_LIMIT = 100


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, _MAX_PAGE_LIMIT))


def _clamp_offset(offset: int) -> int:
    return max(0, offset)


@strawberry.type
class Query:
    @strawberry.field
    def tasks(
        self,
        info: Info,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[TaskType]:
        _require_permission(info, "tasks", "read")
        return get_tasks(_clamp_limit(limit), _clamp_offset(offset), status, db=_db_from_context(info))

    @strawberry.field
    def task(self, info: Info, task_id: str) -> TaskType | None:
        _require_permission(info, "tasks", "read")
        return get_task(task_id, db=_db_from_context(info))

    @strawberry.field
    def task_with_steps(self, info: Info, task_id: str) -> TaskWithSteps | None:
        _require_permission(info, "tasks", "read")
        return get_task_with_steps(task_id, db=_db_from_context(info))

    @strawberry.field
    def memories(
        self,
        info: Info,
        limit: int = 20,
        offset: int = 0,
        memory_type: str | None = None,
    ) -> list[MemoryType]:
        _require_permission(info, "memory", "read")
        return get_memories(_clamp_limit(limit), _clamp_offset(offset), memory_type, db=_db_from_context(info))

    @strawberry.field
    def skills(
        self,
        info: Info,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[SkillType]:
        _require_permission(info, "skills", "read")
        return get_skills(_clamp_limit(limit), _clamp_offset(offset), status, db=_db_from_context(info))

    @strawberry.field
    def audit_events(
        self,
        info: Info,
        limit: int = 20,
        offset: int = 0,
        task_id: str | None = None,
    ) -> list[AuditEventType]:
        _require_permission(info, "audit", "read")
        return get_audit_events(_clamp_limit(limit), _clamp_offset(offset), task_id, db=_db_from_context(info))

    @strawberry.field
    def dashboard_stats(self, info: Info) -> DashboardStats:
        _require_permission(info, "analytics", "read")
        return get_dashboard_stats(db=_db_from_context(info))


schema = strawberry.Schema(query=Query, extensions=[_DepthLimitExtension])
