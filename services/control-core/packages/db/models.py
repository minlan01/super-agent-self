"""ORM models — 24 tables for the Controlled Agent Platform."""

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from packages.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


# ── Enums ──────────────────────────────────────────────────────────────────


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    POLICY_CHECK = "policy_check"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AuditEventType(str, enum.Enum):
    TASK_CREATED = "task_created"
    PLAN_GENERATED = "plan_generated"
    POLICY_CHECK = "policy_check"
    POLICY_APPROVED = "policy_approved"
    POLICY_REJECTED = "policy_rejected"
    STEP_EXECUTING = "step_executing"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    MEMORY_WRITTEN = "memory_written"
    SKILL_EXTRACTED = "skill_extracted"
    SKILL_APPROVED = "skill_approved"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    ROLE_CREATED = "role_created"
    ROLE_UPDATED = "role_updated"
    ROLE_DELETED = "role_deleted"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"
    SSO_LOGIN = "sso_login"
    SSO_USER_CREATED = "sso_user_created"
    USER_REGISTERED = "user_registered"
    USER_LOGIN = "user_login"
    SKILL_DISABLED = "skill_disabled"
    SKILL_ROLLEDBACK = "skill_rolledback"
    DB_BACKUP = "db_backup"
    DB_RESTORE = "db_restore"


class MemoryType(str, enum.Enum):
    EXECUTION_EXPERIENCE = "execution_experience"
    WORKFLOW_PATTERN = "workflow_pattern"
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    ERROR_SOLUTION = "error_solution"
    USER_PREFERENCE = "user_preference"
    PERSONAL_PROJECT = "personal_project"
    FILE_KNOWLEDGE = "file_knowledge"
    REMINDER = "reminder"
    DAILY_CONTEXT = "daily_context"


class SkillStatus(str, enum.Enum):
    CANDIDATE = "candidate"
    STABLE = "stable"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalType(str, enum.Enum):
    SKILL = "skill"
    HIGH_RISK_STEP = "high_risk_step"


class Edition(str, enum.Enum):
    ENTERPRISE = "enterprise"
    PERSONAL = "personal"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class AuthMethod(str, enum.Enum):
    LOCAL = "local"
    SSO = "sso"


class PromotionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ── Mixin ──────────────────────────────────────────────────────────────────


class _TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ── 1. tasks ───────────────────────────────────────────────────────────────


