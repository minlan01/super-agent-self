import os
os.environ["TESTING"] = "1"

import json
import pytest
from pathlib import Path
from packages.plugins.loader import PluginLoader

_PLUGIN_CODE = "class TestPlugin(PluginBase):\n    pass\n"


class TestPluginLoader:
    def test_discover_empty(self, tmp_path):
        loader = PluginLoader(plugin_dir=tmp_path)
        assert loader.discover() == []

    def test_discover_with_plugin(self, tmp_path):
        plugin_dir = tmp_path / "my_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(json.dumps({"name": "My Plugin", "version": "1.0"}))
        (plugin_dir / "main.py").write_text(_PLUGIN_CODE)
        loader = PluginLoader(plugin_dir=tmp_path)
        discovered = loader.discover()
        assert "my_plugin" in discovered

    def test_load_plugin(self, tmp_path):
        plugin_dir = tmp_path / "test_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(json.dumps({
            "name": "Test Plugin", "version": "0.1.0", "description": "A test",
        }))
        (plugin_dir / "main.py").write_text(_PLUGIN_CODE)
        loader = PluginLoader(plugin_dir=tmp_path)
        assert loader.load_plugin("test_plugin") is True
        assert loader.get_plugin("test_plugin") is not None

    def test_load_plugin_missing_manifest(self, tmp_path):
        plugin_dir = tmp_path / "broken"
        plugin_dir.mkdir()
        loader = PluginLoader(plugin_dir=tmp_path)
        assert loader.load_plugin("broken") is False

    def test_load_plugin_path_traversal_dotdot(self, tmp_path):
        loader = PluginLoader(plugin_dir=tmp_path)
        assert loader.load_plugin("../../etc/passwd") is False

    def test_load_plugin_path_traversal_slash(self, tmp_path):
        loader = PluginLoader(plugin_dir=tmp_path)
        assert loader.load_plugin("/etc/passwd") is False

    def test_load_plugin_path_traversal_backslash(self, tmp_path):
        loader = PluginLoader(plugin_dir=tmp_path)
        assert loader.load_plugin("..\\..\\windows\\system32") is False

    def test_load_plugin_path_traversal_dot(self, tmp_path):
        loader = PluginLoader(plugin_dir=tmp_path)
        assert loader.load_plugin(".hidden") is False

    def test_load_plugin_empty_name(self, tmp_path):
        loader = PluginLoader(plugin_dir=tmp_path)
        assert loader.load_plugin("") is False

    def test_load_plugin_missing_entry(self, tmp_path):
        plugin_dir = tmp_path / "no_entry"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(json.dumps({"name": "No Entry"}))
        loader = PluginLoader(plugin_dir=tmp_path)
        assert loader.load_plugin("no_entry") is False

    def test_list_plugins(self, tmp_path):
        plugin_dir = tmp_path / "listed"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(json.dumps({
            "name": "Listed Plugin", "version": "1.0",
        }))
        (plugin_dir / "main.py").write_text(_PLUGIN_CODE)
        loader = PluginLoader(plugin_dir=tmp_path)
        loader.load_plugin("listed")
        plugins = loader.list_plugins()
        assert len(plugins) >= 1
        assert plugins[0]["name"] == "listed"

    @pytest.mark.asyncio
    async def test_activate_and_deactivate(self, tmp_path):
        plugin_dir = tmp_path / "activatable"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(json.dumps({"name": "Activatable", "version": "1.0"}))
        (plugin_dir / "main.py").write_text(_PLUGIN_CODE)
        loader = PluginLoader(plugin_dir=tmp_path)
        loader.load_plugin("activatable")

        data_root = str(tmp_path / "data")
        assert await loader.activate("activatable", data_root=data_root) is True
        plugin = loader.get_plugin("activatable")
        assert plugin.status.value == "active"

        assert await loader.deactivate("activatable") is True

    @pytest.mark.asyncio
    async def test_reload(self, tmp_path):
        plugin_dir = tmp_path / "reloadable"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(json.dumps({"name": "Reloadable", "version": "1.0"}))
        (plugin_dir / "main.py").write_text(_PLUGIN_CODE)
        loader = PluginLoader(plugin_dir=tmp_path)
        loader.load_plugin("reloadable")
        assert await loader.reload("reloadable") is True
