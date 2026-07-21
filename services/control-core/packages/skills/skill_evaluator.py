"""Skill Evaluator — metrics tracking and degradation logic."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from packages.agent_core.schemas import AuditEventCreate, SkillRunCreate
from packages.db.models import AuditEventType, Skill, SkillRun, SkillStatus
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.skill_repo import SkillRepository
from packages.skills.schemas import SkillDegradationCheck

logger = logging.getLogger(__name__)


class SkillEvaluator:
    """Tracks skill performance and triggers degradation when needed."""

    def __init__(self, config_path: str = "configs/skills.yaml"):
        self.consecutive_failures_limit = 3
        self.min_success_rate = 0.7
        self.degradation_action = "disable"
        self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        degradation = cfg.get("skills", {}).get("degradation", {})
        self.consecutive_failures_limit = degradation.get("consecutive_failures", 3)
        self.min_success_rate = degradation.get("min_success_rate", 0.7)
        self.degradation_action = degradation.get("action", "disable")

    def record_run(
        self,
        db: Session,
        skill_id: str,
        task_id: str,
        success: bool,
        metrics: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> SkillRun:
        """Record a skill run and check for degradation."""
        run = SkillRepository.add_run(db, skill_id, SkillRunCreate(
            skill_id=skill_id,
            task_id=task_id,
            success=success,
            metrics=metrics,
            error=error,
        ))

        # Update skill success rate
        self._update_metrics(db, skill_id)

        try:
            from packages.middleware.prometheus import registry
            from packages.db.models import Skill
            skill_obj = db.get(Skill, skill_id)
            registry.skill_runs_total.inc(
                labels={"skill_name": skill_obj.name if skill_obj else skill_id, "status": "success" if success else "failure"},
            )
        except Exception:
            logger.debug("Prometheus skill metrics recording failed", exc_info=True)

        # Check degradation
        check = self.check_degradation(db, skill_id)
        if check.should_degrade:
            self._degrade(db, skill_id, check.reason)

        return run

    def check_degradation(self, db: Session, skill_id: str) -> SkillDegradationCheck:
        """Check if a skill should be degraded based on recent performance."""
        skill = db.get(Skill, skill_id)
        if skill is None:
            return SkillDegradationCheck(skill_id=skill_id, should_degrade=False, reason="Not found")

        if skill.status != SkillStatus.STABLE:
            return SkillDegradationCheck(
                skill_id=skill_id, should_degrade=False,
                reason=f"Skill is {skill.status.value}, not monitored",
            )

        runs = SkillRepository.get_runs(db, skill_id)

        # Check consecutive failures
        consecutive = 0
        for run in runs:
            if not run.success:
                consecutive += 1
            else:
                break

        if consecutive >= self.consecutive_failures_limit:
            return SkillDegradationCheck(
                skill_id=skill_id, should_degrade=True,
                reason=f"{consecutive} consecutive failures (limit: {self.consecutive_failures_limit})",
                current_success_rate=skill.success_rate,
                consecutive_failures=consecutive,
            )

        # Check success rate (need at least 3 runs)
        if len(runs) >= 3 and skill.success_rate < self.min_success_rate:
            return SkillDegradationCheck(
                skill_id=skill_id, should_degrade=True,
                reason=f"Success rate {skill.success_rate:.0%} below minimum {self.min_success_rate:.0%}",
                current_success_rate=skill.success_rate,
                consecutive_failures=consecutive,
            )

        return SkillDegradationCheck(
            skill_id=skill_id, should_degrade=False,
            current_success_rate=skill.success_rate,
            consecutive_failures=consecutive,
        )

    def _update_metrics(self, db: Session, skill_id: str) -> None:
        """Recalculate success rate from runs."""
        from packages.skills.skill_registry import SkillRegistryService
        registry = SkillRegistryService()
        registry.update_success_rate(db, skill_id)

    def _degrade(self, db: Session, skill_id: str, reason: str) -> None:
        """Degrade a skill based on configured action."""
        skill = db.get(Skill, skill_id)
        if skill is None:
            return

        if self.degradation_action == "disable":
            skill.status = SkillStatus.DISABLED
        else:
            skill.status = SkillStatus.DEPRECATED

        db.flush()
        AuditRepository.create(db, AuditEventCreate(
            event_type=AuditEventType.TASK_FAILED,
            detail={
                "action": "skill_degraded",
                "skill_id": skill_id,
                "skill_name": skill.name,
                "reason": reason,
                "new_status": skill.status.value,
            },
        ))
        logger.warning("Skill '%s' degraded: %s → %s", skill.name, reason, skill.status.value)
