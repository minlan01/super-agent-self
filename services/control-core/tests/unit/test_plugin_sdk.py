import os
os.environ["TESTING"] = "1"

import pytest
from pathlib import Path
from packages.plugins.sdk import (
    PluginBase, PluginContext, PluginManifest, PluginHook, PluginStatus,
)


class TestPluginManifest:
    def test_defaults(self):
        m = PluginManifest(name="test", version="1.0")
        assert m.name == "test"
        assert m.version == "1.0"
        assert m.hooks == []
        assert m.entry_point == "main.py"

    def test_custom_values(self):
        m = PluginManifest(
            name="demo", version="2.0", description="Demo plugin",
            author="test", hooks=["on_load"], permissions=["tasks:read"],
        )
        assert m.description == "Demo plugin"
        assert len(m.hooks) == 1


class TestPluginContext:
    def test_read_config(self, tmp_path):
        ctx = PluginContext(plugin_id="test", data_dir=tmp_path, config={"key": "value"})
        assert ctx.read_config("key") == "value"
        assert ctx.read_config("missing", "default") == "default"

    def test_write_and_read_data(self, tmp_path):
        ctx = PluginContext(plugin_id="test", data_dir=tmp_path)
        path = ctx.write_data("test.txt", "hello")
        assert path.exists()
        assert ctx.read_data("test.txt") == "hello"

    def test_read_nonexistent_data(self, tmp_path):
        ctx = PluginContext(plugin_id="test", data_dir=tmp_path)
        assert ctx.read_data("nonexistent.txt") is None


class TestPluginBase:
    def test_initial_status(self):
        plugin = PluginBase()
        assert plugin.status == PluginStatus.DISABLED

    @pytest.mark.asyncio
    async def test_on_load(self, tmp_path):
        plugin = PluginBase()
        ctx = PluginContext(plugin_id="test", data_dir=tmp_path)
        await plugin.on_load(ctx)
        assert plugin.status == PluginStatus.LOADED
        assert plugin.context is ctx

    @pytest.mark.asyncio
    async def test_on_unload(self, tmp_path):
        plugin = PluginBase()
        ctx = PluginContext(plugin_id="test", data_dir=tmp_path)
        await plugin.on_load(ctx)
        await plugin.on_unload()
        assert plugin.status == PluginStatus.DISABLED

    @pytest.mark.asyncio
    async def test_register_and_emit_hook(self, tmp_path):
        plugin = PluginBase()
        results = []
        plugin.register_hook(PluginHook.ON_TASK_CREATE, lambda goal=None, **kw: results.append(goal))
        await plugin.emit(PluginHook.ON_TASK_CREATE, goal="test task")
        assert results == ["test task"]

    @pytest.mark.asyncio
    async def test_emit_no_handler(self, tmp_path):
        plugin = PluginBase()
        result = await plugin.emit(PluginHook.ON_PLAN_GENERATE)
        assert result is None
