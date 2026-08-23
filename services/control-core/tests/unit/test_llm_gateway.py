"""Unit tests for LLM Gateway — dataclasses, MockProvider, ProviderRouter."""

import json

import pytest

from packages.llm_gateway.base import LLMMessage, LLMResponse
from packages.llm_gateway.mock_provider import MockProvider
from packages.llm_gateway.provider_router import ProviderRouter

# ── LLMMessage & LLMResponse dataclass tests ───────────────────────────────


@pytest.mark.unit
class TestLLMMessage:
    def test_create_with_role_and_content(self):
        msg = LLMMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"

    def test_roles(self):
        for role in ("system", "user", "assistant"):
            msg = LLMMessage(role=role, content="x")
            assert msg.role == role


@pytest.mark.unit
class TestLLMResponse:
    def test_defaults(self):
        resp = LLMResponse(content="ok")
        assert resp.content == "ok"
        assert resp.model == ""
        assert resp.provider == ""
        assert resp.usage == {}
        assert resp.raw is None

    def test_full_response(self):
        resp = LLMResponse(
            content="result",
            model="deepseek-chat",
            provider="deepseek",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            raw={"id": "abc"},
        )
        assert resp.model == "deepseek-chat"
        assert resp.usage["prompt_tokens"] == 10
        assert resp.raw["id"] == "abc"


# ── MockProvider tests ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestMockProvider:
    def _make_provider(self, **overrides):
        config = {"name": "mock", **overrides}
        return MockProvider(config)

    @pytest.mark.asyncio
    async def test_generate_returns_content(self):
        provider = self._make_provider()
        messages = [LLMMessage(role="user", content="do something")]
        resp = await provider.generate(messages)

        assert isinstance(resp, LLMResponse)
        assert "Mock" in resp.content
        assert "do something" in resp.content
        assert resp.model == "mock"
        assert resp.provider == "mock"

    @pytest.mark.asyncio
    async def test_generate_no_user_message(self):
        provider = self._make_provider()
        messages = [LLMMessage(role="system", content="you are helpful")]
        resp = await provider.generate(messages)

        assert "(no user message)" in resp.content

    @pytest.mark.asyncio
    async def test_generate_json_returns_parseable_json_with_steps(self):
        provider = self._make_provider()
        messages = [LLMMessage(role="user", content="plan this task")]
        resp = await provider.generate_json(messages)

        data = json.loads(resp.content)
        assert "steps" in data
        assert len(data["steps"]) >= 1
        # Each step should have required fields
        step = data["steps"][0]
        assert "step_id" in step
        assert "tool_name" in step
        assert "args" in step

    @pytest.mark.asyncio
    async def test_generate_json_custom_planning_responses(self):
        custom_plan = {
            "reasoning": "custom",
            "steps": [
                {
                    "step_id": 1,
                    "tool_name": "file.read",
                    "args": {"path": "test.txt"},
                    "reasoning": "read file",
                }
            ],
        }
        provider = self._make_provider(
            mock_config={"planning_responses": {"pricing": json.dumps(custom_plan)}}
        )
        messages = [LLMMessage(role="user", content="Get competitor pricing")]
        resp = await provider.generate_json(messages)

        data = json.loads(resp.content)
        assert data["reasoning"] == "custom"
        assert len(data["steps"]) == 1
        assert data["steps"][0]["tool_name"] == "file.read"

    @pytest.mark.asyncio
    async def test_generate_json_delete_goal_returns_approval_plan(self):
        provider = self._make_provider()
        resp = await provider.generate_json(
            [LLMMessage(role="user", content="file.delete approval smoke")]
        )
        data = json.loads(resp.content)
        assert [step["tool_name"] for step in data["steps"]] == [
            "file.write_markdown",
            "file.delete",
        ]

    @pytest.mark.asyncio
    async def test_generate_json_read_goal_returns_read_plan(self):
        provider = self._make_provider()
        resp = await provider.generate_json(
            [LLMMessage(role="user", content="file.read smoke")]
        )
        data = json.loads(resp.content)
        assert [step["tool_name"] for step in data["steps"]][-1] == "file.read"

    @pytest.mark.asyncio
    async def test_generate_json_keyword_no_match_falls_back_to_default(self):
        provider = self._make_provider(
            mock_config={"planning_responses": {"xyz": '{"steps": []}'}}
        )
        messages = [LLMMessage(role="user", content="unrelated task")]
        resp = await provider.generate_json(messages)

        data = json.loads(resp.content)
        # Should fall back to default plan (3 steps)
        assert len(data["steps"]) == 3

    @pytest.mark.asyncio
    async def test_generate_json_invalid_custom_response_falls_back(self):
        provider = self._make_provider(
            mock_config={"planning_responses": {"bad": "not json at all"}}
        )
        messages = [LLMMessage(role="user", content="bad request")]
        resp = await provider.generate_json(messages)

        # Should still return valid JSON (default plan)
        data = json.loads(resp.content)
        assert "steps" in data


# ── ProviderRouter tests ───────────────────────────────────────────────────


@pytest.mark.unit
class TestProviderRouter:
    def test_loads_config_and_has_mock(self):
        router = ProviderRouter(config_path="configs/models.yaml")
        assert "mock" in router.providers

    def test_get_provider_mock_returns_mock_provider(self):
        router = ProviderRouter(config_path="configs/models.yaml")
        provider = router.get_provider("mock")
        assert isinstance(provider, MockProvider)

    def test_get_provider_none_returns_default(self):
        router = ProviderRouter(config_path="configs/models.yaml")
        provider = router.get_provider(None)
        assert isinstance(provider, type(router.providers[router.default_provider]))

    def test_get_provider_nonexistent_raises(self):
        router = ProviderRouter(config_path="configs/models.yaml")
        with pytest.raises(ValueError, match="not found"):
            router.get_provider("nonexistent")

    def test_missing_config_file_falls_back_to_mock(self):
        router = ProviderRouter(config_path="configs/nonexistent.yaml")
        assert router.default_provider == "mock"
        assert "mock" in router.providers

    @pytest.mark.asyncio
    async def test_generate_delegates_to_mock_provider(self):
        router = ProviderRouter(config_path="configs/models.yaml")
        messages = [LLMMessage(role="user", content="test")]
        resp = await router.generate(messages, provider="mock")
        assert "Mock" in resp.content

    @pytest.mark.asyncio
    async def test_generate_json_delegates_to_mock_provider(self):
        router = ProviderRouter(config_path="configs/models.yaml")
        messages = [LLMMessage(role="user", content="plan")]
        resp = await router.generate_json(messages, provider="mock")
        data = json.loads(resp.content)
        assert "steps" in data
