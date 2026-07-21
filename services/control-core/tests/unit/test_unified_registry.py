"""Tests for UnifiedToolRegistry — decorator registration, YAML merge, backward compat."""

import os
import tempfile

import pytest
import yaml

from packages.executor.tools.base import ToolBase, ToolResult
from packages.policy.unified_registry import UnifiedToolRegistry

# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the singleton before each test."""
    UnifiedToolRegistry.reset_instance()
    yield
    UnifiedToolRegistry.reset_instance()


def _write_yaml(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


@pytest.fixture
def yaml_config():
    """Create a temporary tools.yaml with policy overrides."""
    config = {
        "tools": {
            "test.tool": {
                "category": "test",
                "risk_level": "high",
                "enabled": True,
                "params_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
            },
            "disabled.tool": {
                "category": "test",
                "risk_level": "low",
                "enabled": False,
            },
            "edition.tool": {
                "category": "test",
                "risk_level": "low",
                "enabled": True,
                "edition": ["personal"],
            },
            "placeholder.no_code": {
                "description": "A YAML-only placeholder",
                "category": "test",
                "risk_level": "critical",
                "enabled": False,
                "params_schema": {"type": "object", "properties": {}},
            },
        }
    }
    path = os.path.join(tempfile.gettempdir(), f"test_tools_{os.getpid()}.yaml")
    _write_yaml(path, config)
    yield path
    if os.path.exists(path):
        os.unlink(path)


# ── Tests ────────────────────────────────────────────────────────────────


class TestDecoratorRegistration:
    def test_decorator_registers_tool(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)

        @registry.register(category="test", risk_level="low", emoji="🔧")
        class _TestTool(ToolBase):
            name = "test.tool"
            description = "A test tool"

            async def execute(self, args, context):
                return ToolResult(success=True)

        assert registry.is_registered("test.tool")
        tool = registry.get_tool("test.tool")
        assert tool is not None
        assert tool.emoji == "🔧"
        assert tool.tool_cls is _TestTool

    def test_decorator_duplicate_name_raises(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)

        @registry.register(category="test", risk_level="low")
        class _Tool1(ToolBase):
            name = "dup.tool"
            description = "First"

            async def execute(self, args, context):
                return ToolResult(success=True)

        with pytest.raises(ValueError, match="already registered"):
            @registry.register(category="test", risk_level="low")
            class _Tool2(ToolBase):
                name = "dup.tool"
                description = "Second"

                async def execute(self, args, context):
                    return ToolResult(success=True)

    def test_decorator_no_name_raises(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)

        with pytest.raises(ValueError, match="must have a 'name'"):
            @registry.register(category="test")
            class _NoName(ToolBase):
                description = "No name"

                async def execute(self, args, context):
                    return ToolResult(success=True)


class TestYAMLPolicyMerge:
    def test_yaml_risk_level_overrides_decorator(self, yaml_config):
        """YAML risk_level=high should override decorator risk_level=low."""
        registry = UnifiedToolRegistry(config_path=yaml_config)

        @registry.register(category="test", risk_level="low")
        class _TestTool(ToolBase):
            name = "test.tool"
            description = "A test tool"

            async def execute(self, args, context):
                return ToolResult(success=True)

        tool = registry.get_tool("test.tool")
        assert tool.risk_level == "high"  # YAML overrides

    def test_yaml_enabled_false_disables_tool(self, yaml_config):
        """YAML enabled=false should take precedence."""
        registry = UnifiedToolRegistry(config_path=yaml_config)

        @registry.register(category="test", risk_level="low")
        class _DisabledTool(ToolBase):
            name = "disabled.tool"
            description = "Should be disabled"

            async def execute(self, args, context):
                return ToolResult(success=True)

        tool = registry.get_tool("disabled.tool")
        assert tool.enabled is False

    def test_yaml_edition_overrides(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)

        @registry.register(category="test", risk_level="low")
        class _EditionTool(ToolBase):
            name = "edition.tool"
            description = "Edition restricted"

            async def execute(self, args, context):
                return ToolResult(success=True)

        tool = registry.get_tool("edition.tool")
        assert tool.edition == ["personal"]


class TestYAMLPlaceholders:
    def test_finalize_registers_yaml_only_entries(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)
        registry.finalize()

        tool = registry.get_tool("placeholder.no_code")
        assert tool is not None
        assert tool.tool_cls is None
        assert tool.enabled is False
        assert tool.risk_level == "critical"

    def test_placeholder_not_in_instances(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)
        registry.finalize()

        instance = registry.get_tool_instance("placeholder.no_code")
        assert instance is None


class TestQueryAPI:
    def test_get_tool_instance_returns_singleton(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)

        @registry.register(category="test", risk_level="low")
        class _InstTool(ToolBase):
            name = "test.tool"
            description = "Instance test"

            async def execute(self, args, context):
                return ToolResult(success=True)

        inst1 = registry.get_tool_instance("test.tool")
        inst2 = registry.get_tool_instance("test.tool")
        assert inst1 is inst2

    def test_is_available_for_edition(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)

        @registry.register(category="test", risk_level="low")
        class _EdTool(ToolBase):
            name = "edition.tool"
            description = "Edition"

            async def execute(self, args, context):
                return ToolResult(success=True)

        assert registry.is_available_for_edition("edition.tool", "personal") is True
        assert registry.is_available_for_edition("edition.tool", "enterprise") is False

    def test_get_tools_summary_format(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)

        @registry.register(category="test", risk_level="low")
        class _SumTool(ToolBase):
            name = "test.tool"
            description = "Summary test"

            async def execute(self, args, context):
                return ToolResult(success=True)

        summary = registry.get_tools_summary()
        assert isinstance(summary, list)
        if summary:
            item = summary[0]
            assert "name" in item
            assert "description" in item
            assert "category" in item
            assert "params" in item
            assert "required_params" in item

    def test_list_tools_filters_disabled(self, yaml_config):
        registry = UnifiedToolRegistry(config_path=yaml_config)

        @registry.register(category="test", risk_level="low")
        class _EnabledTool(ToolBase):
            name = "test.tool"

            async def execute(self, args, context):
                return ToolResult(success=True)

        @registry.register(category="test", risk_level="low")
        class _DisabledTool(ToolBase):
            name = "disabled.tool"

            async def execute(self, args, context):
                return ToolResult(success=True)

        tools = registry.list_tools(enabled_only=True)
        names = [t.name for t in tools]
        assert "test.tool" in names
        assert "disabled.tool" not in names


class TestSingleton:
    def test_get_instance_returns_same(self):
        a = UnifiedToolRegistry.get_instance()
        b = UnifiedToolRegistry.get_instance()
        assert a is b

    def test_reset_creates_new(self):
        a = UnifiedToolRegistry.get_instance()
        UnifiedToolRegistry.reset_instance()
        b = UnifiedToolRegistry.get_instance()
        assert a is not b
