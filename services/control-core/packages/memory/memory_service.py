"""Memory Service — writes, retrieves, and manages long-term memories."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from packages.agent_core.schemas import AuditEventCreate, MemoryCreate
from packages.db.models import AuditEventType, Memory
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.memory_repo import MemoryRepository, compute_content_hash
from packages.memory.importance_scorer import ImportanceScorer
from packages.memory.schemas import MemoryWriteRequest
from packages.memory.summarizer import MemorySummarizer

logger = logging.getLogger(__name__)

_MEMORY_RATE_LIMIT = 30
_MEMORY_RATE_WINDOW = 60


class _SlidingWindowRateLimiter:
    """Thread-safe sliding window rate limiter for memory creation."""

    def __init__(self, max_requests: int, window_seconds: float):
        self._max = max_requests
        self._window = window_seconds
        self._timestamps: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        with self._lock:
            now = time.time()
            cutoff = now - self._window
            timestamps = self._timestamps.get(key, [])
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._max:
                self._timestamps[key] = timestamps
                return False
            timestamps.append(now)
            self._timestamps[key] = timestamps
            return True


class MemoryService:
    """Coordinates memory lifecycle: write on task completion, dedup, audit."""

    def __init__(
        self,
        summarizer: MemorySummarizer,
        importance_scorer: ImportanceScorer | None = None,
    ):
        self.summarizer = summarizer
        self.scorer = importance_scorer or ImportanceScorer()
        self._rate_limiter = _SlidingWindowRateLimiter(
            _MEMORY_RATE_LIMIT, _MEMORY_RATE_WINDOW
        )

    async def write_from_task(
        self,
        db: Session,
        request: MemoryWriteRequest,
        user_id: str = "default",
        edition: str = "enterprise",
    ) -> Memory | None:
        """Write a memory from a completed task.

        Returns the created memory, or None if deduplicated.
        """
        if not self._rate_limiter.is_allowed(f"mem:{user_id}:{edition}"):
            logger.warning(
                "Memory write rate limit exceeded for user=%s edition=%s",
                user_id, edition,
            )
            return None

        # Generate summary
        summary = await self.summarizer.summarize(request)

        # Calculate importance
        importance = self.scorer.score(
            memory_type=request.memory_type,
            base_importance=summary.importance_score,
            success=request.success,
            step_count=len(request.steps_summary),
        )

        # Build content and check for duplicates
        content = {
            "goal": request.goal,
            "steps": request.steps_summary,
            "success": request.success,
        }
        content_hash = compute_content_hash(content)

        existing = self._find_by_hash(db, content_hash, user_id, edition)
        if existing is not None:
            logger.info(
                "Memory deduplicated: hash=%s already exists as %s",
                content_hash[:12], existing.id,
            )
            return None

        mem_type = request.memory_type
        task_id = request.task_id

        def _persist(worker_db: Session) -> Memory:
            memory = MemoryRepository.create(worker_db, user_id, edition, MemoryCreate(
                memory_type=mem_type,
                title=summary.title,
                summary=summary.summary,
                content=content,
                importance_score=importance,
                confidence_score=summary.confidence_score,
                source_task_id=task_id,
            ))
            memory.content_hash = content_hash
            worker_db.flush()
            worker_db.refresh(memory)
            AuditRepository.create(worker_db, AuditEventCreate(
                task_id=task_id,
                edition=edition,
                event_type=AuditEventType.MEMORY_WRITTEN,
                detail={"memory_id": memory.id, "memory_type": mem_type.value},
            ))
            return memory

        memory = await asyncio.to_thread(_persist, db)

        logger.info("Memory written: %s (%s)", memory.id, request.memory_type.value)
        return memory

    def get_memory(self, db: Session, memory_id: str) -> Memory | None:
        return MemoryRepository.get_by_id(db, memory_id)

    def list_memories(
        self,
        db: Session,
        user_id: str = "default",
        memory_type: str | None = None,
        is_active: bool = True,
        skip: int = 0,
        limit: int = 20,
    ) -> list[Memory]:
        return MemoryRepository.list_memories(
            db, user_id, memory_type=memory_type,
            is_active=is_active, skip=skip, limit=limit,
        )

    def disable_memory(self, db: Session, memory_id: str) -> Memory | None:
        return MemoryRepository.disable(db, memory_id)

    def delete_memory(self, db: Session, memory_id: str) -> bool:
        return MemoryRepository.delete(db, memory_id)

    def search(
        self,
        db: Session,
        keyword: str | None = None,
        memory_type: str | None = None,
        source_task_id: str | None = None,
        user_id: str = "default",
        edition: str = "enterprise",
        is_active: bool = True,
        limit: int = 10,
    ) -> list[Memory]:
        from packages.agent_core.schemas import MemorySearchQuery
        from packages.db.models import MemoryType

        query = MemorySearchQuery(
            keyword=keyword,
            memory_type=MemoryType(memory_type) if memory_type else None,
            source_task_id=source_task_id,
            is_active=is_active,
            limit=limit,
        )
        return MemoryRepository.search(db, query, user_id, edition)

    @staticmethod
    def _find_by_hash(
        db: Session, content_hash: str, user_id: str, edition: str,
    ) -> Memory | None:
        from sqlalchemy import select
        stmt = select(Memory).where(
            Memory.content_hash == content_hash,
            Memory.user_id == user_id,
            Memory.is_active == True,  # noqa: E712
        ).limit(1)
        return db.scalar(stmt)
