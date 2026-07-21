"""Integration tests — full chain: PlannerService -> Plan -> PolicyEngine -> Token."""


import pytest

from packages.llm_gateway.provider_router import ProviderRouter
from packages.planner.planner_service import PlannerService
from packages.policy.capability_token import TokenIssuer
from packages.policy.policy_engine import PolicyEngine
from packages.policy.tool_registry import ToolRegistry


@pytest.fixture
def chain_components(monkeypatch):
    """Set up all components for the full planning -> policy chain."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    registry = ToolRegistry(config_path="configs/tools.yaml")
    router = ProviderRouter(config_path="configs/models.yaml")
    planner = PlannerService(router, registry)
    token_issuer = TokenIssuer("test-secret")
    policy = PolicyEngine(registry, token_issuer, config_path="configs/policy.yaml")
    return planner, policy


@pytest.mark.integration
class TestPlanningPolicyChain:
    @pytest.mark.asyncio
    async def test_full_planning_to_policy_chain(self, chain_components):
        planner, policy = chain_components

        # Plan
        plan = await planner.plan("Search for competitor pricing and generate report")
        assert len(plan.steps) >= 1

        # Policy check each step
        for step in plan.steps:
            result = policy.check(
                "task-1", f"step-{step.step_id}", step.tool_name, step.args
            )
            assert result.allowed, f"Step {step.tool_name} should be allowed: {result.reason}"
            assert result.token is not None

            # Verify token
            valid, reason = policy.token_issuer.verify(
                result.token,
                "task-1",
                f"step-{step.step_id}",
                step.tool_name,
                step.args,
            )
            assert valid, f"Token should be valid: {reason}"

    @pytest.mark.asyncio
    async def test_shell_run_in_plan_rejected_by_policy(self, chain_components):
        """shell.run is disabled in the tool registry, so the planner
        should never produce a plan with it. But if a step somehow contains
        shell.run, the policy engine must reject it."""
        planner, policy = chain_components

        # Generate a normal plan first
        plan = await planner.plan("Do some web research")

        # Manually construct a shell.run step to test policy rejection
        # (The planner won't produce this because shell.run is disabled)
        from packages.planner.plan_validator import PlanStep
        malicious_step = PlanStep(
            step_id=99,
            tool_name="shell.run",
            args={"command": "rm -rf /"},
            reasoning="evil",
        )

        result = policy.check("task-1", "step-99", malicious_step.tool_name, malicious_step.args)
        assert result.allowed is False
        assert result.token is None

    @pytest.mark.asyncio
    async def test_localhost_url_rejected_in_chain(self, chain_components):
        """If a plan step tries to open localhost, policy should reject it."""
        planner, policy = chain_components

        # Simulate a step with localhost URL (planner shouldn't produce this,
        # but policy is the safety net)
        result = policy.check(
            "task-1", "step-1", "browser.open", {"url": "http://localhost:8080/admin"}
        )
        assert result.allowed is False
        assert result.token is None

    @pytest.mark.asyncio
    async def test_private_network_url_rejected_in_chain(self, chain_components):
        """Private network URLs should be blocked by policy."""
        _, policy = chain_components

        result = policy.check(
            "task-1", "step-1", "browser.open", {"url": "http://192.168.1.1/secret"}
        )
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_plan_with_personal_tool_for_enterprise_rejected(self, chain_components):
        """Personal-only tools should be rejected when edition is enterprise."""
        _, policy = chain_components

        result = policy.check(
            "task-1", "step-1", "file.search",
            {"keyword": "confidential"},
            edition="enterprise",
        )
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_plan_with_forbidden_path_rejected(self, chain_components):
        """Steps targeting forbidden paths should be rejected."""
        _, policy = chain_components

        result = policy.check(
            "task-1", "step-1", "file.write_docx",
            {"output_path": "/etc/crontab", "title": "x", "paragraphs": []},
        )
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_full_chain_produces_valid_tokens(self, chain_components):
        """Every approved step should have a cryptographically valid token."""
        planner, policy = chain_components

        plan = await planner.plan("Create a summary report from web data")
        for step in plan.steps:
            result = policy.check(
                "integration-task", f"step-{step.step_id}", step.tool_name, step.args
            )
            if result.allowed:
                valid, reason = policy.token_issuer.verify(
                    result.token,
                    "integration-task",
                    f"step-{step.step_id}",
                    step.tool_name,
                    step.args,
                )
                assert valid, f"Token verification failed for {step.tool_name}: {reason}"
