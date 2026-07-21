"""MCP (Model Context Protocol) client package."""

__all__ = [
    "MCPClient",
    "MCPToolAdapter",
]


def __getattr__(name: str):
    """Lazy imports to avoid circular dependency at module load time."""
    _lazy = {
        "MCPClient": ("packages.mcp.mcp_client", "MCPClient"),
        "MCPToolAdapter": ("packages.mcp.mcp_tool_adapter", "MCPToolAdapter"),
    }
    if name in _lazy:
        import importlib
        mod_path, attr = _lazy[name]
        return getattr(importlib.import_module(mod_path), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
