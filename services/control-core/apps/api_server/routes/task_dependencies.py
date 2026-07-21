"""Task dependency routes — add, remove, list dependencies; execution order; DAG graph."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_db, require_permission
from packages.agent_core.schemas import AgentDataResponse, ResponseBase, TaskExecutionResponse
from packages.db.models import Task, TaskDependency
from packages.db.repositories.task_dependency_repo import TaskDependencyRepository
from packages.db.repositories.task_repo import TaskRepository

router = APIRouter()


# ── Request / Response schemas ──────────────────────────────────────────────


class DependencyCreate(BaseModel):
    depends_on_id: str = Field(..., min_length=1, max_length=200)


class DependencyResponse(BaseModel):
    id: str
    task_id: str
    depends_on_id: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)


class ExecutionOrderRequest(BaseModel):
    task_ids: list[str] = Field(..., max_length=100)


class ExecutionOrderResponse(BaseModel):
    task_ids: list[str]


def _dep_to_response(dep: TaskDependency) -> dict:
    return {
        "id": dep.id,
        "task_id": dep.task_id,
        "depends_on_id": dep.depends_on_id,
        "created_at": dep.created_at.isoformat() if dep.created_at else None,
    }


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/{task_id}/dependencies", response_model=TaskExecutionResponse, status_code=201, dependencies=[Depends(require_permission("tasks", "write"))])
def add_dependency(
    task_id: str,
    body: DependencyCreate,
    db: Session = Depends(get_db),
):
    """Add a dependency: task_id depends on depends_on_id."""
    # Validate both tasks exist
    task = TaskRepository.get_by_id(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    dep_task = TaskRepository.get_by_id(db, body.depends_on_id)
    if dep_task is None:
        raise HTTPException(status_code=404, detail="Dependency task not found")

    # Self-dependency check
    if task_id == body.depends_on_id:
        raise HTTPException(status_code=400, detail="A task cannot depend on itself")

    # Cycle detection
    would_cycle = TaskDependencyRepository.detect_cycle(db, task_id, body.depends_on_id)
    if would_cycle:
        raise HTTPException(
            status_code=400,
            detail="Adding this dependency would create a cycle",
        )

    dep = TaskDependencyRepository.add_dependency(db, task_id, body.depends_on_id)
    return {"success": True, "data": _dep_to_response(dep)}


@router.delete("/{task_id}/dependencies/{depends_on_id}", response_model=ResponseBase, dependencies=[Depends(require_permission("tasks", "write"))])
def remove_dependency(
    task_id: str,
    depends_on_id: str,
    db: Session = Depends(get_db),
):
    """Remove a dependency edge."""
    removed = TaskDependencyRepository.remove_dependency(db, task_id, depends_on_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Dependency not found")
    return {"success": True, "message": "Dependency removed"}


@router.get("/{task_id}/dependencies", response_model=AgentDataResponse, dependencies=[Depends(require_permission("tasks", "read"))])
def list_dependencies(
    task_id: str,
    db: Session = Depends(get_db),
):
    """List all tasks that task_id depends on."""
    deps = TaskDependencyRepository.get_dependencies(db, task_id)
    return {"success": True, "data": [_dep_to_response(d) for d in deps]}


@router.get("/{task_id}/dependents", response_model=AgentDataResponse, dependencies=[Depends(require_permission("tasks", "read"))])
def list_dependents(
    task_id: str,
    db: Session = Depends(get_db),
):
    """List all tasks that depend on task_id."""
    deps = TaskDependencyRepository.get_dependents(db, task_id)
    return {"success": True, "data": [_dep_to_response(d) for d in deps]}


@router.post("/execution-order", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("tasks", "read"))])
def execution_order(
    body: ExecutionOrderRequest,
    db: Session = Depends(get_db),
):
    """Get topological execution order for a set of tasks."""
    if not body.task_ids:
        return {"success": True, "data": {"task_ids": []}}

    order = TaskDependencyRepository.get_execution_order(db, body.task_ids)
    return {"success": True, "data": {"task_ids": order}}


@router.get("/dag", response_model=TaskExecutionResponse, dependencies=[Depends(require_permission("tasks", "read"))])
def get_dag_graph(db: Session = Depends(get_db)):
    """Return full DAG graph: all tasks as nodes, all dependencies as edges."""
    tasks = list(db.scalars(select(Task)).all())
    deps = list(db.scalars(select(TaskDependency)).all())

    nodes = [
        {
            "id": t.id,
            "name": t.goal[:40] + ("..." if len(t.goal) > 40 else ""),
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "risk_level": t.risk_level.value if t.risk_level and hasattr(t.risk_level, "value") else (str(t.risk_level) if t.risk_level else None),
        }
        for t in tasks
    ]

    edges = [
        {"source": d.depends_on_id, "target": d.task_id}
        for d in deps
    ]

    return {"success": True, "data": {"nodes": nodes, "edges": edges}}
