"""Edition Manager — loads and applies edition-specific configuration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class EditionManager:
    """Manages edition-specific configuration and feature flags."""

    def __init__(self, editions_dir: str = "configs/editions"):
        self._editions: dict[str, dict[str, Any]] = {}
        self._load_all(Path(editions_dir))

    def _load_all(self, editions_dir: Path) -> None:
        if not editions_dir.exists():
            logger.warning("Editions directory not found: %s", editions_dir)
            return
        for f in editions_dir.glob("*.yaml"):
            try:
                with open(f, encoding="utf-8") as fh:
                    cfg = yaml.safe_load(fh) or {}
                edition = cfg.get("edition", f.stem)
                self._editions[edition] = cfg
                logger.info("Loaded edition config: %s", edition)
            except Exception:
                logger.exception("Failed to load edition %s", f)

    def get_config(self, edition: str) -> dict[str, Any]:
        """Get full config for an edition. Falls back to empty dict."""
        return self._editions.get(edition, {})

    def get_enabled_tools(self, edition: str) -> list[str]:
        cfg = self.get_config(edition)
        return cfg.get("tools", {}).get("enabled", [])

    def get_disabled_tools(self, edition: str) -> list[str]:
        cfg = self.get_config(edition)
        return cfg.get("tools", {}).get("disabled", [])

    def get_max_risk_level(self, edition: str) -> str:
        cfg = self.get_config(edition)
        return cfg.get("policy", {}).get("max_risk_level", "medium")

    def get_memory_types(self, edition: str) -> list[str]:
        cfg = self.get_config(edition)
        return cfg.get("memory", {}).get("types", [])

    def get_retention_days(self, edition: str) -> int:
        cfg = self.get_config(edition)
        return cfg.get("memory", {}).get("retention_days", 90)

    def auto_approve_low_risk(self, edition: str) -> bool:
        cfg = self.get_config(edition)
        return cfg.get("approval", {}).get("auto_approve_low_risk", True)

    def is_personal(self, edition: str) -> bool:
        return edition == "personal"

    def is_enterprise(self, edition: str) -> bool:
        return edition == "enterprise"

    def list_editions(self) -> list[str]:
        return list(self._editions.keys())

    def get_name(self, edition: str) -> str:
        cfg = self.get_config(edition)
        return cfg.get("name", edition.title())

    def get_description(self, edition: str) -> str:
        cfg = self.get_config(edition)
        return cfg.get("description", "")
