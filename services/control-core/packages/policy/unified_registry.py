"""Unified Tool Registry — decorator-based self-registration with YAML policy overlay.

Design:
  - Each tool uses ``@tool_registry.register(...)`` to self-register on import.
  - YAML (``configs/tools.yaml``) remains the source of truth for **policy**
    fields: ``risk_level``, ``enabled``, ``edition``, ``params_schema``.
  - The decorator / class attributes provide **defaults** and **code-level**
    metadata: ``description``, ``category``, ``emoji``, ``check_fn``.
  - Merge rule: YAML > decorator > class attribute (for policy fields).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class RegisteredTool:
    """Merged view of a tool's code metadata + policy metadata."""

    name: str
    description: str
    category: str
    risk_level: str  # "low" | "medium" | "high" | "critical"
    enabled: bool
    edition: list[str] | None  # None = all editions
    params_schema: dict[str, Any]
    emoji: str
    check_fn: Callable[[dict[str, Any]], tuple[bool, str]] | None
    tool_cls: type | None = None  # None for YAML-only placeholder entries


# ── Policy fields that YAML can override ─────────────────────────────────
_POLICY_FIELDS = {"risk_level", "enabled", "edition", "params_schema"}


class UnifiedToolRegistry:
    """Unified registry that merges decorator registrations with YAML policy.

    Usage::

        from packages.policy.unified_registry import tool_registry

        @tool_registry.register(category="browser", risk_level="low", emoji="🌐")
        class BrowserOpen(ToolBase):
            name = "browser.open"
            ...
    """

    _instance: UnifiedToolRegistry | None = None

    def __init__(self, config_path: str = "configs/tools.yaml") -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._instances: dict[str, Any] = {}  # lazy-instantiated ToolBase cache
        self._yaml_policy: dict[str, dict[str, Any]] = {}
        self._load_policy(config_path)

    # ── Singleton access ────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> UnifiedToolRegistry:
        """Return (or create) the global singleton registry."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton — for testing only."""
        cls._instance = None

    # ── YAML policy loading ─────────────────────────────────────────────

    def _load_policy(self, config_path: str) -> None:
        """Load policy metadata from YAML config (risk_level, enabled, edition, params_schema)."""
        path = Path(config_path)
        if not path.exists():
            logger.warning("Tool config not found: %s", config_path)
            return

        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        tools = config.get("tools", {})
        for name, tool_def in tools.items():
            self._yaml_policy[name] = {
                "risk_level": tool_def.get("risk_level", "low"),
                "enabled": tool_def.get("enabled", True),
                "edition": tool_def.get("edition"),
                "params_schema": tool_def.get("params_schema", {}),
                # Also store description/category from YAML for placeholder entries
                "description": tool_def.get("description", ""),
                "category": tool_def.get("category", "general"),
            }

        logger.info("Loaded policy for %d tools from %s", len(self._yaml_policy), config_path)

    # ── Decorator-based registration ────────────────────────────────────

    def register(self, **kwargs: Any) -> Callable[[type], type]:
        """Decorator factory — registers a ToolBase subclass.

        Kwargs are merged with YAML policy (YAML wins for policy fields).

        Example::

            @tool_registry.register(category="browser", risk_level="low")
            class BrowserOpen(ToolBase):
                name = "browser.open"
                ...
        """

        def decorator(cls: type) -> type:
            tool_name = kwargs.get("name") or getattr(cls, "name", "")
            if not tool_name:
                raise ValueError(f"Tool class {cls.__name__} must have a 'name' attribute or pass name= to @register()")

            if tool_name in self._tools:
                raise ValueError(f"Tool '{tool_name}' already registered")

            # Build merged metadata
            merged = self._merge_policy(tool_name, kwargs, cls)

            self._tools[tool_name] = RegisteredTool(
                name=tool_name,
                tool_cls=cls,
                **merged,
            )

            logger.debug("Registered tool: %s (category=%s, risk=%s)", tool_name, merged["category"], merged["risk_level"])
            return cls  # non-mutating

        return decorator

    def _merge_policy(
        self,
        name: str,
        decorator_kwargs: dict[str, Any],
        cls: type | None = None,
    ) -> dict[str, Any]:
        """Merge metadata: YAML > decorator > class attribute.

        For policy fields (risk_level, enabled, edition, params_schema),
        YAML values take precedence so operators can override without code deploy.
        For code fields (description, category, emoji, check_fn), only
        decorator / class attribute values are used.
        """
        # Start from class attributes
        class_defaults: dict[str, Any] = {}
        if cls is not None:
            class_defaults = {
                "description": getattr(cls, "description", ""),
                "category": getattr(cls, "category", ""),
                "risk_level": getattr(cls, "risk_level", "low"),
                "emoji": getattr(cls, "emoji", ""),
                "params_schema": getattr(cls, "params_schema", {}),
                "check_fn": getattr(cls, "check_fn", None),
            }

        # Decorator kwargs override class defaults
        merged: dict[str, Any] = {**class_defaults}
        for key in ("description", "category", "risk_level", "emoji", "params_schema", "check_fn", "enabled", "edition"):
            if key in decorator_kwargs:
                merged[key] = decorator_kwargs[key]

        # YAML policy overrides (only for policy fields)
        yaml_entry = self._yaml_policy.get(name, {})
        for policy_field in _POLICY_FIELDS:
            if policy_field in yaml_entry:
                # Use YAML value — but only if it's meaningfully different from default
                yaml_val = yaml_entry[policy_field]
                if policy_field == "params_schema":
                    # Always use YAML schema if it has content
                    if yaml_val:
                        merged[policy_field] = yaml_val
                elif policy_field == "enabled":
                    merged[policy_field] = yaml_val
                elif policy_field == "edition":
                    merged[policy_field] = yaml_val
                elif policy_field == "risk_level":
                    merged[policy_field] = yaml_val

        # Ensure enabled has a default
        merged.setdefault("enabled", True)
        merged.setdefault("edition", None)

        return merged

    # ── Register YAML-only placeholder entries (no code class) ──────────

    def _register_yaml_placeholders(self) -> None:
        """Register tools that exist in YAML but have no corresponding code class."""
        for name, policy in self._yaml_policy.items():
            if name not in self._tools:
                self._tools[name] = RegisteredTool(
                    name=name,
                    description=policy.get("description", ""),
                    category=policy.get("category", "general"),
                    risk_level=policy.get("risk_level", "low"),
                    enabled=policy.get("enabled", True),
                    edition=policy.get("edition"),
                    params_schema=policy.get("params_schema", {}),
                    emoji="",
                    check_fn=None,
                    tool_cls=None,  # no code class
                )
                logger.debug("Registered YAML placeholder: %s (enabled=%s)", name, policy.get("enabled", True))

    # ── Public query API (compatible with ToolRegistry) ─────────────────

    def get_tool(self, name: str) -> RegisteredTool | None:
        """Get a registered tool by name."""
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

    def list_tools(
        self,
        edition: str | None = None,
        enabled_only: bool = True,
    ) -> list[RegisteredTool]:
        """List all tools, optionally filtered by edition and enabled status."""
        result: list[RegisteredTool] = []
        for tool in self._tools.values():
            if enabled_only and not tool.enabled:
                continue
            if edition is not None and not self.is_available_for_edition(tool.name, edition):
                continue
            result.append(tool)
        return result

    def get_tools_summary(self, edition: str | None = None) -> list[dict[str, Any]]:
        """Get a summary of available tools for injection into prompts.

        Output format is identical to the old ``ToolRegistry.get_tools_summary``.
        """
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

    # ── Tool instance access ────────────────────────────────────────────

    def get_tool_instance(self, name: str, *, _skip_enabled_check: bool = False) -> Any | None:
        """Lazily instantiate and cache a ToolBase instance by name.

        Returns None if the tool is not registered, has no code class, or is
        disabled (enabled=False). The enabled check closes the G-08a gap where
        ``enabled`` was a declaration-only flag that did not prevent
        instantiation via SubAgentRunner / CLI / routes.

        ``_skip_enabled_check`` is reserved for ToolRunner's internal use (the
        policy engine has already verified enabled at that point); external
        callers must not pass it.
        """
        registered = self._tools.get(name)
        if registered is None or registered.tool_cls is None:
            return None

        if not _skip_enabled_check and not registered.enabled:
            return None

        if name not in self._instances:
            self._instances[name] = registered.tool_cls()

        return self._instances[name]

    # ── Finalize (call after all imports) ───────────────────────────────

    def finalize(self) -> None:
        """Register any YAML placeholders that have no code class.

        Call this after all tool modules have been imported.
        """
        self._register_yaml_placeholders()


# ── Module-level singleton for decorator access ──────────────────────────
# Tools import this and use @tool_registry.register(...)

tool_registry = UnifiedToolRegistry.get_instance()
