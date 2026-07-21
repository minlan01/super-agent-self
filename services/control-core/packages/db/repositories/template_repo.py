"""Repository for TaskTemplate CRUD operations."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.db.models import Edition, TaskTemplate


class TemplateRepository:
    @staticmethod
    def create(
        db: Session,
        name: str,
        goal_template: str,
        edition: Edition = Edition.ENTERPRISE,
        description: str | None = None,
        parameters: dict | None = None,
        is_builtin: bool = False,
    ) -> TaskTemplate:
        template = TaskTemplate(
            name=name,
            goal_template=goal_template,
            edition=edition,
            description=description,
            parameters=parameters,
            is_builtin=is_builtin,
        )
        db.add(template)
        db.flush()
        db.refresh(template)
        return template

    @staticmethod
    def get_by_id(db: Session, template_id: str) -> TaskTemplate | None:
        return db.get(TaskTemplate, template_id)

    @staticmethod
    def list_templates(
        db: Session,
        edition: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[TaskTemplate]:
        stmt = select(TaskTemplate).order_by(TaskTemplate.created_at.desc())
        if edition is not None:
            stmt = stmt.where(TaskTemplate.edition == edition)
        stmt = stmt.offset(skip).limit(limit)
        return list(db.scalars(stmt).all())

    @staticmethod
    def count(db: Session, edition: str | None = None) -> int:
        stmt = select(TaskTemplate)
        if edition is not None:
            stmt = stmt.where(TaskTemplate.edition == edition)
        return db.scalar(select(func.count()).select_from(stmt.subquery()))  # type: ignore[arg-type]

    @staticmethod
    def update(db: Session, template_id: str, **kwargs) -> TaskTemplate | None:
        template = db.get(TaskTemplate, template_id)
        if template is None:
            return None
        for field, value in kwargs.items():
            setattr(template, field, value)
        db.flush()
        db.refresh(template)
        return template

    @staticmethod
    def delete(db: Session, template_id: str) -> bool:
        template = db.get(TaskTemplate, template_id)
        if template is None:
            return False
        db.delete(template)
        db.flush()
        return True

    @staticmethod
    def increment_usage(db: Session, template_id: str) -> None:
        template = db.get(TaskTemplate, template_id)
        if template is not None:
            template.usage_count = (template.usage_count or 0) + 1
            db.flush()
