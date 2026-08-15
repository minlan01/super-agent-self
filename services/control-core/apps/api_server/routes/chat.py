"""Conversational Chat endpoint — personal assistant interaction with LLM intent routing."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_current_user, get_db, require_permission
from packages.db.models import User
from packages.db.session import run_async

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)
    user_id: str = Field("default", min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_\-]+$")
    edition: str = "personal"
    conversation_id: str | None = None  # for multi-turn conversation


class ChatResponse(BaseModel):
    reply: str
    task_id: str | None = None
    action: str = "none"  # none | task_created | reminder_created | preference_saved
    conversation_id: str | None = None


# ── LLM Intent Classification ─────────────────────────────────────────────

INTENT_SYSTEM_PROMPT = """你是一个意图分类器。分析用户消息，判断其意图，返回 JSON。

可能的意图:
- "task": 用户想创建并执行一个任务（浏览网页、写文档、搜索、下载、提取信息等）
- "reminder": 用户想设置提醒（提醒我、记住要、别忘了等）
- "preference": 用户在表达个人偏好（我喜欢、我偏好、以后总是用、永远不要等）
- "info": 一般性问题、闲聊、或无法归类的消息

返回格式（只返回 JSON，不要其他内容）:
{"intent": "task" | "reminder" | "preference" | "info", "confidence": 0.0-1.0, "extracted": "提取的关键信息（任务目标/提醒内容/偏好内容）"}

注意: 如果用户用自然语言描述要做某事（如"帮我查一下天气预报"），这是 "task"，不是 "info"。
"""


async def _classify_intent(message: str) -> dict[str, Any]:
    """Use LLM to classify user intent. Falls back to keyword matching on failure."""
    try:
        from apps.api_server.dependencies import get_provider_router
        from packages.llm_gateway.base import LLMMessage

        provider_router = get_provider_router()
        messages = [
            LLMMessage(role="system", content=INTENT_SYSTEM_PROMPT),
            LLMMessage(role="user", content=message),
        ]
        response = await provider_router.generate_json(messages, chain="default")

        # Parse the JSON response
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            content = "\n".join(lines)

        result = json.loads(content)
        if "intent" not in result:
            raise ValueError("LLM response missing 'intent' key")
        intent = result["intent"]
        if intent not in ("task", "reminder", "preference", "info"):
            intent = "info"
        return {
            "intent": intent,
            "confidence": result.get("confidence", 0.5),
            "extracted": result.get("extracted", message),
        }
    except Exception as exc:
        logger.warning("LLM intent classification failed: %s, falling back to keywords", exc)
        return _keyword_fallback(message)


def _keyword_fallback(message: str) -> dict[str, Any]:
    """Simple keyword-based fallback when LLM is unavailable."""
    msg = message.lower().strip()

    if any(kw in msg for kw in ("remind", "remember to", "don't forget", "提醒", "别忘了")):
        return {"intent": "reminder", "confidence": 0.6, "extracted": message}
    if any(kw in msg for kw in ("i prefer", "always use", "never", "i like", "我喜欢", "偏好")):
        return {"intent": "preference", "confidence": 0.6, "extracted": message}
    task_kw = ("open", "browse", "scrape", "extract", "write", "save", "download", "search", "find", "create", "打开", "搜索", "写", "帮我", "查一下")
    if any(msg.startswith(kw) for kw in task_kw) or any(f" {kw} " in f" {msg} " for kw in ("帮我", "查一下")):
        return {"intent": "task", "confidence": 0.6, "extracted": message}

    return {"intent": "info", "confidence": 0.6, "extracted": message}


# ── Route Handler ──────────────────────────────────────────────────────────


@router.post("", response_model=ChatResponse, dependencies=[Depends(require_permission("chat", "write"))])
async def chat(body: ChatRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Conversational endpoint — LLM-powered intent detection and action routing."""
    from packages.db.models import UserRole
    from packages.db.repositories.conversation_repo import ConversationRepository

    # Enforce that user_id matches authenticated user (admins can override)
    if current_user and body.user_id != "default":
        is_admin = current_user.role == UserRole.ADMIN
        if not is_admin and body.user_id != current_user.id:
            body.user_id = current_user.id

    # Get or create conversation
    conv_id = body.conversation_id
    if conv_id:
        conv = await run_async(ConversationRepository.get_conversation, conv_id)
    else:
        conv = None

    if conv is None:
        conv = await run_async(
            ConversationRepository.create_conversation,
            user_id=body.user_id, edition=body.edition,
        )

    # Save user message
    await run_async(
        ConversationRepository.add_message,
        conv.id, "user", body.message,
    )

    # Commit the conversation writes before intent handlers run: handlers
    # may write via independent sessions (memory worker), and holding this
    # open transaction across them causes SQLite write-write lock timeouts.
    try:
        db.commit()
    except Exception:
        db.rollback()

    classification = await _classify_intent(body.message)
    intent = classification["intent"]
    extracted = classification.get("extracted", body.message)

    logger.info(
        "Chat intent: %s (confidence=%.2f) for: %s",
        intent, classification.get("confidence", 0), body.message[:50],
    )

    if intent == "reminder":
        try:
            response = await run_async(_handle_reminder, body, extracted)
        except Exception as exc:
            logger.exception("Chat reminder handler failed: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to create reminder")
    elif intent == "preference":
        try:
            response = await _handle_preference(body, extracted, db)
        except Exception as exc:
            logger.exception("Chat preference handler failed: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to save preference")
    elif intent == "task":
        try:
            response = await run_async(_handle_task, body, extracted)
        except Exception as exc:
            logger.exception("Chat task handler failed: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to create task")
    else:
        response = await _handle_info(body, db)

    # Handlers write via the request session (e.g. memory INSERT) without
    # committing; commit before the independent-session assistant-message
    # write below, otherwise that write blocks on this session's lock
    # until the SQLite busy timeout expires.
    try:
        db.commit()
    except Exception:
        db.rollback()

    # Save assistant message
    await run_async(
        ConversationRepository.add_message,
        conv.id, "assistant", response.reply,
    )

    response.conversation_id = conv.id
    return response


