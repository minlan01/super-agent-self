"""Skill Marketplace — user-scoped skill discovery, subscription, rating, and cross-edition sharing.

Provides:
- Browse/search published skills
- Subscribe/unsubscribe to skills (per-user)
- Rate and review skills
- Promote skills across editions (e.g., personal → enterprise)
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.db.models import (
    Edition,
    PromotionStatus,
    Skill,
    SkillPromotion,
    SkillRating,
    SkillStatus,
    SkillSubscription,
)

logger = logging.getLogger(__name__)


class SkillMarketplace:
    """User-scoped skill marketplace for discovery, subscription, and rating."""

    # ── Browse & Search ──────────────────────────────────────────────────

    @staticmethod
    def browse(
        db: Session,
        *,
        edition: str | None = None,
        category: str | None = None,
        min_rating: float = 0.0,
        sort_by: str = "rating",  # "rating" | "newest" | "popular"
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Browse published (stable) skills with optional filters."""
        stmt = select(Skill).where(Skill.status == SkillStatus.STABLE)

        if edition:
            stmt = stmt.where(Skill.edition == edition)

        if category:
            safe_category = category.replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{safe_category}%"
            stmt = stmt.where(
                Skill.definition["tags"].as_string().ilike(pattern, escape="\\")
            )

        # Join with average rating
        avg_rating = (
            select(SkillRating.skill_id, func.avg(SkillRating.rating).label("avg_rating"))
            .group_by(SkillRating.skill_id)
            .subquery()
        )

        stmt = stmt.outerjoin(avg_rating, Skill.id == avg_rating.c.skill_id)

        if min_rating > 0:
            stmt = stmt.where(avg_rating.c.avg_rating >= min_rating)

        if sort_by == "newest":
            stmt = stmt.order_by(Skill.created_at.desc())
        elif sort_by == "popular":
            stmt = stmt.order_by(Skill.total_runs.desc())
        else:  # rating (default)
            stmt = stmt.order_by(avg_rating.c.avg_rating.desc().nulls_last())

        stmt = stmt.offset(offset).limit(limit)
        skills = db.scalars(stmt).all()

        if not skills:
            return []

        skill_ids = [s.id for s in skills]

        sub_counts = dict(db.execute(
            select(SkillSubscription.skill_id, func.count())
            .where(
                SkillSubscription.skill_id.in_(skill_ids),
                SkillSubscription.is_active.is_(True),
            )
            .group_by(SkillSubscription.skill_id)
        ).all())

        avg_ratings = dict(db.execute(
            select(SkillRating.skill_id, func.avg(SkillRating.rating))
            .where(SkillRating.skill_id.in_(skill_ids))
            .group_by(SkillRating.skill_id)
        ).all())

        results: list[dict[str, Any]] = []
        for s in skills:
            avg = avg_ratings.get(s.id)
            results.append({
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "edition": s.edition.value if hasattr(s.edition, "value") else s.edition,
                "version": s.version,
                "success_rate": s.success_rate,
                "total_runs": s.total_runs,
                "avg_rating": round(avg, 2) if avg else None,
                "subscription_count": sub_counts.get(s.id, 0),
            })

        return results

    # ── Subscription ─────────────────────────────────────────────────────

    @staticmethod
    def subscribe(db: Session, user_id: str, skill_id: str) -> SkillSubscription:
        """Subscribe a user to a skill. Creates or reactivates."""
        skill = db.get(Skill, skill_id)
        if skill is None:
            raise ValueError(f"Skill '{skill_id}' not found")

        existing = db.scalar(
            select(SkillSubscription).where(
                SkillSubscription.user_id == user_id,
                SkillSubscription.skill_id == skill_id,
            )
        )
        if existing:
            existing.is_active = True
            db.flush()
            db.refresh(existing)
            return existing

        sub = SkillSubscription(user_id=user_id, skill_id=skill_id, is_active=True)
        db.add(sub)
        db.flush()
        db.refresh(sub)
        return sub

    @staticmethod
    def unsubscribe(db: Session, user_id: str, skill_id: str) -> bool:
        """Unsubscribe a user from a skill (soft delete)."""
        sub = db.scalar(
            select(SkillSubscription).where(
                SkillSubscription.user_id == user_id,
                SkillSubscription.skill_id == skill_id,
                SkillSubscription.is_active.is_(True),
            )
        )
        if not sub:
            return False
        sub.is_active = False
        db.flush()
        return True

    @staticmethod
    def list_subscriptions(
        db: Session, user_id: str, *, active_only: bool = True
    ) -> list[dict[str, Any]]:
        """List skills a user is subscribed to."""
        stmt = select(SkillSubscription).where(SkillSubscription.user_id == user_id)
        if active_only:
            stmt = stmt.where(SkillSubscription.is_active.is_(True))

        subs = db.scalars(stmt).all()
        if not subs:
            return []

        skill_ids = list({sub.skill_id for sub in subs})
        skills = db.scalars(
            select(Skill).where(Skill.id.in_(skill_ids))
        ).all()
        skill_map = {s.id: s for s in skills}

        results = []
        for sub in subs:
            skill = skill_map.get(sub.skill_id)
            if skill:
                results.append({
                    "subscription_id": sub.id,
                    "skill_id": skill.id,
                    "skill_name": skill.name,
                    "description": skill.description,
                    "edition": (
                        skill.edition.value
                        if hasattr(skill.edition, "value") else skill.edition
                    ),
                    "is_active": sub.is_active,
                })
        return results

    # ── Rating ───────────────────────────────────────────────────────────

    @staticmethod
    def rate(
        db: Session, user_id: str, skill_id: str, rating: int, review: str | None = None
    ) -> SkillRating:
        """Rate a skill (1-5 stars). Updates existing rating if present."""
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")

        skill = db.get(Skill, skill_id)
        if skill is None:
            raise ValueError(f"Skill '{skill_id}' not found")

        existing = db.scalar(
            select(SkillRating).where(
                SkillRating.user_id == user_id,
                SkillRating.skill_id == skill_id,
            )
        )
        if existing:
            existing.rating = rating
            existing.review = review
            db.flush()
            db.refresh(existing)
            return existing

        sr = SkillRating(user_id=user_id, skill_id=skill_id, rating=rating, review=review)
        db.add(sr)
        db.flush()
        db.refresh(sr)
        return sr

    @staticmethod
    def get_ratings(db: Session, skill_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get ratings for a skill."""
        ratings = db.scalars(
            select(SkillRating)
            .where(SkillRating.skill_id == skill_id)
            .order_by(SkillRating.created_at.desc())
            .limit(limit)
        ).all()

        return [
            {
                "user_id": r.user_id,
                "rating": r.rating,
                "review": r.review,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in ratings
        ]

    # ── Cross-Edition Promotion (P2-G) ──────────────────────────────────

    @staticmethod
    def promote(
        db: Session,
        skill_id: str,
        source_edition: str,
        target_edition: str,
    ) -> SkillPromotion:
        """Submit a skill for cross-edition promotion.

        Creates a pending promotion request. An admin must approve it
        before the skill becomes available in the target edition.
        """
        skill = db.get(Skill, skill_id)
        if skill is None:
            raise ValueError(f"Skill '{skill_id}' not found")

        if skill.status != SkillStatus.STABLE:
            raise ValueError("Only stable skills can be promoted")

        source = Edition(source_edition)
        target = Edition(target_edition)

        if source == target:
            raise ValueError("Source and target editions must differ")

        # Check for existing pending promotion
        existing = db.scalar(
            select(SkillPromotion).where(
                SkillPromotion.skill_id == skill_id,
                SkillPromotion.target_edition == target,
                SkillPromotion.status == PromotionStatus.PENDING,
            )
        )
        if existing:
            return existing

        promo = SkillPromotion(
            skill_id=skill_id,
            source_edition=source,
            target_edition=target,
            status=PromotionStatus.PENDING,
        )
        db.add(promo)
        db.flush()
        db.refresh(promo)
        logger.info(
            "Skill '%s' promotion submitted: %s → %s",
            skill.name, source_edition, target_edition,
        )
        return promo

    @staticmethod
    def review_promotion(
        db: Session,
        promotion_id: str,
        approved: bool,
        reviewer: str = "admin",
        note: str | None = None,
    ) -> SkillPromotion | None:
        """Approve or reject a skill promotion request."""
        promo = db.get(SkillPromotion, promotion_id)
        if promo is None:
            return None

        if promo.status != PromotionStatus.PENDING:
            raise ValueError(f"Promotion already {promo.status.value}")

        promo.status = (
            PromotionStatus.APPROVED if approved else PromotionStatus.REJECTED
        )
        promo.reviewed_by = reviewer
        promo.review_note = note
        db.flush()
        db.refresh(promo)

        if approved:
            # Create a copy of the skill in the target edition
            source_skill = db.get(Skill, promo.skill_id)
            if source_skill:
                new_skill = Skill(
                    name=source_skill.name,
                    definition=source_skill.definition,
                    description=source_skill.description,
                    edition=promo.target_edition,
                    status=SkillStatus.CANDIDATE,
                    version=1,
                    source_task_id=source_skill.source_task_id,
                )
                db.add(new_skill)
                db.flush()
                logger.info(
                    "Skill '%s' promoted to %s edition as new skill",
                    source_skill.name,
                    promo.target_edition.value,
                )

        return promo

    @staticmethod
    def list_promotions(
        db: Session,
        status: PromotionStatus | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List promotion requests, optionally filtered by status."""
        stmt = select(SkillPromotion)
        if status:
            stmt = stmt.where(SkillPromotion.status == status)
        stmt = stmt.order_by(SkillPromotion.created_at.desc()).limit(limit)

        promos = db.scalars(stmt).all()
        if not promos:
            return []

        skill_ids = list({p.skill_id for p in promos})
        skills = db.scalars(
            select(Skill).where(Skill.id.in_(skill_ids))
        ).all()
        skill_map = {s.id: s for s in skills}

        results = []
        for p in promos:
            skill = skill_map.get(p.skill_id)
            results.append({
                "id": p.id,
                "skill_id": p.skill_id,
                "skill_name": skill.name if skill else "(deleted)",
                "source_edition": (
                    p.source_edition.value
                    if hasattr(p.source_edition, "value") else p.source_edition
                ),
                "target_edition": (
                    p.target_edition.value
                    if hasattr(p.target_edition, "value") else p.target_edition
                ),
                "status": p.status,
                "reviewed_by": p.reviewed_by,
                "review_note": p.review_note,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            })
        return results
