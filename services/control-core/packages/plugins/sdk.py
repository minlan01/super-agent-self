"""Plugin SDK — base classes and interfaces for third-party plugins."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PluginHook(str, Enum):
    """Lifecycle hooks that plugins can subscribe to."""
    ON_LOAD = "on_load"
    ON_UNLOAD = "on_unload"
    ON_TASK_CREATE = "on_task_create"
    ON_TASK_COMPLETE = "on_task_complete"
    ON_TASK_FAIL = "on_task_fail"
    ON_PLAN_GENERATE = "on_plan_generate"
    ON_TOOL_EXECUTE = "on_tool_execute"
    ON_MEMORY_STORE = "on_memory_store"


class PluginStatus(str, Enum):
    DISABLED = "disabled"
    LOADED = "loaded"
    ACTIVE = "active"
    ERROR = "error"


@dataclass
class PluginManifest:
    """Plugin metadata — defined in plugin.json."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    hooks: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    entry_point: str = "main.py"
    min_platform_version: str = "3.0.0"


@dataclass
class PluginContext:
    """Runtime context provided to plugins."""
    plugin_id: str
    data_dir: Path
    config: dict[str, Any] = field(default_factory=dict)

    def read_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def write_data(self, filename: str, content: str) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = (self.data_dir / filename).resolve()
        if not path.is_relative_to(self.data_dir.resolve()):
            raise ValueError("Path traversal detected in plugin write_data")
        path.write_text(content, encoding="utf-8")
        return path

    def read_data(self, filename: str) -> str | None:
        path = self.data_dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None


class PluginBase:
    """Base class for all plugins. Subclass and implement hooks."""

    manifest: PluginManifest

    def __init__(self):
        self._hooks: dict[PluginHook, Callable] = {}
        self._status: PluginStatus = PluginStatus.DISABLED
        self._context: PluginContext | None = None

    def register_hook(self, hook: PluginHook, handler: Callable) -> None:
        """Register a handler for a lifecycle hook."""
        self._hooks[hook] = handler

    async def on_load(self, context: PluginContext) -> None:
        """Called when the plugin is loaded."""
        self._context = context
        self._status = PluginStatus.LOADED
        handler = self._hooks.get(PluginHook.ON_LOAD)
        if handler:
            await handler(context) if inspect.iscoroutinefunction(handler) else handler(context)

    async def on_unload(self) -> None:
        """Called when the plugin is unloaded."""
        handler = self._hooks.get(PluginHook.ON_UNLOAD)
        if handler:
            await handler() if inspect.iscoroutinefunction(handler) else handler()
        self._status = PluginStatus.DISABLED

    async def emit(self, hook: PluginHook, **kwargs: Any) -> Any | None:
        """Emit a hook event to the plugin."""
        handler = self._hooks.get(hook)
        if handler:
            if inspect.iscoroutinefunction(handler):
                return await handler(**kwargs)
            return handler(**kwargs)
        return None

    @property
    def status(self) -> PluginStatus:
        return self._status

    @property
    def context(self) -> PluginContext | None:
        return self._context
