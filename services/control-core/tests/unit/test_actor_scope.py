"""P1.1 ActorScope 测试（G S-05）。"""

from __future__ import annotations

import pytest

from packages.auth.actor_scope import (
    ActorScope,
    ActorScopeNotBound,
    bind_actor_scope,
    get_current_actor_scope,
    reset_actor_scope,
    try_get_current_actor_scope,
)


class TestActorScope:
    def test_unbound_raises(self) -> None:
        """未绑定就读 → fail-closed（不许静默用 default）。"""
        # ContextVar 在每个测试默认是 None（pytest 无 async context）
        # 但 ContextVar 会跨调用传播，所以先确认 try_ 版本返回 None 或 scope
        # 用 contextvars.copy_context 隔离
        import contextvars
        ctx = contextvars.copy_context()
        def _check() -> None:
            with pytest.raises(ActorScopeNotBound):
                get_current_actor_scope()
        ctx.run(_check)

    def test_try_unbound_returns_none(self) -> None:
        import contextvars
        ctx = contextvars.copy_context()
        def _check() -> None:
            assert try_get_current_actor_scope() is None
        ctx.run(_check)

    def test_bind_and_read(self) -> None:
        scope = ActorScope(tenant_id="tnt-A", principal_id="u-1", auth_method="oidc")
        token = bind_actor_scope(scope)
        try:
            got = get_current_actor_scope()
            assert got.tenant_id == "tnt-A"
            assert got.principal_id == "u-1"
        finally:
            reset_actor_scope(token)

    def test_reset_restores_previous(self) -> None:
        scope1 = ActorScope(tenant_id="t1", principal_id="u1")
        scope2 = ActorScope(tenant_id="t2", principal_id="u2")
        t1 = bind_actor_scope(scope1)
        t2 = bind_actor_scope(scope2)
        assert get_current_actor_scope().tenant_id == "t2"
        reset_actor_scope(t2)
        assert get_current_actor_scope().tenant_id == "t1"
        reset_actor_scope(t1)

    def test_frozen(self) -> None:
        """ActorScope 不可变（防运行时篡改身份）。"""
        scope = ActorScope(tenant_id="t", principal_id="u")
        with pytest.raises(Exception):
            scope.tenant_id = "forged"  # type: ignore[misc]

    def test_default_workspace(self) -> None:
        scope = ActorScope(tenant_id="t", principal_id="u")
        assert scope.workspace_id == "default"

    def test_roles_frozenset(self) -> None:
        scope = ActorScope(
            tenant_id="t", principal_id="u",
            roles=frozenset({"operator", "auditor"}),
        )
        assert "operator" in scope.roles
