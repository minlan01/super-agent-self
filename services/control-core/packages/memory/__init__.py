"""Memory service and retriever package."""

__all__ = [
    "ImportanceScorer",
    "MemoryRetriever",
    "MemoryService",
    "MemorySummarizer",
]


def __getattr__(name: str):
    """Lazy imports to avoid circular dependency at module load time."""
    _lazy = {
        "ImportanceScorer": ("packages.memory.importance_scorer", "ImportanceScorer"),
        "MemoryService": ("packages.memory.memory_service", "MemoryService"),
        "MemoryRetriever": ("packages.memory.retriever", "MemoryRetriever"),
        "MemorySummarizer": ("packages.memory.summarizer", "MemorySummarizer"),
    }
    if name in _lazy:
        import importlib
        mod_path, attr = _lazy[name]
        return getattr(importlib.import_module(mod_path), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
