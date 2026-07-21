"""Memory Retriever — recalls relevant memories for planner injection."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.agent_core.schemas import MemorySearchQuery
from packages.db.models import Memory
from packages.db.repositories.memory_repo import MemoryRepository
from packages.memory.schemas import MemoryRetrievalResult

logger = logging.getLogger(__name__)

# Time decay: multiply importance by this factor per day since creation
DECAY_FACTOR_PER_DAY = 0.95
# Boost for memories created in the last 7 days
RECENCY_BOOST_DAYS = 7
RECENCY_BOOST_MULTIPLIER = 1.3

# Optional: sentence-transformers for semantic retrieval
_EMBEDDING_AVAILABLE = False
try:
    import numpy as np  # noqa: F401 — optional dependency probe
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
    _EMBEDDING_AVAILABLE = True
except ImportError:
    pass


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class MemoryRetriever:
    """Retrieves memories for injection into planner prompts.

    Enforces token budget and importance thresholds.
    Applies time-decay and recency boosting.
    Supports optional embedding-based semantic retrieval.
    """

    def __init__(self, config_path: str = "configs/memory.yaml"):
        self.max_results = 5
        self.max_total_tokens = 1500
        self.min_importance = 0.3
        self.min_confidence = 0.5
        self._embedding_model = None
        self._load_config(config_path)
        self._init_embeddings()

    def _load_config(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        retrieval = cfg.get("memory", {}).get("retrieval", {})
        self.max_results = retrieval.get("max_results", 5)
        self.max_total_tokens = retrieval.get("max_total_tokens", 1500)
        self.min_importance = retrieval.get("min_importance", 0.3)
        self.min_confidence = retrieval.get("min_confidence", 0.5)

    def _init_embeddings(self) -> None:
        """Initialize embedding model if sentence-transformers is available."""
        if not _EMBEDDING_AVAILABLE:
            logger.info("sentence-transformers not available, using keyword-only retrieval")
            return
        try:
            self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Embedding model loaded: all-MiniLM-L6-v2")
        except Exception as exc:
            logger.warning("Failed to load embedding model: %s", exc)
            self._embedding_model = None

    @property
    def _has_embeddings(self) -> bool:
        return self._embedding_model is not None

    def _embed(self, text: str) -> list[float] | None:
        """Generate embedding for text. Returns None if unavailable."""
        if not self._has_embeddings:
            return None
        try:
            vec = self._embedding_model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        except Exception as e:
            logger.warning("Embedding generation failed: %s", e)
            return None

    def _embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embeddings for a batch of texts. Much faster than per-text encoding."""
        if not self._has_embeddings or not texts:
            return [None] * len(texts)
        try:
            vectors = self._embedding_model.encode(texts, normalize_embeddings=True, batch_size=32)
            return [v.tolist() for v in vectors]
        except Exception as e:
            logger.warning("Batch embedding generation failed: %s", e)
            return [None] * len(texts)

    def _semantic_search(
        self, db: Session, goal: str, user_id: str, edition: str,
    ) -> list[tuple[Memory, float]]:
        """Search memories by semantic similarity to the goal.

        Returns list of (memory, similarity_score) tuples.
        Falls back to empty list if embeddings unavailable.
        Uses batch encoding for efficiency.
        """
        if not self._has_embeddings:
            return []

        goal_embedding = self._embed(goal)
        if goal_embedding is None:
            return []

        candidates = self._recent_high_importance(
            db, user_id, edition, limit=50,
        )

        texts = [f"{mem.title} {mem.summary}" for mem in candidates]
        embeddings = self._embed_batch(texts)

        scored: list[tuple[Memory, float]] = []
        for mem, mem_embedding in zip(candidates, embeddings):
            if mem_embedding is None:
                continue
            sim = _cosine_similarity(goal_embedding, mem_embedding)
            scored.append((mem, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:self.max_results]

    def _adjusted_score(self, memory: Memory) -> float:
        """Compute time-adjusted importance score with decay and recency boost."""
        base = memory.importance_score

        # Time decay: older memories lose importance
        if memory.created_at:
            now = datetime.now(UTC)
            created = memory.created_at
            # Handle both tz-aware and tz-naive datetimes
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            age_days = (now - created).total_seconds() / 86400
            if age_days > 0:
                base *= DECAY_FACTOR_PER_DAY ** age_days

            # Recency boost: fresh memories get a multiplier
            if age_days <= RECENCY_BOOST_DAYS:
                base *= RECENCY_BOOST_MULTIPLIER

        return base

    def retrieve(
        self,
        db: Session,
        goal: str,
        user_id: str = "default",
        edition: str = "enterprise",
        recent_task_id: str | None = None,
    ) -> MemoryRetrievalResult:
        """Retrieve relevant memories for a planning request.

        Strategy (with embeddings):
        1. Semantic search using cosine similarity
        2. Fill remaining slots with keyword search
        3. Fill remaining slots with recent high-importance

        Strategy (without embeddings):
        1. Keyword search on goal
        2. Fill remaining slots with recent high-importance

        Then: filter by thresholds, sort by time-adjusted score, enforce budget.
        """
        all_memories: list[Memory] = []
        seen_ids: set[str] = set()

        # Strategy 0: Semantic search (if embeddings available)
        if self._has_embeddings:
            semantic_results = self._semantic_search(db, goal, user_id, edition)
            for mem, score in semantic_results:
                if mem.id not in seen_ids:
                    all_memories.append(mem)
                    seen_ids.add(mem.id)

        # Strategy 1: Keyword search (fill gaps)
        keyword_memories = self._keyword_search(db, goal, user_id, edition)
        for m in keyword_memories:
            if m.id not in seen_ids:
                all_memories.append(m)
                seen_ids.add(m.id)

        # Strategy 2: Fill with recent high-importance if under budget
        remaining = self.max_results - len(all_memories)
        if remaining > 0:
            recent = self._recent_high_importance(
                db, user_id, edition, limit=remaining * 2,
                exclude_ids=seen_ids,
            )
            all_memories.extend(recent)

        # Filter by thresholds
        filtered = [
            m for m in all_memories
            if m.importance_score >= self.min_importance
            and m.confidence_score >= self.min_confidence
        ]

        # Sort by time-adjusted score (decay + recency boost)
        filtered.sort(key=lambda m: self._adjusted_score(m), reverse=True)
        filtered = filtered[:self.max_results]

        # Enforce token budget
        result_memories, token_estimate, truncated = self._enforce_budget(filtered)

        return MemoryRetrievalResult(
            memories=result_memories,
            total_count=len(filtered),
            token_estimate=token_estimate,
            truncated=truncated,
        )

    def _keyword_search(
        self, db: Session, goal: str, user_id: str, edition: str,
    ) -> list[Memory]:
        """Extract keywords from goal and search — single combined query."""
        from sqlalchemy import or_

        keywords = self._extract_keywords(goal)
        if not keywords:
            return []

        # Build a single OR query across all keywords instead of N separate queries
        conditions = []
        for kw in keywords:
            safe_kw = kw.replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{safe_kw}%"
            conditions.append(
                Memory.title.ilike(pattern, escape="\\") | Memory.summary.ilike(pattern, escape="\\")
            )
        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.is_active == True,  # noqa: E712
                or_(*conditions),
            )
            .order_by(Memory.importance_score.desc())
            .limit(self.max_results)
        )
        if edition:
            stmt = stmt.where(Memory.edition == edition)
        return list(db.scalars(stmt).all())

    def _recent_high_importance(
        self,
        db: Session,
        user_id: str,
        edition: str,
        limit: int = 10,
        exclude_ids: set[str] | None = None,
    ) -> list[Memory]:
        """Get recent high-importance memories."""
        from sqlalchemy import select

        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.is_active == True,  # noqa: E712
                Memory.importance_score >= self.min_importance,
            )
            .order_by(Memory.importance_score.desc(), Memory.created_at.desc())
            .limit(limit)
        )
        if edition:
            stmt = stmt.where(Memory.edition == edition)
        if exclude_ids:
            stmt = stmt.where(Memory.id.notin_(exclude_ids))

        return list(db.scalars(stmt).all())

    @staticmethod
    def _extract_keywords(goal: str) -> list[str]:
        """Simple keyword extraction from goal text."""
        # Remove common stop words and split
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "to", "of", "and", "in", "that", "it", "for", "on", "with",
            "as", "by", "at", "from", "or", "an", "this", "can", "do",
            "will", "would", "should", "could", "may", "might", "shall",
        }
        words = goal.lower().replace(".", " ").replace(",", " ").split()
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        return keywords[:5]  # top 5 keywords

    def _enforce_budget(
        self, memories: list[Memory],
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """Convert memories to dicts and enforce token budget.

        Rough estimate: 1 token ≈ 4 chars.
        """
        result: list[dict[str, Any]] = []
        total_chars = 0
        truncated = False

        for m in memories:
            entry = {
                "id": m.id,
                "title": m.title,
                "summary": m.summary,
                "memory_type": m.memory_type.value,
                "importance_score": m.importance_score,
            }
            entry_chars = len(m.title) + len(m.summary) + 50  # overhead
            estimated_tokens = (total_chars + entry_chars) // 4

            if estimated_tokens > self.max_total_tokens:
                truncated = True
                break

            result.append(entry)
            total_chars += entry_chars

        return result, total_chars // 4, truncated
