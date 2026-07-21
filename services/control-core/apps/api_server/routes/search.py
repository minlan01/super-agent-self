"""Unified full-text search across all entities."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_db, require_permission
from packages.agent_core.schemas import SearchDataResponse
from packages.db.models import (
    Conversation,
    ConversationMessage,
    Memory,
    Skill,
    Task,
)

router = APIRouter()

VALID_TYPES = {"task", "memory", "skill", "conversation"}


class SearchResultItem(BaseModel):
    id: str
    title: str
    matched_field: str
    extra: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    success: bool = True
    data: dict


def _search_tasks(db: Session, pattern: str, limit: int) -> list[SearchResultItem]:
    stmt = (
        select(Task)
        .where(
            or_(
                Task.goal.ilike(pattern, escape="\\"),
                Task.result.ilike(pattern, escape="\\"),
            )
        )
        .limit(limit)
    )
    rows = list(db.scalars(stmt).all())
    results: list[SearchResultItem] = []
    for r in rows:
        matched = "goal"
        if r.result and pattern.strip("%").lower() in (r.result or "").lower():
            matched = "result"
        results.append(
            SearchResultItem(
                id=r.id,
                title=r.goal[:200],
                matched_field=matched,
                extra={"status": r.status.value if r.status else None},
            )
        )
    return results


def _search_memories(db: Session, pattern: str, limit: int) -> list[SearchResultItem]:
    stmt = (
        select(Memory)
        .where(
            or_(
                Memory.title.ilike(pattern, escape="\\"),
                Memory.summary.ilike(pattern, escape="\\"),
            )
        )
        .limit(limit)
    )
    rows = list(db.scalars(stmt).all())
    results: list[SearchResultItem] = []
    for r in rows:
        matched = "title"
        if pattern.strip("%").lower() in (r.summary or "").lower():
            matched = "summary"
        results.append(
            SearchResultItem(
                id=r.id,
                title=r.title,
                matched_field=matched,
                extra={"memory_type": r.memory_type.value if r.memory_type else None},
            )
        )
    return results


def _search_skills(db: Session, pattern: str, limit: int) -> list[SearchResultItem]:
    stmt = (
        select(Skill)
        .where(
            or_(
                Skill.name.ilike(pattern, escape="\\"),
                Skill.description.ilike(pattern, escape="\\"),
            )
        )
        .limit(limit)
    )
    rows = list(db.scalars(stmt).all())
    results: list[SearchResultItem] = []
    for r in rows:
        matched = "name"
        if pattern.strip("%").lower() in (r.description or "").lower():
            matched = "description"
        results.append(
            SearchResultItem(
                id=r.id,
                title=r.name,
                matched_field=matched,
            )
        )
    return results


def _search_conversations(
    db: Session, pattern: str, limit: int
) -> list[SearchResultItem]:
    """Search conversations by title or by their messages' content."""
    results: list[SearchResultItem] = []
    seen_ids: set[str] = set()

    # Search by title first
    title_stmt = (
        select(Conversation)
        .where(Conversation.title.ilike(pattern, escape="\\"))
        .limit(limit)
    )
    title_rows = list(db.scalars(title_stmt).all())
    for r in title_rows:
        seen_ids.add(r.id)
        results.append(
            SearchResultItem(
                id=r.id,
                title=r.title or "",
                matched_field="title",
            )
        )

    # Search by message content — collect unique conversation_ids first,
    # then fetch all matching conversations in a single query (avoids N+1).
    remaining = limit - len(results)
    if remaining > 0:
        msg_stmt = (
            select(ConversationMessage.conversation_id)
            .where(ConversationMessage.content.ilike(pattern, escape="\\"))
            .distinct()
            .limit(remaining * 3)
        )
        msg_rows = list(db.scalars(msg_stmt).all())
        new_ids = [cid for cid in msg_rows if cid not in seen_ids]
        if new_ids:
            conv_stmt = select(Conversation).where(Conversation.id.in_(new_ids))
            convs = list(db.scalars(conv_stmt).all())
            for conv in convs:
                if len(results) >= limit:
                    break
                results.append(
                    SearchResultItem(
                        id=conv.id,
                        title=conv.title or "",
                        matched_field="message",
                    )
                )

    return results


def _escape_like(value: str) -> str:
    return value.replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=SearchDataResponse, dependencies=[Depends(require_permission("search", "read"))])
async def search(
    q: str = Query(..., min_length=2, max_length=200, description="Search keyword (min 2 chars)"),
    types: str | None = Query(None, description="Comma-separated entity types"),
    limit: int = Query(10, ge=1, le=50, description="Results per type"),
    db: Session = Depends(get_db),
):
    """Search across tasks, memories, skills, and conversations."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Search keyword must not be blank")

    if types:
        requested = {t.strip().lower() for t in types.split(",")}
        invalid = requested - VALID_TYPES
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid search types: {', '.join(sorted(invalid))}. Valid types: {', '.join(sorted(VALID_TYPES))}",
            )
    else:
        requested = VALID_TYPES

    safe_q = _escape_like(q)
    pattern = f"%{safe_q}%"

    def _query(db):
        results: dict[str, list[SearchResultItem]] = {}
        if "task" in requested:
            results["tasks"] = _search_tasks(db, pattern, limit)
        if "memory" in requested:
            results["memories"] = _search_memories(db, pattern, limit)
        if "skill" in requested:
            results["skills"] = _search_skills(db, pattern, limit)
        if "conversation" in requested:
            results["conversations"] = _search_conversations(db, pattern, limit)
        return results

    from packages.db.session import run_async
    results = await run_async(_query, bind_engine=db.bind)

    total = sum(len(v) for v in results.values())

    return {
        "success": True,
        "data": {
            "query": q,
            "results": {k: [r.model_dump() for r in v] for k, v in results.items()},
            "total": total,
        },
    }
