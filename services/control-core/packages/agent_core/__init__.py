"""Agent core — orchestration, sub-agents, task state, and schemas."""

from packages.agent_core.version import __version__

__all__ = [
    "__version__",
]


def __getattr__(name: str):
    """Lazy imports to avoid circular dependency at module load time."""
    _lazy = {
        "AgentBus": "packages.agent_core.agent_bus",
        "AgentMessage": "packages.agent_core.agent_bus",
        "MessageType": "packages.agent_core.agent_bus",
        "ContextCompressor": "packages.agent_core.context_compressor",
        "EditionManager": "packages.agent_core.edition_manager",
        "Orchestrator": "packages.agent_core.orchestrator",
        "DelegateTask": "packages.agent_core.sub_agent",
        "InvalidTransition": "packages.agent_core.task_state",
        "TaskStateMachine": "packages.agent_core.task_state",
    }
    if name in _lazy:
        import importlib
        module = importlib.import_module(_lazy[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
