"""Skill Marketplace API routes — browse, subscribe, rate, and promote skills."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_current_user, get_db, require_permission
from packages.agent_core.schemas import (
    MarketplaceBrowseResponse,
    PromoteSkillResponse,
    RateSkillResponse,
    ResponseBase,
    SubscribeResponse,
)
from packages.db.models import User
from packages.skills.marketplace import SkillMarketplace

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_error(e: Exception) -> str:
    """Return user-safe error message. Only expose ValueError details."""
    if isinstance(e, ValueError):
        return str(e)
    logger.warning("Marketplace error: %s", e)
    return "Operation failed"


# ── Request schemas ──────────────────────────────────────────────────────


class SubscribeRequest(BaseModel):
    skill_id: str = Field(..., min_length=1, max_length=200)


class RateRequest(BaseModel):
    skill_id: str = Field(..., min_length=1, max_length=200)
    rating: int = Field(..., ge=1, le=5)
    review: str | None = Field(None, max_length=2000)


class PromoteRequest(BaseModel):
    skill_id: str = Field(..., min_length=1, max_length=200)
    source_edition: str = Field(..., max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")
    target_edition: str = Field(..., max_length=50, pattern=r"^[a-zA-Z0-9_\-]+$")


class ReviewPromotionRequest(BaseModel):
    approved: bool
    note: str | None = Field(None, max_length=2000)


# ── Browse ───────────────────────────────────────────────────────────────


@router.get(
    "/browse",
    response_model=MarketplaceBrowseResponse,
    summary="Browse marketplace skills",
    dependencies=[Depends(require_permission("marketplace", "read"))],
    description=(
        "Browse published skills with optional filters "
        "for edition, category, and rating."
    ),
)
def browse_skills(
    edition: str | None = None,
    category: str | None = None,
    min_rating: float = 0.0,
    sort_by: str = Query("rating", pattern="^(rating|name|created_at|total_runs)$"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
):
    mp = SkillMarketplace()
    offset = (page - 1) * page_size
    results = mp.browse(
        db, edition=edition, category=category, min_rating=min_rating,
        sort_by=sort_by, limit=page_size, offset=offset,
    )
    return {"success": True, "data": results, "page": page, "page_size": page_size}


# ── Subscription ─────────────────────────────────────────────────────────


@router.post(
    "/subscribe",
    response_model=SubscribeResponse,
    summary="Subscribe to a skill",
    dependencies=[Depends(require_permission("marketplace", "write"))],
    description="Subscribe the current user to a skill.",
)
def subscribe_skill(
    req: SubscribeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mp = SkillMarketplace()
    user_id = current_user.id if current_user else "default"
    try:
        sub = mp.subscribe(db, user_id=user_id, skill_id=req.skill_id)
        return {
            "success": True,
            "data": {"subscription_id": sub.id, "skill_id": sub.skill_id},
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=_safe_error(e))


@router.post(
    "/unsubscribe/{skill_id}",
    response_model=ResponseBase,
    summary="Unsubscribe from a skill",
    dependencies=[Depends(require_permission("marketplace", "write"))],
)
def unsubscribe_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mp = SkillMarketplace()
    user_id = current_user.id if current_user else "default"
    ok = mp.unsubscribe(db, user_id=user_id, skill_id=skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Active subscription not found")
    return {"success": True, "message": "Unsubscribed"}


@router.get(
    "/subscriptions",
    response_model=MarketplaceBrowseResponse,
    summary="List user subscriptions",
    dependencies=[Depends(require_permission("marketplace", "read"))],
)
def list_subscriptions(
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mp = SkillMarketplace()
    user_id = current_user.id if current_user else "default"
    results = mp.list_subscriptions(db, user_id=user_id, active_only=active_only)
    return {"success": True, "data": results}


# ── Rating ───────────────────────────────────────────────────────────────


@router.post(
    "/rate",
    response_model=RateSkillResponse,
    summary="Rate a skill",
    dependencies=[Depends(require_permission("marketplace", "write"))],
    description="Rate a skill 1-5 stars with an optional review.",
)
def rate_skill(
    req: RateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mp = SkillMarketplace()
    user_id = current_user.id if current_user else "default"
    try:
        sr = mp.rate(
            db, user_id=user_id,
            skill_id=req.skill_id, rating=req.rating, review=req.review,
        )
        return {
            "success": True,
            "data": {"rating_id": sr.id, "rating": sr.rating},
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_safe_error(e))


@router.get(
    "/{skill_id}/ratings",
    response_model=MarketplaceBrowseResponse,
    summary="Get skill ratings",
    dependencies=[Depends(require_permission("marketplace", "read"))],
)
def get_skill_ratings(
    skill_id: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    mp = SkillMarketplace()
    results = mp.get_ratings(db, skill_id, limit=limit)
    return {"success": True, "data": results}


# ── Cross-Edition Promotion ──────────────────────────────────────────────


@router.post(
    "/promote",
    response_model=PromoteSkillResponse,
    summary="Promote a skill across editions",
    dependencies=[Depends(require_permission("marketplace", "write"))],
    description="Submit a skill for cross-edition promotion.",
)
def promote_skill(
    req: PromoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mp = SkillMarketplace()
    try:
        promo = mp.promote(
            db, skill_id=req.skill_id,
            source_edition=req.source_edition,
            target_edition=req.target_edition,
        )
        return {
            "success": True,
            "data": {"promotion_id": promo.id, "status": promo.status},
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_safe_error(e))


@router.post(
    "/promotions/{promotion_id}/review",
    response_model=PromoteSkillResponse,
    summary="Review a promotion request",
    description="Approve or reject a skill promotion request. Admin only.",
    dependencies=[Depends(require_permission("marketplace", "admin"))],
)
def review_promotion(
    promotion_id: str,
    req: ReviewPromotionRequest,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_user),
):
    mp = SkillMarketplace()
    try:
        promo = mp.review_promotion(
            db, promotion_id=promotion_id,
            approved=req.approved,
            reviewer=admin_user.username,
            note=req.note,
        )
        if promo is None:
            raise HTTPException(status_code=404, detail="Promotion not found")
        return {
            "success": True,
            "data": {"promotion_id": promo.id, "status": promo.status},
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_safe_error(e))


@router.get(
    "/promotions",
    response_model=MarketplaceBrowseResponse,
    summary="List promotion requests",
    dependencies=[Depends(require_permission("marketplace", "read"))],
)
def list_promotions(
    status: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    mp = SkillMarketplace()
    results = mp.list_promotions(db, status=status, limit=limit)
    return {"success": True, "data": results}
