"""REST API endpoints for the notification system."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_current_user, get_db, require_permission
from packages.agent_core.schemas import (
    NotificationClearResponse,
    NotificationListResponse,
    NotificationMarkReadResponse,
    NotificationUnreadCountResponse,
    ResponseBase,
)
from packages.db.models import NotificationModel, User
from packages.db.pagination import PaginatedResult, paginate
from packages.notification.notification_service import notification_service

router = APIRouter()


@router.get(
    "",
    response_model=NotificationListResponse,
    dependencies=[Depends(require_permission("notifications", "read"))],
)
def get_notifications(
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get notifications for the current user (paginated, newest first).

    Uses in-memory ring buffer first.  If the user has no in-memory
    notifications (e.g. after a server restart), falls back to the
    database with proper DB-level pagination.
    """
    uid = current_user.id if current_user else "default"
    page = max(1, page)
    page_size = min(max(1, page_size), 100)

    in_memory = notification_service.get_all(uid)
    if in_memory:
        offset = (page - 1) * page_size
        total = len(in_memory)
        notifications = in_memory[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        result = PaginatedResult(
            items=[n.to_dict() if hasattr(n, "to_dict") else n for n in notifications],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
        )
    else:
        stmt = (
            select(NotificationModel)
            .where(NotificationModel.user_id == uid)
            .order_by(NotificationModel.created_at.desc())
        )
        db_result = paginate(db, stmt, page=page, page_size=page_size)
        result = PaginatedResult(
            items=[
                {
                    "id": row.id,
                    "type": row.type,
                    "title": row.title,
                    "message": row.message or "",
                    "data": row.data,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                    "read": row.read,
                }
                for row in db_result.items
            ],
            total=db_result.total,
            page=db_result.page,
            page_size=db_result.page_size,
            total_pages=db_result.total_pages,
            has_next=db_result.has_next,
            has_prev=db_result.has_prev,
        )

    return {
        "success": True,
        "data": result.items,
        "count": len(result.items),
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "total_pages": result.total_pages,
        "has_next": result.has_next,
        "has_prev": result.has_prev,
        "unread_count": notification_service.get_unread_count(uid),
    }


@router.get(
    "/unread",
    response_model=NotificationUnreadCountResponse,
    dependencies=[Depends(require_permission("notifications", "read"))],
)
def get_unread_count(
    current_user: User = Depends(get_current_user),
):
    """Get the number of unread notifications for the current user."""
    uid = current_user.id if current_user else "default"
    count = notification_service.get_unread_count(uid)
    return {"success": True, "count": count}


@router.post(
    "/{notification_id}/read",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("notifications", "write"))],
)
def mark_as_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a single notification as read."""
    uid = current_user.id if current_user else "default"
    found = notification_service.mark_read(uid, notification_id, db=db)
    if not found:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"success": True, "message": "Notification marked as read"}


@router.post(
    "/read-all",
    response_model=NotificationMarkReadResponse,
    dependencies=[Depends(require_permission("notifications", "write"))],
)
def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all notifications as read for the current user."""
    uid = current_user.id if current_user else "default"
    count = notification_service.mark_all_read(uid, db=db)
    return {"success": True, "marked_count": count}


@router.delete(
    "",
    response_model=NotificationClearResponse,
    dependencies=[Depends(require_permission("notifications", "write"))],
)
def clear_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clear all notifications for the current user."""
    uid = current_user.id if current_user else "default"
    count = notification_service.clear(uid, db=db)
    return {"success": True, "cleared_count": count}
