"""Skill Registry service — CRUD, dedup, versioning for skills."""

from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import Skill, SkillStatus
from packages.skills.schemas import SkillDefinition

logger = logging.getLogger(__name__)


class SkillRegistryService:
    """Service-level skill registry with dedup and versioning."""

    def __init__(self, max_versions: int = 5):
        self.max_versions = max_versions

    def create(
        self,
        db: Session,
        definition: SkillDefinition,
        edition: str = "enterprise",
        source_task_id: str | None = None,
    ) -> Skill:
        """Create a new candidate skill, or bump version if duplicate name exists."""
        # Check for existing skill with same name
        existing = self._find_by_name(db, definition.name, edition)
        if existing is not None:
            # Bump version
            return self._create_version(db, existing, definition, source_task_id)

        # Create new
        def_hash = self._definition_hash(definition)
        skill = Skill(
            name=definition.name,
            definition={
                "name": definition.name,
                "description": definition.description,
                "steps_template": definition.steps_template,
                "tags": definition.tags,
                "hash": def_hash,
            },
            description=definition.description,
            edition=edition,
            source_task_id=source_task_id,
            status=SkillStatus.CANDIDATE,
            version=1,
        )
        db.add(skill)
        db.flush()
        db.refresh(skill)
        logger.info("Created skill '%s' v1 (candidate)", definition.name)
        return skill

    def get_by_id(self, db: Session, skill_id: str) -> Skill | None:
        return db.get(Skill, skill_id)

    def list_skills(
        self,
        db: Session,
        edition: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[Skill]:
        from packages.db.repositories.skill_repo import SkillRepository
        return SkillRepository.list_skills(db, edition=edition, status=status, skip=skip, limit=limit)

    def approve(self, db: Session, skill_id: str) -> Skill | None:
        """Move a candidate skill to stable."""
        skill = db.get(Skill, skill_id)
        if skill is None:
            return None
        if skill.status != SkillStatus.CANDIDATE:
            raise ValueError(f"Can only approve candidate skills, current status: {skill.status.value}")
        skill.status = SkillStatus.STABLE
        db.flush()
        db.refresh(skill)
        logger.info("Skill '%s' approved → stable", skill.name)
        return skill

    def disable(self, db: Session, skill_id: str) -> Skill | None:
        skill = db.get(Skill, skill_id)
        if skill is None:
            return None
        if skill.status == SkillStatus.DISABLED:
            raise ValueError(f"Skill '{skill.name}' is already disabled")
        skill.status = SkillStatus.DISABLED
        db.flush()
        db.refresh(skill)
        logger.info("Skill '%s' disabled", skill.name)
        return skill

    def rollback(self, db: Session, skill_id: str) -> Skill | None:
        """Re-enable a disabled skill back to stable."""
        skill = db.get(Skill, skill_id)
        if skill is None:
            return None
        if skill.status != SkillStatus.DISABLED:
            raise ValueError(f"Skill '{skill.name}' is not disabled (current: {skill.status.value})")
        skill.status = SkillStatus.STABLE
        db.flush()
        db.refresh(skill)
        logger.info("Skill '%s' rolled back → stable", skill.name)
        return skill

    def update_success_rate(self, db: Session, skill_id: str) -> Skill:
        """Recalculate success_rate from skill_runs."""
        from packages.db.repositories.skill_repo import SkillRepository

        runs = SkillRepository.get_runs(db, skill_id)
        if not runs:
            return db.get(Skill, skill_id)

        skill = db.get(Skill, skill_id)
        successes = sum(1 for r in runs if r.success)
        skill.success_rate = round(successes / len(runs), 2)
        skill.total_runs = len(runs)
        db.flush()
        db.refresh(skill)
        return skill

    def _find_by_name(self, db: Session, name: str, edition: str) -> Skill | None:
        stmt = (
            select(Skill)
            .where(Skill.name == name, Skill.edition == edition)
            .order_by(Skill.version.desc())
            .limit(1)
        )
        return db.scalar(stmt)

    def _create_version(
        self,
        db: Session,
        existing: Skill,
        definition: SkillDefinition,
        source_task_id: str | None,
    ) -> Skill:
        """Create a new version of an existing skill."""
        # Check definition hash to avoid duplicate versions
        new_hash = self._definition_hash(definition)
        old_hash = existing.definition.get("hash", "")
        if new_hash == old_hash:
            logger.info("Skill '%s' definition unchanged, skipping version", definition.name)
            return existing

        new_version = existing.version + 1
        if new_version > self.max_versions:
            # Deprecate oldest
            self._deprecate_oldest(db, definition.name, existing.edition)

        skill = Skill(
            name=definition.name,
            definition={
                "name": definition.name,
                "description": definition.description,
                "steps_template": definition.steps_template,
                "tags": definition.tags,
                "hash": new_hash,
            },
            description=definition.description,
            edition=existing.edition,
            source_task_id=source_task_id,
            status=SkillStatus.CANDIDATE,
            version=new_version,
        )
        db.add(skill)
        db.flush()
        db.refresh(skill)
        logger.info("Created skill '%s' v%d (candidate)", definition.name, new_version)
        return skill

    def _deprecate_oldest(self, db: Session, name: str, edition: str) -> None:
        stmt = (
            select(Skill)
            .where(Skill.name == name, Skill.edition == edition)
            .order_by(Skill.version.asc())
        )
        oldest = db.scalar(stmt)
        if oldest and oldest.status == SkillStatus.STABLE:
            oldest.status = SkillStatus.DEPRECATED
            db.flush()

    @staticmethod
    def _definition_hash(definition: SkillDefinition) -> str:
        data = json.dumps(
            {"steps": [s.get("tool_name") for s in definition.steps_template]},
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()[:16]
