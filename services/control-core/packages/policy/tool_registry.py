"""Tool Registry — loads and manages available tools from config."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    name: str
    description: str
    category: str
    risk_level: str  # "low" | "medium" | "high" | "critical"
    enabled: bool = True
    edition: list[str] | None = None  # None = all editions, ["personal"] = personal only
    params_schema: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self, config_path: str = "configs/tools.yaml"):
        self._tools: dict[str, ToolDefinition] = {}
        self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        """Load tool definitions from YAML config."""
        path = Path(config_path)
        if not path.exists():
            logger.warning("Tool config not found: %s", config_path)
            return

        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        tools = config.get("tools", {})
        for name, tool_def in tools.items():
            self._tools[name] = ToolDefinition(
                name=name,
                description=tool_def.get("description", ""),
                category=tool_def.get("category", "general"),
                risk_level=tool_def.get("risk_level", "low"),
                enabled=tool_def.get("enabled", True),
                edition=tool_def.get("edition"),
                params_schema=tool_def.get("params_schema", {}),
            )
        logger.info("Loaded %d tools from %s", len(self._tools), config_path)

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def is_registered(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def is_enabled(self, name: str) -> bool:
        """Check if a tool is enabled."""
        tool = self._tools.get(name)
        return tool is not None and tool.enabled

    def is_available_for_edition(self, name: str, edition: str) -> bool:
        """Check if a tool is available for the given edition."""
        tool = self._tools.get(name)
        if tool is None or not tool.enabled:
            return False
        if tool.edition is None:
            return True
        return edition in tool.edition

    def get_risk_level(self, name: str) -> str | None:
        """Get the risk level of a tool."""
        tool = self._tools.get(name)
        return tool.risk_level if tool else None

    def list_tools(self, edition: str | None = None, enabled_only: bool = True) -> list[ToolDefinition]:
        """List all tools, optionally filtered by edition and enabled status."""
        result = []
        for tool in self._tools.values():
            if enabled_only and not tool.enabled:
                continue
            if edition is not None and not self.is_available_for_edition(tool.name, edition):
                continue
            result.append(tool)
        return result

    def get_tools_summary(self, edition: str | None = None) -> list[dict[str, Any]]:
        """Get a summary of available tools for injection into prompts."""
        tools = self.list_tools(edition=edition, enabled_only=True)
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "params": t.params_schema.get("properties", {}),
                "required_params": t.params_schema.get("required", []),
            }
            for t in tools
        ]
