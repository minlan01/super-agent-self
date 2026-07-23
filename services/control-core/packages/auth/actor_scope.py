"""ActorScope — request-scoped identity carrier (P1.1, G S-05 fix).

Spec §2.3: ActorScope is mandatory on every write command; request bodies
never carry forgeable identity. This module binds the authenticated user's
identity into a ContextVar at request entry, so Repositories can enforce
tenant filtering without each route having to pass tenant_id explicitly.

Design:
- Runtime dataclass (not Pydantic) — hot path, no validation overhead.
- Field-aligned with packages.protocol.schemas.v1.ActorScope for easy mapping.
- ContextVar defaults to None; ``get_current_actor_scope()`` raises if unset
  (fail-closed — code that forgets to bind gets loud failure, not silent default).
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


_actor_scope_var: ContextVar["ActorScope | None"] = ContextVar(
    "zcode_actor_scope", default=None
)


@dataclass(frozen=True)
class ActorScope:
    """Runtime identity of the actor issuing the current request.

    Bound from auth context (JWT claims / local user), NEVER from request body.
    Repositories read this via get_current_actor_scope() to enforce tenant
    filtering (spec §2.3 + G I-01).
    """
    tenant_id: str
    principal_id: str
    workspace_id: str = "default"
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)
    auth_method: str = "local"
    device_id: str | None = None
    os_session_id: str | None = None
    # Free-form metadata for debugging; never used for authorization decisions.
    metadata: dict[str, Any] = field(default_factory=dict)


class ActorScopeNotBound(RuntimeError):
    """Raised when code reads ActorScope but no request has bound one.

    This is a fail-closed signal — it means a code path forgot to depend on
    get_current_actor_scope, or is running outside a request context.
    """


def bind_actor_scope(scope: ActorScope) -> Token:
    """Bind an ActorScope to the current ContextVar. Returns a token for reset()."""
    return _actor_scope_var.set(scope)


def reset_actor_scope(token: Token) -> None:
    """Reset the ContextVar to its previous value (use in finally blocks)."""
    _actor_scope_var.reset(token)


def get_current_actor_scope() -> ActorScope:
    """Read the current ActorScope. Raises ActorScopeNotBound if unset.

    Use this in Repositories / services that need tenant_id but don't want
    to clutter their signatures with a scope parameter on every call.
    """
    scope = _actor_scope_var.get()
    if scope is None:
        raise ActorScopeNotBound(
            "no ActorScope bound in this context — the calling route must "
            "depend on get_current_actor_scope or bind one explicitly"
        )
    return scope


def try_get_current_actor_scope() -> ActorScope | None:
    """Non-raising variant for code paths where scope is optional
    (e.g. background workers, CLI)."""
    return _actor_scope_var.get()


__all__ = [
    "ActorScope",
    "ActorScopeNotBound",
    "bind_actor_scope",
    "reset_actor_scope",
    "get_current_actor_scope",
    "try_get_current_actor_scope",
]
