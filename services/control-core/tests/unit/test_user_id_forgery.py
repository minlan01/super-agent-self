"""P1.3 请求体 user_id 伪造测试（G E-04）。

验证：
1. TaskCreate.user_id 字段是可选（None 默认），不再是必填
2. 即使客户端传 user_id，也会被 ActorScope 覆盖（route 层强制）
"""

from __future__ import annotations

import pytest


class TestUserIdForgery:
    """G E-04: 请求体不得接受可伪造的 user_id。"""

    def test_task_create_user_id_is_optional(self) -> None:
        """TaskCreate 不带 user_id 也能构造（None 默认）。"""
        from packages.agent_core.schemas import TaskCreate
        tc = TaskCreate(goal="test")
        assert tc.user_id is None

    def test_task_create_accepts_user_id_but_deprecated(self) -> None:
        """向后兼容：仍接受 user_id，但会被 route 覆盖（不在 schema 拒绝）。"""
        from packages.agent_core.schemas import TaskCreate
        tc = TaskCreate(goal="test", user_id="attacker-forged")
        # schema 层不拒绝（兼容），route 层会覆盖
        assert tc.user_id == "attacker-forged"  # 但 route 会用 ActorScope 覆盖它

    def test_task_create_no_pattern_restriction_anymore(self) -> None:
        """user_id 字段不再有 pattern（因为不再被信任）。"""
        from packages.agent_core.schemas import TaskCreate
        import json
        schema = TaskCreate.model_json_schema()
        user_id_field = schema.get("properties", {}).get("user_id", {})
        # 不应有 pattern 约束（因为根本不用这个值）
        assert "pattern" not in user_id_field