def _handle_reminder(db: Session, body: ChatRequest, extracted: str) -> ChatResponse:
    """Create a reminder."""
    from packages.personal_context.reminder_service import ReminderService

    svc = ReminderService()
    reminder = svc.create_reminder(
        db, title=extracted[:200], description=body.message,
        user_id=body.user_id, edition=body.edition,
    )
    return ChatResponse(
        reply=f"Got it! I've saved a reminder: {extracted[:80]}",
        task_id=reminder.id,
        action="reminder_created",
    )


async def _handle_preference(body: ChatRequest, extracted: str, db: Session) -> ChatResponse:
    """Save a user preference."""
    from packages.memory.memory_service import MemoryService
    from packages.memory.summarizer import MemorySummarizer
    from packages.personal_context.personal_context_service import PersonalContextService

    mem_svc = MemoryService(summarizer=MemorySummarizer())
    ctx_svc = PersonalContextService(mem_svc)
    await ctx_svc.save_preference(
        db, key=extracted[:50], value=body.message, user_id=body.user_id,
    )
    return ChatResponse(
        reply=f"Noted! I've saved your preference: {extracted[:80]}",
        action="preference_saved",
    )


def _handle_task(db: Session, body: ChatRequest, extracted: str) -> ChatResponse:
    """Create a task."""
    from packages.agent_core.schemas import AuditEventCreate, TaskCreate
    from packages.db.models import AuditEventType
    from packages.db.repositories.audit_repo import AuditRepository
    from packages.db.repositories.task_repo import TaskRepository

    task = TaskRepository.create(db, TaskCreate(
        goal=body.message, edition=body.edition, user_id=body.user_id,
    ))
    AuditRepository.create(db, AuditEventCreate(
        task_id=task.id, edition=body.edition,
        event_type=AuditEventType.TASK_CREATED,
        detail={"goal": body.message, "source": "chat", "intent_extracted": extracted},
    ))
    return ChatResponse(
        reply=f"I've created a task for you: {extracted[:80]}\nTask ID: {task.id}\nI'll start working on it right away.",
        task_id=task.id,
        action="task_created",
    )


async def _handle_info(body: ChatRequest, db: Session) -> ChatResponse:
    """General conversation handler — uses LLM to generate a real response."""
    from packages.db.repositories.conversation_repo import ConversationRepository

    # Fetch recent conversation history for multi-turn context
    history: list[dict[str, str]] = []
    if body.conversation_id:
        msgs = await run_async(
            ConversationRepository.get_recent_messages, body.conversation_id, 20
        )
        for m in msgs:
            history.append({"role": m.role, "content": m.content})

    # Call LLM on the main event loop (httpx client is bound to it)
    try:
        reply = await _llm_chat_reply(body.message, history)
    except Exception as exc:
        logger.warning("LLM chat reply failed: %s", exc)
        reply = _fallback_chat_reply(body.message)

    return ChatResponse(reply=reply)


CHAT_SYSTEM_PROMPT = """你是一个友好、专业的个人智能助手。你可以：
- 回答各种问题（技术、知识、建议等）
- 进行自然对话和闲聊
- 用用户的语言回复（中文提问用中文，英文提问用英文）

请直接回答用户的问题，保持简洁有用。如果涉及需要执行的操作（如创建任务、设置提醒），建议用户明确说明。"""


async def _llm_chat_reply(message: str, history: list[dict[str, str]]) -> str:
    """Call the LLM to generate a conversational reply."""
    from apps.api_server.dependencies import get_provider_router
    from packages.llm_gateway.base import LLMMessage

    provider_router = get_provider_router()
    messages = [LLMMessage(role="system", content=CHAT_SYSTEM_PROMPT)]
    for h in history:
        messages.append(LLMMessage(role=h["role"], content=h["content"]))
    messages.append(LLMMessage(role="user", content=message))

    response = await provider_router.generate(messages, chain="default")
    return response.content.strip()


def _fallback_chat_reply(message: str) -> str:
    """Fallback reply when all LLM providers are unavailable."""
    return (
        "所有模型连接失败，请检查：\n"
        "- 网络/代理是否正常\n"
        "- API Key 是否正确（环境变量）\n"
        "- configs/models.yaml 中 defaults.provider 是否配置正确\n"
        "后端控制台日志中有详细错误信息。"
    )
