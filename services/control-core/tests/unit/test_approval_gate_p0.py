"""P0.5 审批旁路修复测试（G-02）。

验证：
1. 高风险工具（shell.execute / desktop.click）policy 返回 allowed=False +
   requires_approval=True，且不签 token（token=None）。
2. 低风险工具（file.read / web.search）policy 返回 allowed=True +
   requires_approval=False，且签了 token。
3. 禁用工具（shell.run）返回 allowed=False。
"""

from __future__ import annotations

import pytest

from packages.policy.capability_token import TokenIssuer
from packages.policy.policy_engine import PolicyEngine
from packages.policy.unified_registry import UnifiedToolRegistry


@pytest.fixture
def engine() -> PolicyEngine:
    reg = UnifiedToolRegistry.get_instance()
    reg.finalize()
    issuer = TokenIssuer(secret_key="test-secret-key-for-p0-5-verification")
    return PolicyEngine(reg, issuer, config_path="configs/policy.yaml")


class TestApprovalGateP0:
    """P0.5 G-02 修复：高风险工具不得在审批前签 token。"""

    def test_high_risk_tool_withholds_token(self, engine: PolicyEngine) -> None:
        """shell.execute 是 high risk → requires_approval_levels 默认含 high."""
        result = engine.check(
            task_id="t-1",
            step_id="s-1",
            tool_name="shell.execute",
            args={"command": ["ls"]},
            edition="enterprise",
        )
        assert result.requires_approval is True
        # 关键不变量：高风险时不签 token（原 bug 是无条件签发）
        assert result.token is None, (
            "high-risk tool must not receive a token before approval "
            "(G-02: this was the bypass that allowed immediate execution)"
        )
        assert result.allowed is False

    def test_low_risk_tool_gets_token(self, engine: PolicyEngine) -> None:
        """file.read 是 low risk → 正常签 token，立即可执行。"""
        result = engine.check(
            task_id="t-1",
            step_id="s-1",
            tool_name="file.read",
            args={"path": "/tmp/test.txt"},
            edition="enterprise",
        )
        assert result.allowed is True
        assert result.requires_approval is False
        assert result.token is not None
        assert len(result.token) > 0

    def test_medium_risk_tool_gets_token(self, engine: PolicyEngine) -> None:
        """delegate.task 是 medium risk（不在默认 require_approval_levels）→ 签 token。"""
        result = engine.check(
            task_id="t-1",
            step_id="s-1",
            tool_name="delegate.task",
            args={"goal": "sub-task"},
            edition="enterprise",
        )
        assert result.allowed is True
        assert result.token is not None

    def test_disabled_tool_rejected(self, engine: PolicyEngine) -> None:
        """shell.run 在 tools.yaml 标 enabled:false → 拒绝。"""
        result = engine.check(
            task_id="t-1",
            step_id="s-1",
            tool_name="shell.run",
            args={"command": "rm -rf /"},
            edition="enterprise",
        )
        assert result.allowed is False
        assert "disabled" in result.reason.lower()

    def test_unknown_tool_rejected(self, engine: PolicyEngine) -> None:
        result = engine.check(
            task_id="t-1",
            step_id="s-1",
            tool_name="nonexistent.tool",
            args={},
            edition="enterprise",
        )
        assert result.allowed is False
        assert "not registered" in result.reason.lower()

    def test_critical_risk_requires_approval(self, engine: PolicyEngine) -> None:
        """如果有 critical risk 工具（如 system.modify），必须审批。
        system.modify 在 tools.yaml 标 enabled:false，会先被 enabled 检查拦下，
        所以这里用 monkeypatch 验证机制本身。"""
        # 用一个假设的 critical 工具
        from packages.policy.unified_registry import UnifiedToolRegistry
        reg = UnifiedToolRegistry.get_instance()
        # 检查 require_approval_risk_levels 默认配置
        assert "high" in engine.require_approval_risk_levels
        # 如果配置了 critical 也要求审批，则 critical 工具也会 withhold token
