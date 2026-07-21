"""Memory API routes — search, list, get, disable, delete."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api_server.dependencies import CommonQueryParams, get_db, require_permission
from packages.agent_core.schemas import (
    MemoryDetailResponse,
    MemoryListResponse,
    MemoryResponse,
    ResponseBase,
)
from packages.memory.memory_service import MemoryService

router = APIRouter()


def _get_memory_service() -> MemoryService:
    from packages.memory.summarizer import MemorySummarizer
    return MemoryService(summarizer=MemorySummarizer())


@router.get(
    "/search",
    response_model=MemoryListResponse,
    summary="Search memories",
    description="Search memories by keyword, type, or source task ID.",
    dependencies=[Depends(require_permission("memory", "read"))],
)
def search_memories(
    keyword: str | None = Query(None, max_length=200),
    memory_type: str | None = None,
    source_task_id: str | None = None,
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Search memories by keyword, type, or source task."""
    service = _get_memory_service()
    memories = service.search(
        db, keyword=keyword, memory_type=memory_type,
        source_task_id=source_task_id, limit=limit,
    )
    return MemoryListResponse(data=[MemoryResponse.model_validate(m) for m in memories])


@router.get(
    "",
    response_model=MemoryListResponse,
    summary="List memories",
    description="Retrieve a paginated list of memories with optional type and active-status filtering.",
    dependencies=[Depends(require_permission("memory", "read"))],
)
def list_memories(
    commons: CommonQueryParams = Depends(),
    memory_type: str | None = None,
    is_active: bool = True,
    db: Session = Depends(get_db),
):
    """List memories with pagination."""
    service = _get_memory_service()
    skip = (commons.page - 1) * commons.page_size
    memories = service.list_memories(
        db, memory_type=memory_type, is_active=is_active,
        skip=skip, limit=commons.page_size,
    )
    return MemoryListResponse(data=[MemoryResponse.model_validate(m) for m in memories])


@router.get(
    "/{memory_id}",
    response_model=MemoryDetailResponse,
    summary="Get memory detail",
    description="Retrieve a single memory entry by its unique ID.",
    dependencies=[Depends(require_permission("memory", "read"))],
)
def get_memory(memory_id: str, db: Session = Depends(get_db)):
    """Get a single memory by ID."""
    service = _get_memory_service()
    memory = service.get_memory(db, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryDetailResponse(data=MemoryResponse.model_validate(memory))


@router.post("/{memory_id}/disable", response_model=ResponseBase, dependencies=[Depends(require_permission("memory", "write"))])
def disable_memory(memory_id: str, db: Session = Depends(get_db)):
    """Disable a memory (soft delete)."""
    service = _get_memory_service()
    memory = service.disable_memory(db, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ResponseBase(message="Memory disabled")


@router.delete("/{memory_id}", response_model=ResponseBase, dependencies=[Depends(require_permission("memory", "write"))])
def delete_memory(memory_id: str, db: Session = Depends(get_db)):
    """Permanently delete a memory."""
    service = _get_memory_service()
    if not service.delete_memory(db, memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return ResponseBase(message="Memory deleted")
