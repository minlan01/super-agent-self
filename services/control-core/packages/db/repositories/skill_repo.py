"""Repository for Skill and SkillRun CRUD operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.agent_core.schemas import SkillCreate, SkillRunCreate, SkillUpdate
from packages.db.models import Skill, SkillRun


class SkillRepository:
    @staticmethod
    def create(db: Session, schema: SkillCreate) -> Skill:
        skill = Skill(
            name=schema.name,
            definition=schema.definition,
            description=schema.description,
            edition=schema.edition,
            source_task_id=schema.source_task_id,
        )
        db.add(skill)
        db.flush()
        db.refresh(skill)
        return skill

    @staticmethod
    def get_by_id(db: Session, skill_id: str) -> Skill | None:
        return db.get(Skill, skill_id)

    @staticmethod
    def list_skills(
        db: Session,
        edition=None,
        status=None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[Skill]:
        stmt = select(Skill).order_by(Skill.created_at.desc())
        if edition is not None:
            stmt = stmt.where(Skill.edition == edition)
        if status is not None:
            stmt = stmt.where(Skill.status == status)
        stmt = stmt.offset(skip).limit(limit)
        return list(db.scalars(stmt).all())

    @staticmethod
    def update(db: Session, skill_id: str, schema: SkillUpdate) -> Skill | None:
        skill = db.get(Skill, skill_id)
        if skill is None:
            return None
        update_data = schema.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(skill, field, value)
        db.flush()
        db.refresh(skill)
        return skill

    @staticmethod
    def add_run(db: Session, skill_id: str, schema: SkillRunCreate) -> SkillRun:
        run = SkillRun(
            skill_id=skill_id,
            task_id=schema.task_id,
            success=schema.success,
            metrics=schema.metrics,
            error=schema.error,
        )
        db.add(run)
        db.flush()
        db.refresh(run)
        return run

    @staticmethod
    def get_runs(db: Session, skill_id: str, limit: int = 100) -> list[SkillRun]:
        stmt = (
            select(SkillRun)
            .where(SkillRun.skill_id == skill_id)
            .order_by(SkillRun.created_at.desc())
            .limit(limit)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_runs_by_task(db: Session, task_id: str) -> list[SkillRun]:
        """Get all skill runs for a task."""
        return list(db.scalars(select(SkillRun).where(SkillRun.task_id == task_id)).all())

    @staticmethod
    def update_run_benchmark(db: Session, run_id: str, with_skill_duration: float, without_skill_duration: float) -> None:
        """Update benchmark fields on a skill run."""
        run = db.get(SkillRun, run_id)
        if run:
            run.with_skill_duration = with_skill_duration
            run.without_skill_duration = without_skill_duration
            db.flush()
