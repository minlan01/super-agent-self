"""Repository for EditionProfile CRUD operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.agent_core.schemas import EditionProfileCreate
from packages.db.models import EditionProfile


class EditionRepository:
    @staticmethod
    def create(db: Session, schema: EditionProfileCreate) -> EditionProfile:
        profile = EditionProfile(
            edition=schema.edition,
            name=schema.name,
            config=schema.config,
        )
        db.add(profile)
        db.flush()
        db.refresh(profile)
        return profile

    @staticmethod
    def get_active(db: Session, edition: str) -> EditionProfile | None:
        stmt = (
            select(EditionProfile)
            .where(EditionProfile.edition == edition, EditionProfile.is_active.is_(True))
            .order_by(EditionProfile.created_at.desc())
            .limit(1)
        )
        return db.scalars(stmt).first()

    @staticmethod
    def list_profiles(db: Session, edition=None) -> list[EditionProfile]:
        stmt = select(EditionProfile).order_by(EditionProfile.created_at.desc())
        if edition is not None:
            stmt = stmt.where(EditionProfile.edition == edition)
        return list(db.scalars(stmt).all())
