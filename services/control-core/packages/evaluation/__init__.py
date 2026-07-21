"""Evaluation — task assessment, skill metrics, regression checks."""

__all__ = [
    "TaskEvaluator",
]


def __getattr__(name: str):
    """Lazy imports to avoid circular dependency at module load time."""
    if name == "TaskEvaluator":
        from packages.evaluation.task_evaluator import TaskEvaluator
        return TaskEvaluator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
