"""Task CRUD routes — create, list, detail, cancel, execute, retry, batch."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api_server.dependencies import CommonQueryParams, get_db, get_orchestrator, require_permission
from packages.agent_core.schemas import (
    AuditEventCreate,
    AuditEventResponse,
    PaginatedResponse,
    TaskAuditListResponse,
    TaskCreate,
    TaskDetailResponse,
    TaskExecutionResponse,
    TaskListResponse,
    TaskResponse,
    TaskStepResponse,
    TaskUpdate,
)
from packages.db.models import AuditEventType, Task, TaskStatus
from packages.db.pagination import paginate
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.task_repo import TaskRepository
from packages.db.session import run_async

router = APIRouter(dependencies=[Depends(require_permission("tasks", "read"))])


@router.post(
    "",
    response_model=TaskDetailResponse,
    status_code=201,
    summary="Create a task",
    description="Submit a new task with a goal description. The task starts in 'pending' status.",
    dependencies=[Depends(require_permission("tasks", "write"))],
)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    """Create a new task."""
    task = TaskRepository.create(db, body)

    AuditRepository.create(
        db,
        AuditEventCreate(
            task_id=task.id,
            edition=task.edition,
            event_type=AuditEventType.TASK_CREATED,
            detail={"goal": task.goal},
        ),
    )

    return TaskDetailResponse(data=TaskResponse.model_validate(task))


@router.get(
    "",
    response_model=TaskListResponse,
    summary="List tasks",
    description="Retrieve a paginated list of tasks with optional filtering by status and edition.",
)
def list_tasks(
    commons: CommonQueryParams = Depends(),
    status: TaskStatus | None = None,
    edition: str | None = None,
    db: Session = Depends(get_db),
):
    """List tasks with pagination and optional filters."""
    stmt = select(Task).order_by(Task.created_at.desc())
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if edition is not None:
        stmt = stmt.where(Task.edition == edition)

    result = paginate(db, stmt, page=commons.page, page_size=commons.page_size)

    return TaskListResponse(
        data=PaginatedResponse(
            total=result.total,
            items=[TaskResponse.model_validate(t) for t in result.items],
            page=result.page,
            page_size=result.page_size,
        )
    )


@router.get(
    "/{task_id}",
    response_model=TaskDetailResponse,
    summary="Get task detail",
    description="Retrieve a single task by ID, including all associated execution steps.",
)
def get_task(task_id: str, db: Session = Depends(get_db)):
    """Get task detail with all steps."""
    task = TaskRepository.get_by_id(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    resp = TaskResponse.model_validate(task)
    resp.steps = [TaskStepResponse.model_validate(s) for s in task.steps]

    return TaskDetailResponse(data=resp)


@router.post(
    "/{task_id}/execute",
    response_model=TaskExecutionResponse,
    summary="Execute a task",
    description="Run the full lifecycle for a pending task: planning, policy check, and step-by-step execution.",
    dependencies=[Depends(require_permission("tasks", "execute"))],
)
async def execute_task(task_id: str, db: Session = Depends(get_db)):
    """Execute a pending task: plan -> policy check -> execute."""

    updated = await run_async(
        TaskRepository.atomic_status_transition,
        task_id, TaskStatus.PENDING, TaskStatus.PLANNING,
    )
    if updated is None:
        task = await run_async(TaskRepository.get_by_id, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        raise HTTPException(
            status_code=409,
            detail=f"Task cannot be executed — current status: '{task.status.value}'",
        )

    orchestrator = get_orchestrator()
    edition = task.edition.value if hasattr(task.edition, "value") else task.edition

    from packages.executor.tools.base import ExecutionContext
    context = ExecutionContext(task_id=task_id, step_id="orchestrator", edition=edition)

    result = await orchestrator.run(
        db=db,
        goal=task.goal,
        edition=edition,
        user_id=task.user_id,
        context=context,
    )

    steps = await run_async(TaskRepository.get_steps, task_id)
    return TaskExecutionResponse(
        success=True,
        data={
            "task_id": task_id,
            "status": result.get("status", "unknown"),
            "plan": result.get("plan", {}),
            "results": result.get("results", []),
            "execution_success": result.get("success", False),
            "steps": [TaskStepResponse.model_validate(s).model_dump() for s in steps],
        },
    )


@router.post(
    "/{task_id}/cancel",
    response_model=TaskDetailResponse,
    summary="Cancel a task",
    description="Cancel a task that is currently in pending, planning, or awaiting-approval status.",
    dependencies=[Depends(require_permission("tasks", "write"))],
)
def cancel_task(task_id: str, db: Session = Depends(get_db)):
    """Cancel a pending or planning task."""
    task = TaskRepository.get_by_id(db, task_id, include_steps=False)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.PENDING, TaskStatus.PLANNING, TaskStatus.AWAITING_APPROVAL):
        raise HTTPException(status_code=400, detail=f"Cannot cancel task in status '{task.status.value}'")

    updated = TaskRepository.atomic_status_transition(db, task_id, task.status, TaskStatus.CANCELLED)
    if updated is None:
        raise HTTPException(status_code=409, detail="Task status changed concurrently — please retry")

    AuditRepository.create(
        db,
        AuditEventCreate(
            task_id=task_id,
            edition=updated.edition,
            event_type=AuditEventType.TASK_CANCELLED,
            detail={"previous_status": task.status.value},
        ),
    )

    return TaskDetailResponse(data=TaskResponse.model_validate(updated))


@router.get(
    "/{task_id}/steps",
    response_model=list[TaskStepResponse],
    summary="Get task steps",
    description="Retrieve all execution steps for a given task.",
)
def get_task_steps(task_id: str, db: Session = Depends(get_db)):
    """Get all steps for a task."""
    task = TaskRepository.get_by_id(db, task_id, include_steps=False)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    steps = TaskRepository.get_steps(db, task_id)
    return [TaskStepResponse.model_validate(s) for s in steps]


@router.post(
    "/{task_id}/retry",
    response_model=TaskDetailResponse,
    summary="Retry a task",
    description="Reset a failed or completed task back to pending so it can be re-executed.",
    dependencies=[Depends(require_permission("tasks", "write"))],
)
def retry_task(task_id: str, db: Session = Depends(get_db)):
    """Retry a failed or completed task by resetting it to pending."""
    task = TaskRepository.get_by_id(db, task_id, include_steps=False)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.FAILED, TaskStatus.COMPLETED):
        raise HTTPException(
            status_code=400,
            detail=f"Can only retry failed or completed tasks, current: '{task.status.value}'",
        )

    updated = TaskRepository.atomic_status_transition(db, task_id, task.status, TaskStatus.PENDING)
    if updated is None:
        raise HTTPException(status_code=409, detail="Task status changed concurrently — please retry")

    AuditRepository.create(
        db,
        AuditEventCreate(
            task_id=task_id,
            edition=updated.edition,
            event_type=AuditEventType.TASK_CREATED,
            detail={"retried": True, "previous_status": task.status.value},
        ),
    )

    return TaskDetailResponse(data=TaskResponse.model_validate(updated))


class BatchTaskCreate(BaseModel):
    tasks: list[TaskCreate]


class BatchTaskResponse(BaseModel):
    created: list[TaskResponse]
    count: int


@router.post(
    "/batch",
    response_model=BatchTaskResponse,
    status_code=201,
    summary="Batch create tasks",
    description="Create up to 50 tasks in a single request.",
    dependencies=[Depends(require_permission("tasks", "write"))],
)
def batch_create_tasks(body: BatchTaskCreate, db: Session = Depends(get_db)):
    """Create multiple tasks at once."""
    if not body.tasks:
        raise HTTPException(status_code=400, detail="Task list must not be empty")
    if len(body.tasks) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 tasks per batch")

    # Bulk insert tasks via add_all (single flush)
    tasks = TaskRepository.batch_create(db, body.tasks)
    # Bulk insert audit events via add_all (single flush)
    AuditRepository.batch_create(
        db,
        [
            AuditEventCreate(
                task_id=t.id,
                edition=t.edition,
                event_type=AuditEventType.TASK_CREATED,
                detail={"goal": t.goal, "source": "batch"},
            )
            for t in tasks
        ],
    )
    created = [TaskResponse.model_validate(t) for t in tasks]
    return BatchTaskResponse(created=created, count=len(created))


@router.get(
    "/{task_id}/audit",
    response_model=TaskAuditListResponse,
    summary="Get task audit trail",
    description="Retrieve all audit events associated with a specific task.",
)
def get_task_audit(task_id: str, db: Session = Depends(get_db)):
    """Get audit events for a task."""
    task = TaskRepository.get_by_id(db, task_id, include_steps=False)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    events = AuditRepository.list_by_task(db, task_id)
    return TaskAuditListResponse(
        data=[AuditEventResponse.model_validate(e) for e in events],
    )
