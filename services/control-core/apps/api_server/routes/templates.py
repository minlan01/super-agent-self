"""Task template routes — CRUD, apply template to create tasks."""

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api_server.dependencies import CommonQueryParams, get_db, require_permission
from packages.agent_core.schemas import PaginatedResponse, ResponseBase, TaskCreate
from packages.db.models import Edition
from packages.db.repositories.task_repo import TaskRepository
from packages.db.repositories.template_repo import TemplateRepository

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    goal_template: str = Field(..., min_length=1, max_length=10000)
    description: str | None = Field(None, max_length=2000)
    edition: Edition = Edition.ENTERPRISE
    parameters: dict[str, Any] | None = None


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    goal_template: str | None = Field(None, min_length=1, max_length=10000)
    description: str | None = Field(None, max_length=2000)
    edition: Edition | None = None
    parameters: dict[str, Any] | None = None


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    goal_template: str
    edition: Edition
    is_builtin: bool
    parameters: dict[str, Any] | None = None
    usage_count: int
    created_at: Any
    updated_at: Any

    model_config = {"from_attributes": True}


class TemplateListResponse(ResponseBase):
    data: PaginatedResponse


class TemplateDetailResponse(ResponseBase):
    data: TemplateResponse


class ApplyTemplateRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    user_id: str = Field(..., min_length=1, max_length=200)


class ApplyTemplateResponse(ResponseBase):
    data: dict


# ── Helpers ───────────────────────────────────────────────────────────────


def _substitute_placeholders(goal_template: str, params: dict[str, str]) -> str:
    """Replace {param_name} placeholders in goal_template with actual values.

    Only replaces placeholders that were declared in the template.
    Param keys must be word-characters only; values are truncated to 500 chars.
    """
    import re as _re
    result = goal_template
    allowed = set(_re.findall(r"\{(\w+)\}", goal_template))
    for key, value in params.items():
        if not _re.match(r"^\w+$", key):
            continue
        if key not in allowed:
            continue
        safe_value = str(value)[:500]
        result = result.replace(f"{{{key}}}", safe_value)
    return result


def _extract_placeholders(goal_template: str) -> list[str]:
    """Extract all {param_name} placeholders from goal_template."""
    return re.findall(r"\{(\w+)\}", goal_template)


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("", response_model=TemplateListResponse, dependencies=[Depends(require_permission("templates", "read"))])
def list_templates(
    commons: CommonQueryParams = Depends(),
    edition: str | None = None,
    db: Session = Depends(get_db),
):
    """List templates with pagination and optional edition filter."""
    skip = (commons.page - 1) * commons.page_size
    templates = TemplateRepository.list_templates(db, edition=edition, skip=skip, limit=commons.page_size)
    total = TemplateRepository.count(db, edition=edition)

    items = [TemplateResponse.model_validate(t) for t in templates]
    return TemplateListResponse(
        data=PaginatedResponse(
            total=total,
            items=items,
            page=commons.page,
            page_size=commons.page_size,
        )
    )


