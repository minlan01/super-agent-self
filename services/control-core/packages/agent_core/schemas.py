"""Pydantic schemas — request/response models for all entities."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from packages.agent_core.version import __version__
from packages.db.models import (
    ApprovalStatus,
    ApprovalType,
    AuditEventType,
    AuthMethod,
    Edition,
    MemoryType,
    RiskLevel,
    SkillStatus,
    StepStatus,
    TaskStatus,
)

# ── Common ─────────────────────────────────────────────────────────────────


class ResponseBase(BaseModel):
    """Standard API response wrapper."""

    success: bool = True
    message: str = "ok"


class ErrorResponse(BaseModel):
    """Standard error response wrapper.

    Returned by the global exception handler for ``HTTPException`` and
    unhandled errors.  ``error_code`` is a stable machine-readable token
    (``http_404``, ``validation_error``, ``internal_error``, …) used by
    the frontend for i18n and error categorisation.  ``request_id`` lets
    the user paste a single id when reporting issues.
    """

    success: bool = False
    error_code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message (already sanitised)")
    request_id: str | None = Field(None, description="Correlation id for log lookup")
    details: dict[str, Any] | None = Field(None, description="Optional structured context")


class PaginatedResponse(BaseModel):
    total: int
    items: list[Any]
    page: int = 1
    page_size: int = 20


# ── Task ───────────────────────────────────────────────────────────────────


class TaskCreate(BaseModel):
    goal: str = Field(..., min_length=1, max_length=5000, description="Task goal description")
    edition: Edition = Edition.ENTERPRISE
    # P1.3 (G E-04): user_id is DEPRECATED for client input.
    # It's accepted for backward compat but MUST be overwritten by the route
    # from ActorScope (get_current_actor_scope). Clients that still send it
    # will have it silently ignored. Spec §2.3 forbids accepting forgeable identity.
    user_id: str | None = Field(None, description="DEPRECATED — overwritten by ActorScope")

    @field_validator("goal")
    @classmethod
    def _validate_goal_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("goal must not be blank or whitespace-only")
        return stripped


class TaskUpdate(BaseModel):
    status: TaskStatus | None = None
    result: str | None = None
    error: str | None = None
    risk_level: RiskLevel | None = None


class TaskResponse(BaseModel):
    id: str
    user_id: str
    edition: Edition
    goal: str
    status: TaskStatus
    risk_level: RiskLevel | None = None
    result: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    steps: list["TaskStepResponse"] = []

    model_config = {"from_attributes": True}


class TaskListResponse(ResponseBase):
    data: PaginatedResponse


class TaskDetailResponse(ResponseBase):
    data: TaskResponse


# ── TaskStep ───────────────────────────────────────────────────────────────


class TaskStepCreate(BaseModel):
    step_order: int = Field(..., ge=0)
    tool_name: str = Field(..., min_length=1, max_length=100)
    args: dict[str, Any] | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    requires_approval: bool = False


class TaskStepUpdate(BaseModel):
    status: StepStatus | None = None
    result: str | None = None
    error: str | None = None
    requires_approval: bool | None = None
    approval_request_id: str | None = None
    capability_token_hash: str | None = None


class TaskStepResponse(BaseModel):
    id: str
    task_id: str
    step_order: int
    tool_name: str
    args: dict[str, Any] | None = None
    risk_level: RiskLevel
    requires_approval: bool
    status: StepStatus
    approval_request_id: str | None = None
    capability_token_hash: str | None = None
    result: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── AuditEvent ─────────────────────────────────────────────────────────────


class AuditEventCreate(BaseModel):
    task_id: str | None = None
    step_id: str | None = None
    edition: Edition | None = None
    event_type: AuditEventType
    actor: str = "system"
    detail: dict[str, Any] | None = None


class AuditEventResponse(BaseModel):
    id: str
    task_id: str | None = None
    step_id: str | None = None
    edition: Edition | None = None
    event_type: AuditEventType
    actor: str
    detail: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditListResponse(ResponseBase):
    data: list[AuditEventResponse]


# ── Memory ─────────────────────────────────────────────────────────────────


class MemoryCreate(BaseModel):
    memory_type: MemoryType
    title: str = Field(..., min_length=1, max_length=500)
    summary: str = Field(..., min_length=1)
    content: dict[str, Any] | None = None
    importance_score: float = Field(0.5, ge=0.0, le=1.0)
    confidence_score: float = Field(0.5, ge=0.0, le=1.0)
    source_task_id: str | None = None
    expires_at: datetime | None = None


class MemoryUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    summary: str | None = Field(None, min_length=1, max_length=50000)
    importance_score: float | None = Field(None, ge=0.0, le=1.0)
    is_active: bool | None = None


class MemoryResponse(BaseModel):
    id: str
    user_id: str
    edition: Edition
    memory_type: MemoryType
    title: str
    summary: str
    content: dict[str, Any] | None = None
    content_hash: str | None = None
    importance_score: float
    confidence_score: float
    source_task_id: str | None = None
    is_active: bool
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemorySearchQuery(BaseModel):
    keyword: str | None = None
    memory_type: MemoryType | None = None
    source_task_id: str | None = None
    is_active: bool = True
    limit: int = Field(10, ge=1, le=100)


class MemoryListResponse(ResponseBase):
    data: list[MemoryResponse]


# ── Skill ──────────────────────────────────────────────────────────────────


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    definition: dict[str, Any]
    description: str | None = None
    edition: Edition = Edition.ENTERPRISE
    source_task_id: str | None = None


class SkillUpdate(BaseModel):
    status: SkillStatus | None = None
    description: str | None = None


class SkillResponse(BaseModel):
    id: str
    edition: Edition
    name: str
    version: int
    status: SkillStatus
    definition: dict[str, Any]
    description: str | None = None
    success_rate: float
    total_runs: int
    source_task_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SkillListResponse(ResponseBase):
    data: list[SkillResponse]


# ── SkillRun ───────────────────────────────────────────────────────────────


class SkillRunCreate(BaseModel):
    skill_id: str
    task_id: str
    success: bool
    execution_time: float | None = None
    estimated_cost_usd: float | None = None
    metrics: dict[str, Any] | None = None
    error: str | None = None


class SkillRunResponse(BaseModel):
    id: str
    skill_id: str
    task_id: str
    success: bool
    execution_time: float | None = None
    estimated_cost_usd: float | None = None
    metrics: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Approval ───────────────────────────────────────────────────────────────


class ApprovalCreate(BaseModel):
    approval_type: ApprovalType
    target_id: str
    edition: Edition = Edition.ENTERPRISE
    requested_by: str = "system"
    reason: str | None = None


class ApprovalResolve(BaseModel):
    approved: bool
    approved_by: str
    reason: str | None = None


class BatchApprovalItem(BaseModel):
    approval_id: str
    approved: bool
    approved_by: str
    reason: str | None = None


class BatchApprovalRequest(BaseModel):
    items: list[BatchApprovalItem]


class ApprovalResponse(BaseModel):
    id: str
    edition: Edition
    approval_type: ApprovalType
    target_id: str
    status: ApprovalStatus
    requested_by: str
    approved_by: str | None = None
    reason: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchApprovalResultItem(BaseModel):
    approval_id: str
    status: str
    current_status: str | None = None


class BatchApprovalResultResponse(ResponseBase):
    resolved: int = 0
    results: list[BatchApprovalResultItem] = []


class ApprovalListResponse(ResponseBase):
    data: list[ApprovalResponse]
    total: int = 0


# ── EditionProfile ─────────────────────────────────────────────────────────


class EditionProfileCreate(BaseModel):
    edition: Edition
    name: str = Field(..., min_length=1, max_length=100)
    config: dict[str, Any]


class EditionProfileResponse(BaseModel):
    id: str
    edition: Edition
    name: str
    config: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Health ─────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = __version__
    edition: str = "enterprise"


class ReadinessCheckResponse(BaseModel):
    """Response schema for the readiness probe."""
    ready: bool
    checks: dict[str, str]


class PlatformMetricsResponse(BaseModel):
    """Response schema for platform metrics."""
    tasks: dict[str, int]
    total_tasks: int
    memories: dict[str, int]
    uptime_seconds: int
    version: str


class TaskExecutionResponse(ResponseBase):
    """Response schema for task execution result."""
    data: dict[str, Any]


class TaskAuditListResponse(ResponseBase):
    """Response schema for task audit events."""
    data: list[AuditEventResponse]


class SkillDetailResponse(ResponseBase):
    """Response schema for single skill detail."""
    data: SkillResponse


class MemoryDetailResponse(ResponseBase):
    """Response schema for single memory detail."""
    data: MemoryResponse


# ── Auth ───────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    email: str | None = Field(None, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("username", "password")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Must not be blank or whitespace-only")
        return v


class UserResponse(BaseModel):
    id: str
    username: str
    email: str | None
    role: str
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_created_at(cls, v: object) -> str:
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)


class RegisterResponse(BaseModel):
    success: bool
    data: UserResponse


class LoginResponse(BaseModel):
    success: bool
    data: dict  # {"token": ..., "user": UserResponse}


class MeResponse(BaseModel):
    success: bool
    data: UserResponse


# ── RBAC ────────────────────────────────────────────────────────────────


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    is_default: bool = False
    permission_ids: list[str] = []


class RoleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    is_default: bool | None = None


class PermissionResponse(BaseModel):
    id: str
    name: str
    resource: str
    action: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoleResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    is_default: bool
    is_system: bool
    permissions: list[PermissionResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoleListResponse(ResponseBase):
    data: list[RoleResponse]
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 0
    has_next: bool = False
    has_prev: bool = False


class RoleDetailResponse(ResponseBase):
    data: RoleResponse


class UserRoleAssign(BaseModel):
    user_id: str
    role_ids: list[str]


class UserRoleRevoke(BaseModel):
    user_id: str
    role_ids: list[str]


class UserRoleAssignmentResponse(BaseModel):
    id: str
    user_id: str
    role_id: str
    role_name: str
    granted_by: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserRolesResponse(ResponseBase):
    data: list[UserRoleAssignmentResponse]


class PermissionListResponse(ResponseBase):
    data: list[PermissionResponse]


class UserPermissionsResponse(ResponseBase):
    data: list[str]


# ── SSO ────────────────────────────────────────────────────────────────


class SSOCallbackRequest(BaseModel):
    code: str
    state: str | None = None


class SSOTokenResponse(BaseModel):
    """Response schema for exchanging SSO authorization code for token."""
    token: str


class SSOLoginResponse(BaseModel):
    success: bool
    data: dict  # {"token": ..., "user": UserResponse, "is_new_user": bool}


class SSOProviderInfo(BaseModel):
    provider: str
    display_name: str
    login_url: str


class SSOProvidersResponse(ResponseBase):
    data: list[SSOProviderInfo]


# ── User (Extended for RBAC) ───────────────────────────────────────────


class UserDetailResponse(BaseModel):
    """Extended user response with roles and permissions."""
    id: str
    username: str
    email: str | None
    role: str
    is_active: bool
    created_at: str
    auth_method: str = "local"
    sso_provider: str | None = None
    roles: list[RoleResponse] = []
    permissions: list[str] = []  # flattened "resource:action" strings

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_created_at(cls, v: object) -> str:
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)

    model_config = {"from_attributes": True}


class UserListResponse(ResponseBase):
    data: list[UserDetailResponse]


# ── Analytics Schemas ────────────────────────────────────────────────────


class RealtimeMetricsResponse(BaseModel):
    """Real-time execution metrics."""
    running_tasks: int = 0
    completed_last_hour: int = 0
    failed_last_hour: int = 0
    avg_execution_time_seconds: float | None = None
    tasks_per_hour: float = 0.0
    active_skills: int = 0
    total_cost_usd: float = 0.0


class CostTrendPoint(BaseModel):
    date: str
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0


class CostBreakdownItem(BaseModel):
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0
    estimated_cost_usd: float = 0.0


class CostAnalyticsResponse(BaseModel):
    days: int = 30
    total_cost_usd: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_requests: int = 0
    trend: list[CostTrendPoint] = []
    breakdown: list[CostBreakdownItem] = []


class SkillBenchmarkItem(BaseModel):
    name: str
    success_rate: float = 0.0
    total_runs: int = 0
    avg_execution_time: float | None = None
    avg_cost_usd: float | None = None
    with_skill_duration: float | None = None
    without_skill_duration: float | None = None
    improvement_ratio: float | None = None
    trend: list[dict[str, Any]] = []


class SkillBenchmarkResponse(BaseModel):
    skills: list[SkillBenchmarkItem] = []


class AnomalyAlert(BaseModel):
    type: str  # "failure_spike", "cost_spike", "latency_spike", "skill_degradation"
    severity: str  # "warning", "critical"
    message: str
    resource: str
    value: float
    threshold: float
    detected_at: str


class AnomalyDetectionResponse(BaseModel):
    alerts: list[AnomalyAlert] = []
    checked_at: str = ""


# ── Analytics Overview / Trend ───────────────────────────────────────────


class AnalyticsOverviewResponse(BaseModel):
    """Response schema for analytics overview endpoint."""
    total_tasks: int = 0
    success_rate: float = 0.0
    active_skills: int = 0
    total_memories: int = 0
    recent_activity_24h: int = 0


class TaskTrendPoint(BaseModel):
    date: str
    count: int


class TaskTrendResponse(BaseModel):
    """Response schema for task trend endpoint."""
    days: int
    trend: list[TaskTrendPoint] = []


class TaskStatusDistributionResponse(BaseModel):
    """Response schema for task status distribution endpoint."""
    distribution: dict[str, int] = {}


class SkillsPerformanceResponse(BaseModel):
    """Response schema for skills performance endpoint."""
    skills: list[dict[str, Any]] = []


class MemoriesGrowthPoint(BaseModel):
    date: str
    count: int
    cumulative: int


class MemoriesGrowthResponse(BaseModel):
    """Response schema for memories growth endpoint."""
    days: int
    growth: list[MemoriesGrowthPoint] = []


class RecentActivityEvent(BaseModel):
    id: str
    event_type: str
    actor: str
    task_id: str | None = None
    detail: dict[str, Any] | None = None
    created_at: str | None = None


class RecentActivityResponse(BaseModel):
    """Response schema for recent activity endpoint."""
    events: list[RecentActivityEvent] = []
    total: int = 0


# ── Admin Schemas ────────────────────────────────────────────────────────


class BackupDataResponse(BaseModel):
    backup_path: str


class BackupRestoreResponse(BaseModel):
    message: str


class BackupListDataResponse(BaseModel):
    backups: list[str] = []
    total: int = 0


# ── Agent Schemas ────────────────────────────────────────────────────────


class AgentToolInfo(BaseModel):
    name: str
    description: str
    category: str


class AgentStatusResponse(BaseModel):
    success: bool = True
    data: dict[str, Any]


class AgentDataResponse(BaseModel):
    success: bool = True
    data: Any = None


class AgentMessageResponse(BaseModel):
    success: bool = True
    data: Any = None


# ── Personal Schemas ────────────────────────────────────────────────────


class ReminderCreateResponse(ResponseBase):
    data: dict[str, Any]


class ReminderListResponse(ResponseBase):
    data: list[dict[str, Any]] = []


class DailyContextResponse(ResponseBase):
    data: dict[str, Any]


class PreferenceListResponse(ResponseBase):
    data: Any = None


class PreferenceSaveResponse(ResponseBase):
    data: Any = None


class EditionInfo(BaseModel):
    edition: str
    name: str
    description: str


class EditionListResponse(ResponseBase):
    data: list[EditionInfo] = []


# ── Webhook / Messaging Schemas ─────────────────────────────────────────


class WebhookReceiveResponse(BaseModel):
    success: bool = True
    platform: str = ""
    sender: str = ""


class SendMessageResponse(BaseModel):
    success: bool
    message_id: str
    status: str


class ChannelInfo(BaseModel):
    id: str
    platform: str
    channel_id: str
    channel_name: str | None = None
    is_active: bool = True


class ChannelListResponse(BaseModel):
    success: bool = True
    channels: list[ChannelInfo] = []


class ChannelCreateData(BaseModel):
    id: str
    platform: str
    channel_id: str


class ChannelCreateResponse(BaseModel):
    success: bool = True
    channel: ChannelCreateData


class MessageHistoryItem(BaseModel):
    id: str
    direction: str
    platform: str
    sender_id: str | None = None
    content: str | None = None
    status: str
    created_at: str | None = None


class MessageHistoryResponse(BaseModel):
    success: bool = True
    messages: list[MessageHistoryItem] = []


# ── Marketplace Schemas ─────────────────────────────────────────────────


class MarketplaceBrowseResponse(ResponseBase):
    data: Any = None


class SubscriptionData(BaseModel):
    subscription_id: str
    skill_id: str


class SubscribeResponse(ResponseBase):
    data: SubscriptionData


class RatingData(BaseModel):
    rating_id: str
    rating: int


class RateSkillResponse(ResponseBase):
    data: RatingData


class PromotionData(BaseModel):
    promotion_id: str
    status: str


class PromoteSkillResponse(ResponseBase):
    data: PromotionData


# ── Plugin Schemas ──────────────────────────────────────────────────────


class PluginListResponse(BaseModel):
    success: bool = True
    data: Any = None


# ── Search Schemas ──────────────────────────────────────────────────────


class SearchDataResponse(BaseModel):
    """Response schema for unified search endpoint."""
    success: bool = True
    data: dict[str, Any]


# ── Notification Schemas ──────────────────────────────────────────────


class NotificationListResponse(ResponseBase):
    data: list[Any] = []
    count: int = 0
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0
    has_next: bool = False
    has_prev: bool = False
    unread_count: int = 0


class NotificationUnreadCountResponse(ResponseBase):
    count: int = 0


class NotificationMarkReadResponse(ResponseBase):
    marked_count: int = 0


class NotificationClearResponse(ResponseBase):
    cleared_count: int = 0
