"""Plugin Loader — discover, load, and manage plugins."""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from packages.plugins.sdk import (
    PluginBase,
    PluginContext,
    PluginManifest,
    PluginStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_PLUGIN_DIR = "plugins"


class PluginLoader:
    """Discover, load, and manage third-party plugins."""

    _instance: PluginLoader | None = None

    def __init__(self, plugin_dir: str | Path = DEFAULT_PLUGIN_DIR):
        self.plugin_dir = Path(plugin_dir)
        self._plugins: dict[str, PluginBase] = {}
        self._manifests: dict[str, PluginManifest] = {}
        self._errors: dict[str, str] = {}
        PluginLoader._instance = self

    @classmethod
    def get_instance(cls) -> PluginLoader | None:
        """Return the most recently created PluginLoader instance, if any."""
        return cls._instance

    def discover(self) -> list[str]:
        """Scan plugin directory for valid plugins. Returns list of plugin names."""
        discovered = []
        if not self.plugin_dir.exists():
            return discovered

        for item in sorted(self.plugin_dir.iterdir()):
            if not item.is_dir():
                continue
            manifest_path = item / "plugin.json"
            if manifest_path.exists():
                discovered.append(item.name)
        return discovered

    def load_plugin(self, name: str) -> bool:
        """Load a single plugin by name."""
        if not name or ".." in name or "/" in name or "\\" in name or name.startswith("."):
            self._errors[name] = "Invalid plugin name"
            logger.warning("Rejected plugin name with path traversal: %r", name)
            return False

        plugin_path = self.plugin_dir / name

        try:
            resolved = plugin_path.resolve()
            base = self.plugin_dir.resolve()
            if not resolved.is_relative_to(base):
                self._errors[name] = "Plugin path escapes plugin directory"
                logger.warning("Plugin path escapes directory: %r -> %s", name, resolved)
                return False
        except OSError:
            self._errors[name] = "Cannot resolve plugin path"
            return False

        manifest_path = plugin_path / "plugin.json"

        if not manifest_path.exists():
            self._errors[name] = "plugin.json not found"
            return False

        try:
            with open(manifest_path, encoding="utf-8") as f:
                data = json.load(f)

            manifest = PluginManifest(
                name=data.get("name", name),
                version=data.get("version", "0.1.0"),
                description=data.get("description", ""),
                author=data.get("author", ""),
                hooks=data.get("hooks", []),
                permissions=data.get("permissions", []),
                entry_point=data.get("entry_point", "main.py"),
                min_platform_version=data.get("min_platform_version", "3.0.0"),
            )
            self._manifests[name] = manifest

            # Load entry point
            entry_path = plugin_path / manifest.entry_point
            if not entry_path.exists():
                self._errors[name] = f"Entry point {manifest.entry_point} not found"
                return False

            # Import module dynamically
            module_name = f"plugin_{name}"
            spec = importlib.util.spec_from_file_location(module_name, str(entry_path))
            if spec is None or spec.loader is None:
                self._errors[name] = "Failed to create module spec"
                return False

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module

            _SAFE_BUILTINS = frozenset({
                "print", "len", "range", "str", "int", "float", "bool",
                "list", "dict", "set", "tuple", "isinstance", "hasattr",
                "None", "True", "False",
                "enumerate", "zip", "sorted", "min", "max",
                "abs", "round", "Exception", "ValueError",
                "TypeError", "RuntimeError", "KeyError", "IndexError",
                "__build_class__",
            })
            _src_builtins = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
            restricted_builtins = {
                k: v for k, v in _src_builtins.items() if k in _SAFE_BUILTINS
            }
            module.__dict__["__builtins__"] = restricted_builtins
            module.__dict__["PluginBase"] = PluginBase
            module.__dict__["__import__"] = None

            spec.loader.exec_module(module)

            # Find PluginBase subclass
            plugin_instance = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type)
                    and issubclass(attr, PluginBase)
                    and attr is not PluginBase):
                    plugin_instance = attr()
                    break

            if plugin_instance is None:
                self._errors[name] = "No PluginBase subclass found in entry point"
                return False

            plugin_instance.manifest = manifest
            self._plugins[name] = plugin_instance
            logger.info("Plugin '%s' v%s loaded", manifest.name, manifest.version)
            return True

        except Exception as e:
            self._errors[name] = str(e)
            logger.exception("Failed to load plugin '%s'", name)
            return False

    def load_all(self) -> dict[str, bool]:
        """Discover and load all plugins."""
        results = {}
        for name in self.discover():
            results[name] = self.load_plugin(name)
        return results

    async def activate(self, name: str, data_root: str = "./data") -> bool:
        """Activate a loaded plugin with context."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return False

        data_dir = Path(data_root) / "plugins" / name
        context = PluginContext(
            plugin_id=name,
            data_dir=data_dir,
        )
        await plugin.on_load(context)
        plugin._status = PluginStatus.ACTIVE
        return True

    async def deactivate(self, name: str) -> bool:
        """Deactivate a plugin."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return False
        await plugin.on_unload()
        return True

    def get_plugin(self, name: str) -> PluginBase | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all discovered plugins with status."""
        result = []
        for name, plugin in self._plugins.items():
            manifest = self._manifests.get(name)
            result.append({
                "name": name,
                "display_name": manifest.name if manifest else name,
                "version": manifest.version if manifest else "unknown",
                "description": manifest.description if manifest else "",
                "status": plugin.status.value,
                "hooks": list(plugin._hooks.keys()),
                "error": self._errors.get(name),
            })
        # Also list plugins that failed to load
        for name, error in self._errors.items():
            if name not in self._plugins:
                result.append({
                    "name": name,
                    "display_name": name,
                    "version": "unknown",
                    "description": "",
                    "status": "error",
                    "hooks": [],
                    "error": error,
                })
        return result

    async def emit(self, hook_name: str, **kwargs: Any) -> list[Any]:
        """Emit a hook to all active plugins."""
        from packages.plugins.sdk import PluginHook
        results = []
        for plugin in self._plugins.values():
            if plugin.status == PluginStatus.ACTIVE:
                try:
                    result = await plugin.emit(PluginHook(hook_name), **kwargs)
                    results.append(result)
                except Exception:
                    logger.exception("Plugin hook error")
        return results

    async def reload(self, name: str) -> bool:
        """Hot-reload a plugin by unloading and reloading."""
        if name in self._plugins:
            old_plugin = self._plugins.pop(name)
            # Call on_unload lifecycle hook for proper cleanup
            try:
                await old_plugin.on_unload()
            except Exception as e:
                logger.warning("Plugin %s on_unload error during reload: %s", name, e)
            # Remove old module from sys.modules to allow fresh import
            module_key = f"plugin_{name}"
            sys.modules.pop(module_key, None)
        self._errors.pop(name, None)
        return self.load_plugin(name)


# Singleton
_loader: PluginLoader | None = None
_loader_lock = threading.Lock()


def get_plugin_loader() -> PluginLoader:
    global _loader
    with _loader_lock:
        if _loader is None:
            _loader = PluginLoader()
    return _loader
