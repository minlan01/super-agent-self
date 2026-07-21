"""Skill service and extraction package."""

__all__ = [
    "SkillEvaluator",
    "SkillExtractor",
    "SkillMarketplace",
    "SkillRegistryService",
    "SkillService",
]


def __getattr__(name: str):
    """Lazy imports to avoid circular dependency at module load time."""
    _lazy = {
        "SkillMarketplace": ("packages.skills.marketplace", "SkillMarketplace"),
        "SkillEvaluator": ("packages.skills.skill_evaluator", "SkillEvaluator"),
        "SkillExtractor": ("packages.skills.skill_extractor", "SkillExtractor"),
        "SkillRegistryService": ("packages.skills.skill_registry", "SkillRegistryService"),
        "SkillService": ("packages.skills.skill_service", "SkillService"),
    }
    if name in _lazy:
        import importlib
        mod_path, attr = _lazy[name]
        return getattr(importlib.import_module(mod_path), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