class Task(_TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_created_at", "created_at"),
        Index("ix_tasks_edition", "edition"),
        Index("ix_tasks_user_id_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), default="default", index=True)
    edition: Mapped[Edition] = mapped_column(Enum(Edition), default=Edition.ENTERPRISE)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING, index=True)
    risk_level: Mapped[RiskLevel | None] = mapped_column(Enum(RiskLevel), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    steps: Mapped[list["TaskStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskStep.step_order"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="task")


# ── 2. task_steps ──────────────────────────────────────────────────────────


class TaskStep(_TimestampMixin, Base):
    __tablename__ = "task_steps"
    __table_args__ = (
        Index("ix_task_steps_task_id", "task_id"),
        Index("ix_task_steps_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    args: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    risk_level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel), default=RiskLevel.LOW)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.PENDING)
    capability_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped["Task"] = relationship(back_populates="steps")

    @validates("args")
    def _validate_args(self, key: str, value: Any) -> Any:
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"TaskStep.args must be a dict or None, got {type(value).__name__}")
        return value


# ── 3. audit_events ────────────────────────────────────────────────────────


class AuditEvent(_TimestampMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_task_id", "task_id"),
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_actor", "actor"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    step_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    edition: Mapped[Edition | None] = mapped_column(Enum(Edition), nullable=True)
    event_type: Mapped[AuditEventType] = mapped_column(Enum(AuditEventType), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    task: Mapped["Task | None"] = relationship(back_populates="audit_events")

    @validates("detail")
    def _validate_detail(self, key: str, value: Any) -> Any:
        if value is not None and not isinstance(value, dict):
            raise ValueError(
                f"AuditEvent.detail must be a dict or None, "
                f"got {type(value).__name__}"
            )
        return value


# ── 4. memories ────────────────────────────────────────────────────────────


class Memory(_TimestampMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_user_active", "user_id", "is_active"),
        Index("ix_memories_source_task_id", "source_task_id"),
        Index("ix_memories_dedup", "content_hash", "user_id", "is_active"),
        Index("ix_memories_edition", "edition"),
        Index("ix_memories_memory_type", "memory_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), default="default")
    edition: Mapped[Edition] = mapped_column(Enum(Edition), default=Edition.ENTERPRISE)
    memory_type: Mapped[MemoryType] = mapped_column(Enum(MemoryType), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    source_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    @validates("content")
    def _validate_content(self, key: str, value: Any) -> Any:
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"Memory.content must be a dict or None, got {type(value).__name__}")
        return value


# ── 5. skills ──────────────────────────────────────────────────────────────


class Skill(_TimestampMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (
        Index("ix_skills_status", "status"),
        Index("ix_skills_edition", "edition"),
        Index("ix_skills_name_edition", "name", "edition"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    edition: Mapped[Edition] = mapped_column(Enum(Edition), default=Edition.ENTERPRISE)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[SkillStatus] = mapped_column(Enum(SkillStatus), default=SkillStatus.CANDIDATE)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    source_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    runs: Mapped[list["SkillRun"]] = relationship(back_populates="skill", cascade="all, delete-orphan")

    @validates("definition")
    def _validate_definition(self, key: str, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError(f"Skill.definition must be a dict, got {type(value).__name__}")
        return value


# ── 6. skill_runs ──────────────────────────────────────────────────────────


class SkillRun(_TimestampMixin, Base):
    __tablename__ = "skill_runs"
    __table_args__ = (
        Index("ix_skill_runs_skill_id", "skill_id"),
        Index("ix_skill_runs_task_id", "task_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    skill_id: Mapped[str] = mapped_column(String(36), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    execution_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    with_skill_duration: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    without_skill_duration: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)

    skill: Mapped["Skill"] = relationship(back_populates="runs")


# ── 7. approvals ───────────────────────────────────────────────────────────


class Approval(_TimestampMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_status", "status"),
        Index("ix_approvals_edition", "edition"),
        Index("ix_approvals_requested_by", "requested_by"),
        Index("ix_approvals_approved_by", "approved_by"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    edition: Mapped[Edition] = mapped_column(Enum(Edition), default=Edition.ENTERPRISE)
    approval_type: Mapped[ApprovalType] = mapped_column(Enum(ApprovalType), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    requested_by: Mapped[str] = mapped_column(String(100), default="system")
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ── 8. edition_profiles ────────────────────────────────────────────────────


class EditionProfile(_TimestampMixin, Base):
    __tablename__ = "edition_profiles"
    __table_args__ = (
        Index("ix_edition_profiles_edition", "edition"),
        Index("ix_edition_profiles_edition_active", "edition", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    edition: Mapped[Edition] = mapped_column(Enum(Edition), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @validates("config")
    def _validate_config(self, key: str, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError(f"EditionProfile.config must be a dict, got {type(value).__name__}")
        return value


# ── 9. conversations ──────────────────────────────────────────────────────


class Conversation(_TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), default="default")
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    edition: Mapped[Edition] = mapped_column(Enum(Edition), default=Edition.ENTERPRISE)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
    )


# ── 10. conversation_messages ─────────────────────────────────────────────


class ConversationMessage(_TimestampMixin, Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conv_messages_conv_id", "conversation_id"),
        Index("ix_conv_messages_created_at", "created_at"),
    )

    _ALLOWED_ROLES = {"user", "assistant", "tool", "system"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    @validates("role")
    def _validate_role(self, key: str, value: str) -> str:
        if value not in self._ALLOWED_ROLES:
            raise ValueError(
                f"ConversationMessage.role must be one of {self._ALLOWED_ROLES}, "
                f"got '{value}'"
            )
        return value


# ── 11. users ──────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_username", "username", unique=True),
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_sso_id", "sso_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sso_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sso_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    auth_method: Mapped[AuthMethod] = mapped_column(Enum(AuthMethod), default=AuthMethod.LOCAL)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    role_assignments: Mapped[list["UserRoleAssignment"]] = relationship(back_populates="user", cascade="all, delete-orphan")


# ── 12. task_templates ────────────────────────────────────────────────────


class TaskTemplate(_TimestampMixin, Base):
    __tablename__ = "task_templates"
    __table_args__ = (
        Index("ix_task_templates_edition", "edition"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal_template: Mapped[str] = mapped_column(Text, nullable=False)
    edition: Mapped[Edition] = mapped_column(Enum(Edition), default=Edition.ENTERPRISE)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)


# ── 13. task_dependencies ──────────────────────────────────────────────────


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        Index("ix_task_deps_task_id", "task_id"),
        Index("ix_task_deps_depends_on_id", "depends_on_id"),
        Index("ix_task_dependencies_task_depends", "task_id", "depends_on_id"),
        UniqueConstraint("task_id", "depends_on_id", name="uq_task_dep"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    depends_on_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ── 14. notifications ─────────────────────────────────────────────────────


class NotificationModel(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id", "user_id"),
        Index("ix_notifications_user_unread", "user_id", "read"),
        Index("ix_notifications_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


# ── 15. messaging_channels ────────────────────────────────────────────────


class MessagingChannel(Base):
    __tablename__ = "messaging_channels"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "channel_id", name="uq_messaging_channel"),
        Index("ix_messaging_channels_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)  # telegram|discord|slack|feishu
    channel_id: Mapped[str] = mapped_column(String(200), nullable=False)  # platform-specific ID
    channel_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ── 16. message_logs ──────────────────────────────────────────────────────


class MessageLog(Base):
    __tablename__ = "message_logs"
    __table_args__ = (
        Index("ix_message_logs_channel_id", "channel_id"),
        Index("ix_message_logs_created_at", "created_at"),
        Index("ix_message_logs_platform", "platform"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    channel_id: Mapped[str] = mapped_column(String(36), ForeignKey("messaging_channels.id", ondelete="CASCADE"), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # "inbound" | "outbound"
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ── 17. skill_ratings ────────────────────────────────────────────────────


class SkillRating(_TimestampMixin, Base):
    __tablename__ = "skill_ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", name="uq_skill_rating"),
        Index("ix_skill_ratings_skill_id", "skill_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(36), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    review: Mapped[str | None] = mapped_column(Text, nullable=True)

    @validates("rating")
    def _validate_rating(self, key: str, value: int) -> int:
        if not isinstance(value, int) or value < 1 or value > 5:
            raise ValueError(
                f"SkillRating.rating must be an integer between 1 and 5, got {value!r}"
            )
        return value


# ── 18. skill_subscriptions ────────────────────────────────────────────────


class SkillSubscription(_TimestampMixin, Base):
    __tablename__ = "skill_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", name="uq_skill_subscription"),
        Index("ix_skill_subscriptions_skill_id", "skill_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(36), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ── 19. skill_promotions ────────────────────────────────────────────────


class SkillPromotion(_TimestampMixin, Base):
    __tablename__ = "skill_promotions"
    __table_args__ = (
        Index("ix_skill_promotions_skill_id", "skill_id"),
        Index("ix_skill_promotions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    skill_id: Mapped[str] = mapped_column(String(36), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    source_edition: Mapped[Edition] = mapped_column(Enum(Edition), nullable=False)
    target_edition: Mapped[Edition] = mapped_column(Enum(Edition), nullable=False)
    status: Mapped[PromotionStatus] = mapped_column(
        Enum(PromotionStatus), default=PromotionStatus.PENDING
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── 20. roles ──────────────────────────────────────────────────────────


class Role(_TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("name", name="uq_role_name"),
        Index("ix_roles_is_default", "is_default"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role", cascade="all, delete-orphan")
    user_assignments: Mapped[list["UserRoleAssignment"]] = relationship(back_populates="role", cascade="all, delete-orphan")


# ── 21. permissions ──────────────────────────────────────────────────


class Permission(_TimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("resource", "action", name="uq_permission_resource_action"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    roles: Mapped[list["RolePermission"]] = relationship(back_populates="permission", cascade="all, delete-orphan")


# ── 22. role_permissions ──────────────────────────────────────────────


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
        Index("ix_role_permissions_role_id", "role_id"),
        Index("ix_role_permissions_permission_id", "permission_id"),
    )

    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[str] = mapped_column(String(36), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)

    role: Mapped["Role"] = relationship(back_populates="permissions")
    permission: Mapped["Permission"] = relationship(back_populates="roles")


# ── 23. user_role_assignments ─────────────────────────────────────────


class UserRoleAssignment(Base):
    __tablename__ = "user_role_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
        Index("ix_user_role_assignments_user_id", "user_id"),
        Index("ix_user_role_assignments_role_id", "role_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    granted_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    user: Mapped["User"] = relationship(back_populates="role_assignments")
    role: Mapped["Role"] = relationship(back_populates="user_assignments")


# ── 24. llm_cost_records ──────────────────────────────────────────────


class LLMCostRecord(_TimestampMixin, Base):
    __tablename__ = "llm_cost_records"
    __table_args__ = (
        Index("ix_llm_cost_records_provider", "provider"),
        Index("ix_llm_cost_records_created_at", "created_at"),
        Index("ix_llm_cost_provider_date", "provider", "created_at"),
        Index("ix_llm_cost_records_model", "model"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
