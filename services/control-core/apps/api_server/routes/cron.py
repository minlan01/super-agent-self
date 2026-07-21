"""Cron API routes — CRUD for scheduled tasks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from apps.api_server.dependencies import require_permission
from packages.agent_core.schemas import ResponseBase
from packages.cron.jobs import CronJob, JobStore

router = APIRouter()

# Module-level job store (initialized on first use)
_job_store: JobStore | None = None


def _get_job_store() -> JobStore:
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store


# ── Schemas ────────────────────────────────────────────────────────────────


class CronJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    schedule: str = Field("every 60m", min_length=1, max_length=100)
    goal: str = Field(..., min_length=1, max_length=5000)
    edition: str = Field("enterprise", max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")
    enabled: bool = True
    context_from: list[str] = Field(default_factory=list, max_length=20)


class CronJobUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    schedule: str | None = Field(None, min_length=1, max_length=100)
    goal: str | None = Field(None, min_length=1, max_length=5000)
    enabled: bool | None = None
    context_from: list[str] | None = Field(None, max_length=20)


class CronJobResponse(BaseModel):
    id: str
    name: str
    schedule: str
    goal: str
    edition: str
    enabled: bool
    last_run_at: str | None = None
    next_run_at: str | None = None
    created_at: str | None = None
    context_from: list[str] = []
    last_output: str | None = None


def _job_to_response(job: CronJob) -> CronJobResponse:
    return CronJobResponse(
        id=job.id,
        name=job.name,
        schedule=job.schedule,
        goal=job.goal,
        edition=job.edition,
        enabled=job.enabled,
        last_run_at=job.last_run_at.isoformat() if job.last_run_at else None,
        next_run_at=job.next_run_at.isoformat() if job.next_run_at else None,
        created_at=job.created_at.isoformat() if job.created_at else None,
        context_from=job.context_from or [],
        last_output=job.last_output,
    )


class CronJobListResponse(BaseModel):
    success: bool = True
    data: list[CronJobResponse]
    count: int
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 0
    has_next: bool = False
    has_prev: bool = False


# ── Routes ─────────────────────────────────────────────────────────────────


@router.post("", response_model=CronJobResponse, status_code=201, dependencies=[Depends(require_permission("cron", "write"))])
def create_cron_job(body: CronJobCreate):
    """Create a new scheduled task."""
    store = _get_job_store()
    from packages.cron.jobs import _parse_schedule
    parsed = _parse_schedule(body.schedule)
    if parsed.get("type") == "unknown":
        raise HTTPException(
            status_code=400,
            detail="Invalid schedule format. Use 'every Ns/m/h/d', cron 'M H DoM Mon DoW', or ISO datetime",
        )
    is_valid, error = store.validate_context_from("", context_from=body.context_from)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)
    job = CronJob(
        name=body.name,
        schedule=body.schedule,
        goal=body.goal,
        edition=body.edition,
        enabled=body.enabled,
        context_from=body.context_from,
    )
    created = store.add_job(job)
    return _job_to_response(created)


@router.get("", response_model=CronJobListResponse, dependencies=[Depends(require_permission("cron", "read"))])
def list_cron_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List all scheduled tasks with pagination."""
    store = _get_job_store()
    all_jobs = store.list_jobs()
    total = len(all_jobs)
    start = (page - 1) * page_size
    end = start + page_size
    items = [_job_to_response(j) for j in all_jobs[start:end]]
    total_pages = max(1, (total + page_size - 1) // page_size)
    return CronJobListResponse(
        data=items, count=total,
        total=total, page=page, page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages, has_prev=page > 1,
    )


@router.get("/{job_id}", response_model=CronJobResponse, dependencies=[Depends(require_permission("cron", "read"))])
def get_cron_job(job_id: str):
    """Get a scheduled task by ID."""
    store = _get_job_store()
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return _job_to_response(job)


@router.put("/{job_id}", response_model=CronJobResponse, dependencies=[Depends(require_permission("cron", "write"))])
def update_cron_job(job_id: str, body: CronJobUpdate):
    """Update a scheduled task."""
    store = _get_job_store()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    if "schedule" in updates:
        from packages.cron.jobs import _parse_schedule
        parsed = _parse_schedule(updates["schedule"])
        if parsed.get("type") == "unknown":
            raise HTTPException(
                status_code=400,
                detail="Invalid schedule format. Use 'every Ns/m/h/d', cron 'M H DoM Mon DoW', or ISO datetime",
            )

    if "context_from" in updates:
        is_valid, error = store.validate_context_from(
            job_id, context_from=updates["context_from"]
        )
        if not is_valid:
            raise HTTPException(status_code=400, detail=error)

    job = store.update_job(job_id, **updates)
    if job is None:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return _job_to_response(job)


@router.delete("/{job_id}", response_model=ResponseBase, dependencies=[Depends(require_permission("cron", "admin"))])
def delete_cron_job(job_id: str):
    """Delete a scheduled task."""
    store = _get_job_store()
    deleted = store.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return {"success": True, "message": f"Cron job {job_id} deleted"}
