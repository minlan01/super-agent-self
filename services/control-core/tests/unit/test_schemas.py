"""Unit tests for Pydantic schema validation."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from packages.agent_core.schemas import (
    ApprovalCreate,
    ApprovalResolve,
    ApprovalType,
    AuditEventCreate,
    AuditEventType,
    Edition,
    HealthResponse,
    MemoryCreate,
    MemorySearchQuery,
    MemoryType,
    RiskLevel,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from packages.db.models import TaskStatus

# ── TaskCreate ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTaskCreate:
    def test_valid_task_create(self):
        schema = TaskCreate(goal="Deploy the application")
        assert schema.goal == "Deploy the application"
        assert schema.edition == Edition.ENTERPRISE
        assert schema.user_id is None  # P1.3: overwritten by ActorScope, never trusted from body

    def test_goal_required(self):
        with pytest.raises(ValidationError) as exc_info:
            TaskCreate()  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("goal",) for e in errors)

    def test_goal_min_length(self):
        with pytest.raises(ValidationError) as exc_info:
            TaskCreate(goal="")
        errors = exc_info.value.errors()
        assert any("at least 1 character" in str(e["msg"]) for e in errors)

    def test_goal_max_length(self):
        with pytest.raises(ValidationError):
            TaskCreate(goal="x" * 5001)

    def test_custom_edition(self):
        schema = TaskCreate(goal="test", edition=Edition.PERSONAL)
        assert schema.edition == Edition.PERSONAL

    def test_custom_user_id(self):
        schema = TaskCreate(goal="test", user_id="user-42")
        assert schema.user_id == "user-42"


# ── TaskUpdate ─────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTaskUpdate:
    def test_empty_update_allowed(self):
        schema = TaskUpdate()
        assert schema.status is None
        assert schema.result is None
        assert schema.error is None
        assert schema.risk_level is None

    def test_partial_update(self):
        schema = TaskUpdate(status=TaskStatus.COMPLETED)
        assert schema.status == TaskStatus.COMPLETED
        assert schema.result is None


# ── TaskResponse (from_attributes) ────────────────────────────────────────


@pytest.mark.unit
class TestTaskResponse:
    def _make_mock_task(self, **overrides):
        defaults = {
            "id": "task-001",
            "user_id": "default",
            "edition": Edition.ENTERPRISE,
            "goal": "Build API",
            "status": TaskStatus.PENDING,
            "risk_level": None,
            "result": None,
            "error": None,
            "created_at": datetime(2026, 1, 1, 12, 0, 0),
            "updated_at": datetime(2026, 1, 1, 12, 0, 0),
            "steps": [],
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_from_attributes_basic(self):
        mock = self._make_mock_task()
        response = TaskResponse.model_validate(mock, from_attributes=True)
        assert response.id == "task-001"
        assert response.goal == "Build API"
        assert response.status == TaskStatus.PENDING
        assert response.edition == Edition.ENTERPRISE
        assert response.steps == []

    def test_from_attributes_with_steps(self):
        step = SimpleNamespace(
            id="step-001",
            task_id="task-001",
            step_order=0,
            tool_name="bash",
            args=None,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            status=TaskStatus.PENDING,
            capability_token_hash=None,
            result=None,
            error=None,
            created_at=datetime(2026, 1, 1, 12, 0, 0),
            updated_at=datetime(2026, 1, 1, 12, 0, 0),
        )
        mock = self._make_mock_task(steps=[step])
        response = TaskResponse.model_validate(mock, from_attributes=True)
        assert len(response.steps) == 1
        assert response.steps[0].tool_name == "bash"

    def test_from_attributes_with_result(self):
        mock = self._make_mock_task(
            status=TaskStatus.COMPLETED,
            result="Success",
            risk_level=RiskLevel.MEDIUM,
        )
        response = TaskResponse.model_validate(mock, from_attributes=True)
        assert response.status == TaskStatus.COMPLETED
        assert response.result == "Success"
        assert response.risk_level == RiskLevel.MEDIUM


# ── MemoryCreate ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMemoryCreate:
    def test_valid_memory_create(self):
        schema = MemoryCreate(
            memory_type=MemoryType.DOMAIN_KNOWLEDGE,
            title="FastAPI tips",
            summary="Use dependency injection",
        )
        assert schema.memory_type == MemoryType.DOMAIN_KNOWLEDGE
        assert schema.importance_score == 0.5
        assert schema.confidence_score == 0.5

    def test_importance_score_bounds_valid(self):
        schema = MemoryCreate(
            memory_type=MemoryType.ERROR_SOLUTION,
            title="t",
            summary="s",
            importance_score=0.0,
        )
        assert schema.importance_score == 0.0

        schema = MemoryCreate(
            memory_type=MemoryType.ERROR_SOLUTION,
            title="t",
            summary="s",
            importance_score=1.0,
        )
        assert schema.importance_score == 1.0

    def test_importance_score_below_zero(self):
        with pytest.raises(ValidationError) as exc_info:
            MemoryCreate(
                memory_type=MemoryType.ERROR_SOLUTION,
                title="t",
                summary="s",
                importance_score=-0.1,
            )
        errors = exc_info.value.errors()
        assert any("greater than or equal to 0" in str(e["msg"]) for e in errors)

    def test_importance_score_above_one(self):
        with pytest.raises(ValidationError) as exc_info:
            MemoryCreate(
                memory_type=MemoryType.ERROR_SOLUTION,
                title="t",
                summary="s",
                importance_score=1.1,
            )
        errors = exc_info.value.errors()
        assert any("less than or equal to 1" in str(e["msg"]) for e in errors)

    def test_confidence_score_bounds(self):
        with pytest.raises(ValidationError):
            MemoryCreate(
                memory_type=MemoryType.ERROR_SOLUTION,
                title="t",
                summary="s",
                confidence_score=2.0,
            )

    def test_title_required(self):
        with pytest.raises(ValidationError):
            MemoryCreate(
                memory_type=MemoryType.ERROR_SOLUTION,
                summary="s",
            )

    def test_summary_min_length(self):
        with pytest.raises(ValidationError):
            MemoryCreate(
                memory_type=MemoryType.ERROR_SOLUTION,
                title="t",
                summary="",
            )


# ── MemorySearchQuery ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestMemorySearchQuery:
    def test_defaults(self):
        query = MemorySearchQuery()
        assert query.keyword is None
        assert query.memory_type is None
        assert query.source_task_id is None
        assert query.is_active is True
        assert query.limit == 10

    def test_custom_values(self):
        query = MemorySearchQuery(
            keyword="SQLAlchemy",
            memory_type=MemoryType.DOMAIN_KNOWLEDGE,
            is_active=False,
            limit=50,
        )
        assert query.keyword == "SQLAlchemy"
        assert query.memory_type == MemoryType.DOMAIN_KNOWLEDGE
        assert query.is_active is False
        assert query.limit == 50

    def test_limit_minimum(self):
        with pytest.raises(ValidationError):
            MemorySearchQuery(limit=0)

    def test_limit_maximum(self):
        with pytest.raises(ValidationError):
            MemorySearchQuery(limit=101)


# ── AuditEventCreate ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestAuditEventCreate:
    def test_valid_create(self):
        schema = AuditEventCreate(event_type=AuditEventType.TASK_CREATED)
        assert schema.event_type == AuditEventType.TASK_CREATED
        assert schema.actor == "system"
        assert schema.task_id is None
        assert schema.detail is None

    def test_event_type_required(self):
        with pytest.raises(ValidationError):
            AuditEventCreate()


# ── ApprovalCreate / ApprovalResolve ───────────────────────────────────────


@pytest.mark.unit
class TestApprovalCreate:
    def test_valid_create(self):
        schema = ApprovalCreate(
            approval_type=ApprovalType.SKILL,
            target_id="skill-001",
        )
        assert schema.approval_type == ApprovalType.SKILL
        assert schema.target_id == "skill-001"
        assert schema.edition == Edition.ENTERPRISE
        assert schema.requested_by == "system"


@pytest.mark.unit
class TestApprovalResolve:
    def test_approve(self):
        schema = ApprovalResolve(approved=True, approved_by="admin")
        assert schema.approved is True
        assert schema.approved_by == "admin"

    def test_reject_with_reason(self):
        schema = ApprovalResolve(approved=False, approved_by="admin", reason="Too risky")
        assert schema.approved is False
        assert schema.reason == "Too risky"


# ── HealthResponse ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHealthResponse:
    def test_defaults(self):
        health = HealthResponse()
        assert health.status == "ok"
        assert health.version == "3.11.0"
        assert health.edition == "enterprise"

    def test_custom_values(self):
        health = HealthResponse(status="degraded", version="0.2.0", edition="personal")
        assert health.status == "degraded"
        assert health.version == "0.2.0"
        assert health.edition == "personal"
