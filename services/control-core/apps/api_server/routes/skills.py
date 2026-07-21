"""Skill API routes — list, get, approve, disable, rollback."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api_server.dependencies import CommonQueryParams, get_db, require_permission
from packages.agent_core.schemas import (
    AuditEventCreate,
    ResponseBase,
    SkillDetailResponse,
    SkillListResponse,
    SkillResponse,
)
from packages.db.models import AuditEventType
from packages.db.repositories.audit_repo import AuditRepository
from packages.skills.skill_service import SkillService

router = APIRouter()


def _get_skill_service() -> SkillService:
    return SkillService()


@router.get(
    "",
    response_model=SkillListResponse,
    summary="List skills",
    description="Retrieve a paginated list of skills with optional filtering by edition and status.",
    dependencies=[Depends(require_permission("skills", "read"))],
)
def list_skills(
    commons: CommonQueryParams = Depends(),
    edition: str | None = Query(None, pattern="^(enterprise|personal)$"),
    status: str | None = Query(None, pattern="^(candidate|stable|disabled|deprecated)$"),
    db: Session = Depends(get_db),
):
    """List skills with optional filters."""
    service = _get_skill_service()
    skip = (commons.page - 1) * commons.page_size
    skills = service.list_skills(db, edition=edition, status=status, skip=skip, limit=commons.page_size)
    return SkillListResponse(data=[SkillResponse.model_validate(s) for s in skills])


@router.get(
    "/{skill_id}",
    response_model=SkillDetailResponse,
    summary="Get skill detail",
    description="Retrieve a single skill by its unique ID, including definition and usage statistics.",
    dependencies=[Depends(require_permission("skills", "read"))],
)
def get_skill(skill_id: str, db: Session = Depends(get_db)):
    """Get skill detail by ID."""
    service = _get_skill_service()
    skill = service.get_skill(db, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillDetailResponse(data=SkillResponse.model_validate(skill))


@router.post(
    "/{skill_id}/approve",
    response_model=ResponseBase,
    summary="Approve a skill",
    description="Promote a candidate skill to approved status, making it available for reuse.",
    dependencies=[Depends(require_permission("skills", "write"))],
)
def approve_skill(skill_id: str, db: Session = Depends(get_db)):
    """Approve a candidate skill."""
    service = _get_skill_service()
    skill = service.approve_skill(db, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found or not candidate")
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.SKILL_APPROVED,
        detail={"skill_id": skill_id, "skill_name": skill.name},
    ))
    return ResponseBase(message=f"Skill '{skill.name}' approved")


@router.post(
    "/{skill_id}/disable",
    response_model=ResponseBase,
    summary="Disable a skill",
    description="Soft-disable a skill so it is no longer available for task execution.",
    dependencies=[Depends(require_permission("skills", "write"))],
)
def disable_skill(skill_id: str, db: Session = Depends(get_db)):
    """Disable a skill."""
    service = _get_skill_service()
    skill = service.disable_skill(db, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.SKILL_DISABLED,
        detail={"skill_id": skill_id, "skill_name": skill.name},
    ))
    return ResponseBase(message=f"Skill '{skill.name}' disabled")


@router.post(
    "/{skill_id}/rollback",
    response_model=ResponseBase,
    summary="Roll back a skill",
    description="Restore a disabled skill back to stable status.",
    dependencies=[Depends(require_permission("skills", "write"))],
)
def rollback_skill(skill_id: str, db: Session = Depends(get_db)):
    """Roll back a disabled skill to stable."""
    service = _get_skill_service()
    skill = service.rollback_skill(db, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    AuditRepository.create(db, AuditEventCreate(
        event_type=AuditEventType.SKILL_ROLLEDBACK,
        detail={"skill_id": skill_id, "skill_name": skill.name},
    ))
    return ResponseBase(message=f"Skill '{skill.name}' rolled back to stable")
