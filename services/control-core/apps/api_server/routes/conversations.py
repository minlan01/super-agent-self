"""Conversation API — list, history, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_current_user, get_db, require_permission
from packages.agent_core.schemas import ResponseBase
from packages.db.models import User

router = APIRouter()


class ConversationResponse(BaseModel):
    id: str
    user_id: str
    title: str | None = None
    edition: str
    created_at: str | None = None


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str | None = None


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: list[MessageResponse]


class ConversationListResponse(BaseModel):
    success: bool = True
    data: list[ConversationResponse]
    count: int


def _enforce_owner(conv_user_id: str, current_user_id: str, is_admin: bool) -> None:
    if not is_admin and conv_user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Not your conversation")


@router.get("", response_model=ConversationListResponse, dependencies=[Depends(require_permission("conversations", "read"))])
def list_conversations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from packages.db.models import UserRole
    from packages.db.repositories.conversation_repo import ConversationRepository

    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    is_admin = current_user.role == UserRole.ADMIN
    filter_user_id = None if is_admin else current_user.id

    convs = ConversationRepository.list_conversations(
        db, user_id=filter_user_id, limit=limit, offset=offset,
    )
    total = ConversationRepository.count_conversations(db, user_id=filter_user_id)
    items = [
        ConversationResponse(
            id=c.id,
            user_id=c.user_id,
            title=c.title,
            edition=c.edition,
            created_at=c.created_at.isoformat() if c.created_at else None,
        )
        for c in convs
    ]
    return ConversationListResponse(data=items, count=total)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse, dependencies=[Depends(require_permission("conversations", "read"))])
def get_conversation(
    conversation_id: str = Path(..., max_length=64),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from packages.db.models import UserRole
    from packages.db.repositories.conversation_repo import ConversationRepository

    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    conv = ConversationRepository.get_conversation(db, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    _enforce_owner(conv.user_id, current_user.id, current_user.role == UserRole.ADMIN)

    # Messages already loaded via selectinload in get_conversation — no extra query
    return ConversationDetailResponse(
        conversation=ConversationResponse(
            id=conv.id,
            user_id=conv.user_id,
            title=conv.title,
            edition=conv.edition,
            created_at=conv.created_at.isoformat() if conv.created_at else None,
        ),
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in conv.messages
        ],
    )


@router.delete("/{conversation_id}", response_model=ResponseBase, dependencies=[Depends(require_permission("conversations", "write"))])
def delete_conversation(
    conversation_id: str = Path(..., max_length=64),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from packages.db.models import Conversation, ConversationMessage, UserRole
    from packages.db.repositories.conversation_repo import ConversationRepository

    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    conv = ConversationRepository.get_conversation(db, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    _enforce_owner(conv.user_id, current_user.id, current_user.role == UserRole.ADMIN)

    db.execute(
        delete(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id
        )
    )
    db.execute(delete(Conversation).where(Conversation.id == conversation_id))
    db.commit()

    return {"success": True, "message": f"Conversation {conversation_id} deleted"}
