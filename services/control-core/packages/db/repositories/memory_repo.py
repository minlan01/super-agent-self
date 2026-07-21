"""Repository for Memory CRUD operations."""

import hashlib
import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.agent_core.schemas import MemoryCreate, MemorySearchQuery, MemoryUpdate
from packages.db.models import Memory


def compute_content_hash(content) -> str:
    """Canonical content hash used for dedup — single source of truth."""
    raw = json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class MemoryRepository:
    @staticmethod
    def create(db: Session, user_id: str, edition: str, schema: MemoryCreate) -> Memory:
        # Dedup: check for existing memory with same content_hash + user_id
        if schema.content:
            content_hash = compute_content_hash(schema.content)
            existing = db.scalars(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.content_hash == content_hash,
                    Memory.is_active == True,  # noqa: E712
                ).limit(1)
            ).first()
            if existing:
                return existing

        memory = Memory(
            user_id=user_id,
            edition=edition,
            memory_type=schema.memory_type,
            title=schema.title,
            summary=schema.summary,
            content=schema.content,
            importance_score=schema.importance_score,
            confidence_score=schema.confidence_score,
            source_task_id=schema.source_task_id,
            expires_at=schema.expires_at,
        )
        db.add(memory)
        db.flush()
        db.refresh(memory)
        return memory

    @staticmethod
    def get_by_id(db: Session, memory_id: str) -> Memory | None:
        return db.get(Memory, memory_id)

    @staticmethod
    def search(
        db: Session,
        query: MemorySearchQuery,
        user_id: str,
        edition: str,
    ) -> list[Memory]:
        stmt = select(Memory).where(
            Memory.user_id == user_id,
            Memory.edition == edition,
            Memory.is_active == query.is_active,
        )
        if query.keyword:
            safe_kw = query.keyword.replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{safe_kw}%"
            stmt = stmt.where(
                or_(
                    Memory.title.ilike(pattern, escape="\\"),
                    Memory.summary.ilike(pattern, escape="\\"),
                )
            )
        if query.memory_type is not None:
            stmt = stmt.where(Memory.memory_type == query.memory_type)
        if query.source_task_id is not None:
            stmt = stmt.where(Memory.source_task_id == query.source_task_id)
        stmt = stmt.order_by(Memory.importance_score.desc()).limit(query.limit)
        return list(db.scalars(stmt).all())

    @staticmethod
    def list_memories(
        db: Session,
        user_id: str,
        memory_type=None,
        is_active: bool = True,
        skip: int = 0,
        limit: int = 20,
    ) -> list[Memory]:
        stmt = select(Memory).where(
            Memory.user_id == user_id,
            Memory.is_active == is_active,
        )
        if memory_type is not None:
            stmt = stmt.where(Memory.memory_type == memory_type)
        stmt = stmt.order_by(Memory.created_at.desc()).offset(skip).limit(limit)
        return list(db.scalars(stmt).all())

    @staticmethod
    def update(db: Session, memory_id: str, schema: MemoryUpdate) -> Memory | None:
        memory = db.get(Memory, memory_id)
        if memory is None:
            return None
        update_data = schema.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(memory, field, value)
        db.flush()
        db.refresh(memory)
        return memory

    @staticmethod
    def disable(db: Session, memory_id: str) -> Memory | None:
        memory = db.get(Memory, memory_id)
        if memory is None:
            return None
        memory.is_active = False
        db.flush()
        db.refresh(memory)
        return memory

    @staticmethod
    def delete(db: Session, memory_id: str) -> bool:
        memory = db.get(Memory, memory_id)
        if memory is None:
            return False
        db.delete(memory)
        db.flush()
        return True
