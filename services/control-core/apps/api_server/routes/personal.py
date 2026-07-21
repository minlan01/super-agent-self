"""Personal Edition API routes — reminders, context, preferences, editions."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_current_user, get_db, require_permission
from packages.agent_core.edition_manager import EditionManager
from packages.db.models import User
from packages.agent_core.schemas import (
    MemoryResponse,
    ReminderCreateResponse,
    ReminderListResponse,
    DailyContextResponse,
    PreferenceListResponse,
    PreferenceSaveResponse,
    EditionListResponse,
    ResponseBase,
)
from packages.personal_context.personal_context_service import PersonalContextService
from packages.personal_context.reminder_service import ReminderService

router = APIRouter()


# ── Request Schemas ──────────────────────────────────────────────────────────


class ReminderCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    expires_at: datetime | None = None


class PreferenceSave(BaseModel):
    key: str = Field(..., min_length=1, max_length=200)
    value: str = Field(..., min_length=1, max_length=10000)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_reminder_service() -> ReminderService:
    return ReminderService()


def _get_context_service() -> PersonalContextService:
    from packages.memory.memory_service import MemoryService
    from packages.memory.summarizer import MemorySummarizer
    memory_service = MemoryService(summarizer=MemorySummarizer())
    return PersonalContextService(memory_service=memory_service)


def _get_edition_manager() -> EditionManager:
    return EditionManager()


# ── Reminders ────────────────────────────────────────────────────────────────


@router.post("/reminders", response_model=ReminderCreateResponse, status_code=201, dependencies=[Depends(require_permission("tasks", "write"))])
def create_reminder(
    body: ReminderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new reminder."""
    svc = _get_reminder_service()
    reminder = svc.create_reminder(
        db,
        title=body.title,
        description=body.description,
        expires_at=body.expires_at,
    )
    return {
        "success": True,
        "message": "Reminder created",
        "data": MemoryResponse.model_validate(reminder).model_dump(),
    }


@router.get("/reminders", response_model=ReminderListResponse, dependencies=[Depends(require_permission("tasks", "read"))])
def list_reminders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List active (non-expired, non-dismissed) reminders."""
    svc = _get_reminder_service()
    reminders = svc.list_active(db)
    return {
        "success": True,
        "data": [MemoryResponse.model_validate(r).model_dump() for r in reminders],
    }


@router.post("/reminders/{reminder_id}/dismiss", response_model=ResponseBase, dependencies=[Depends(require_permission("tasks", "write"))])
def dismiss_reminder(
    reminder_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dismiss (deactivate) a reminder."""
    svc = _get_reminder_service()
    reminder = svc.dismiss(db, reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {
        "success": True,
        "message": "Reminder dismissed",
        "data": MemoryResponse.model_validate(reminder).model_dump(),
    }


# ── Daily Context ────────────────────────────────────────────────────────────


@router.get("/context", response_model=DailyContextResponse, dependencies=[Depends(require_permission("tasks", "read"))])
def get_daily_context(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get today's daily context including reminders and preference count."""
    svc = _get_context_service()
    context = svc.get_daily_context(db)
    return {"success": True, "data": context}


# ── Preferences ──────────────────────────────────────────────────────────────


@router.get("/preferences", response_model=PreferenceListResponse, dependencies=[Depends(require_permission("tasks", "read"))])
def get_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all active user preferences."""
    svc = _get_context_service()
    prefs = svc.get_user_preferences(db)
    return {"success": True, "data": prefs}


@router.post("/preferences", response_model=PreferenceSaveResponse, dependencies=[Depends(require_permission("tasks", "write"))])
async def save_preference(
    body: PreferenceSave,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a user preference."""
    svc = _get_context_service()
    result = await svc.save_preference(db, key=body.key, value=body.value)
    validated = MemoryResponse.model_validate(result).model_dump() if result else None
    return {
        "success": True,
        "message": "Preference saved",
        "data": validated,
    }


# ── Editions (Personal-scoped) ──────────────────────────────────────────────


@router.get("/editions", response_model=EditionListResponse, dependencies=[Depends(require_permission("tasks", "read"))])
def list_editions(current_user: User = Depends(get_current_user)):
    """List available editions."""
    mgr = _get_edition_manager()
    editions = mgr.list_editions()
    edition_details = [
        {
            "edition": e,
            "name": mgr.get_name(e),
            "description": mgr.get_description(e),
        }
        for e in editions
    ]
    return {"success": True, "data": edition_details}