@router.get("/{template_id}", response_model=TemplateDetailResponse, dependencies=[Depends(require_permission("templates", "read"))])
def get_template(template_id: str, db: Session = Depends(get_db)):
    """Get template detail."""
    template = TemplateRepository.get_by_id(db, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return TemplateDetailResponse(data=TemplateResponse.model_validate(template))


@router.post("", response_model=TemplateDetailResponse, status_code=201, dependencies=[Depends(require_permission("templates", "write"))])
def create_template(body: TemplateCreate, db: Session = Depends(get_db)):
    """Create a new template."""
    template = TemplateRepository.create(
        db,
        name=body.name,
        goal_template=body.goal_template,
        edition=body.edition,
        description=body.description,
        parameters=body.parameters,
    )
    return TemplateDetailResponse(data=TemplateResponse.model_validate(template))


@router.put("/{template_id}", response_model=TemplateDetailResponse, dependencies=[Depends(require_permission("templates", "write"))])
def update_template(template_id: str, body: TemplateUpdate, db: Session = Depends(get_db)):
    """Update a template (builtin templates cannot be modified)."""
    template = TemplateRepository.get_by_id(db, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.is_builtin:
        raise HTTPException(status_code=400, detail="Cannot modify builtin templates")

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        return TemplateDetailResponse(data=TemplateResponse.model_validate(template))

    updated = TemplateRepository.update(db, template_id, **update_data)
    return TemplateDetailResponse(data=TemplateResponse.model_validate(updated))


@router.delete("/{template_id}", response_model=ResponseBase, dependencies=[Depends(require_permission("templates", "write"))])
def delete_template(template_id: str, db: Session = Depends(get_db)):
    """Delete a template (builtin templates cannot be deleted)."""
    template = TemplateRepository.get_by_id(db, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.is_builtin:
        raise HTTPException(status_code=400, detail="Cannot delete builtin templates")

    TemplateRepository.delete(db, template_id)
    return {"success": True, "message": "Template deleted"}


@router.post("/{template_id}/apply", response_model=ApplyTemplateResponse, dependencies=[Depends(require_permission("tasks", "write"))])
def apply_template(template_id: str, body: ApplyTemplateRequest, db: Session = Depends(get_db)):
    """Apply template: substitute params into goal_template and create a task."""
    template = TemplateRepository.get_by_id(db, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Validate required parameters
    params_meta = template.parameters or {}
    fields = params_meta.get("fields", [])
    required_fields = [f["name"] for f in fields if f.get("required", False)]

    for field_name in required_fields:
        if field_name not in body.params or not body.params[field_name]:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required parameter: {field_name}",
            )

    # Substitute placeholders
    goal = _substitute_placeholders(template.goal_template, body.params)

    # Create task
    task = TaskRepository.create(
        db,
        TaskCreate(
            goal=goal,
            edition=template.edition,
            user_id=body.user_id,
        ),
    )

    # Increment usage count
    TemplateRepository.increment_usage(db, template_id)

    return ApplyTemplateResponse(
        data={
            "task_id": task.id,
            "goal": task.goal,
            "status": task.status.value,
            "template_id": template_id,
        },
    )


# ── Builtin seed ──────────────────────────────────────────────────────────


def seed_builtin_templates(db: Session) -> None:
    """Seed builtin templates if they do not already exist."""
    existing = TemplateRepository.list_templates(db, limit=1000)
    existing_names = {t.name for t in existing if t.is_builtin}

    builtins = [
        {
            "name": "Web Search",
            "description": "Search the web for a given query",
            "goal_template": "Search the web for {query}",
            "parameters": {
                "fields": [
                    {"name": "query", "label": "Search Query", "required": True},
                ],
            },
        },
        {
            "name": "Document Summary",
            "description": "Read and summarize a document at a given URL",
            "goal_template": "Read and summarize the document at {url}",
            "parameters": {
                "fields": [
                    {"name": "url", "label": "Document URL", "required": True},
                ],
            },
        },
        {
            "name": "Data Extraction",
            "description": "Extract specified fields from a URL",
            "goal_template": "Extract {fields} from {url}",
            "parameters": {
                "fields": [
                    {"name": "fields", "label": "Fields to Extract", "required": True},
                    {"name": "url", "label": "Source URL", "required": True},
                ],
            },
        },
        {
            "name": "Code Review",
            "description": "Review code in a file path for specific concerns",
            "goal_template": "Review the code in {path} for {concerns}",
            "parameters": {
                "fields": [
                    {"name": "path", "label": "File Path", "required": True},
                    {"name": "concerns", "label": "Concerns", "required": True},
                ],
            },
        },
    ]

    for b in builtins:
        if b["name"] not in existing_names:
            TemplateRepository.create(
                db,
                name=b["name"],
                goal_template=b["goal_template"],
                description=b["description"],
                parameters=b["parameters"],
                is_builtin=True,
            )
