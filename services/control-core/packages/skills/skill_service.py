"""Skill Service — coordinates skill lifecycle: extraction, reuse, metrics."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from packages.agent_core.schemas import AuditEventCreate
from packages.db.models import AuditEventType
from packages.db.repositories.audit_repo import AuditRepository
from packages.skills.skill_evaluator import SkillEvaluator
from packages.skills.skill_extractor import SkillExtractor
from packages.skills.skill_registry import SkillRegistryService

logger = logging.getLogger(__name__)


class SkillService:
    """Main service for skill lifecycle management."""

    def __init__(
        self,
        extractor: SkillExtractor | None = None,
        registry: SkillRegistryService | None = None,
        evaluator: SkillEvaluator | None = None,
    ):
        self.extractor = extractor or SkillExtractor()
        self.registry = registry or SkillRegistryService()
        self.evaluator = evaluator or SkillEvaluator()

    def on_task_completed(
        self,
        db: Session,
        task_id: str,
        goal: str,
        steps: list[dict[str, Any]],
        success: bool,
        edition: str = "enterprise",
    ) -> Any | None:
        """Called when a task completes. Attempts to extract a skill.

        Returns the created Skill or None.
        """
        result = self.extractor.extract(goal, steps, success)
        if not result.extracted:
            logger.info("No skill extracted from task %s: %s", task_id, result.reason)
            return None

        assert result.skill is not None

        try:
            skill = self.registry.create(
                db,
                definition=result.skill,
                edition=edition,
                source_task_id=task_id,
            )
            AuditRepository.create(db, AuditEventCreate(
                task_id=task_id,
                event_type=AuditEventType.SKILL_EXTRACTED,
                detail={
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "version": skill.version,
                },
            ))
            logger.info("Skill extracted from task %s: %s v%d", task_id, skill.name, skill.version)
            return skill
        except Exception:
            logger.exception("Failed to create skill from task %s", task_id)
            return None

    def approve_skill(self, db: Session, skill_id: str) -> Any | None:
        """Approve a candidate skill."""
        skill = self.registry.approve(db, skill_id)
        if skill:
            AuditRepository.create(db, AuditEventCreate(
                event_type=AuditEventType.SKILL_APPROVED,
                detail={"skill_id": skill_id, "skill_name": skill.name},
            ))
        return skill

    def get_skills_for_planner(
        self,
        db: Session,
        goal: str,
        edition: str = "enterprise",
    ) -> list[dict[str, Any]]:
        """Get approved skills relevant to a goal for planner injection.

        Returns skills that are STABLE and match tags from the goal.
        """
        skills = self.registry.list_skills(
            db, edition=edition, status="stable",
        )

        # Simple keyword matching
        goal_lower = goal.lower()
        relevant = []
        for skill in skills:
            tags = skill.definition.get("tags", [])
            name_lower = skill.name.lower()
            if any(t in goal_lower for t in tags) or any(w in goal_lower for w in name_lower.split("_")):
                relevant.append({
                    "id": skill.id,
                    "name": skill.name,
                    "description": skill.description or "",
                    "steps": skill.definition.get("steps_template", []),
                    "success_rate": skill.success_rate,
                })

        return relevant[:5]  # Max 5 skills

    def record_skill_run(
        self,
        db: Session,
        skill_id: str,
        task_id: str,
        success: bool,
        metrics: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Any:
        """Record a skill run and check for degradation."""
        return self.evaluator.record_run(
            db, skill_id, task_id, success, metrics, error,
        )

    # Delegate CRUD
    def get_skill(self, db: Session, skill_id: str) -> Any | None:
        return self.registry.get_by_id(db, skill_id)

    def list_skills(self, db: Session, **kwargs) -> list[Any]:
        return self.registry.list_skills(db, **kwargs)

    def disable_skill(self, db: Session, skill_id: str) -> Any | None:
        return self.registry.disable(db, skill_id)

    def rollback_skill(self, db: Session, skill_id: str) -> Any | None:
        return self.registry.rollback(db, skill_id)
