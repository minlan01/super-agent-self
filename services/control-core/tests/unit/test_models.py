"""Unit tests for ORM model creation and relationships."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.db.models import (
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    AuditEventType,
    Edition,
    EditionProfile,
    Memory,
    MemoryType,
    RiskLevel,
    Skill,
    SkillRun,
    SkillStatus,
    StepStatus,
    Task,
    TaskStatus,
    TaskStep,
)
from packages.db.session import Base


@pytest.fixture
def db_session():
    """Create a fresh in-memory SQLite session with all tables."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


# ── Model creation tests ───────────────────────────────────────────────────


@pytest.mark.unit
class TestTaskModel:
    def test_create_task_minimal(self, db_session: Session):
        task = Task(goal="Build a REST API")
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)

        assert task.id is not None
        assert task.goal == "Build a REST API"
        assert task.status == TaskStatus.PENDING
        assert task.edition == Edition.ENTERPRISE
        assert task.user_id == "default"
        assert task.risk_level is None
        assert task.result is None
        assert task.error is None
        assert isinstance(task.created_at, datetime)
        assert isinstance(task.updated_at, datetime)

    def test_create_task_with_all_fields(self, db_session: Session):
        task = Task(
            goal="Deploy to production",
            user_id="user-42",
            edition=Edition.PERSONAL,
            status=TaskStatus.EXECUTING,
            risk_level=RiskLevel.HIGH,
            result="done",
            error=None,
        )
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)

        assert task.user_id == "user-42"
        assert task.edition == Edition.PERSONAL
        assert task.status == TaskStatus.EXECUTING
        assert task.risk_level == RiskLevel.HIGH
        assert task.result == "done"


@pytest.mark.unit
class TestTaskStepModel:
    def test_create_step_minimal(self, db_session: Session):
        task = Task(goal="parent task")
        db_session.add(task)
        db_session.commit()

        step = TaskStep(
            task_id=task.id,
            step_order=0,
            tool_name="bash",
        )
        db_session.add(step)
        db_session.commit()
        db_session.refresh(step)

        assert step.id is not None
        assert step.task_id == task.id
        assert step.step_order == 0
        assert step.tool_name == "bash"
        assert step.status == StepStatus.PENDING
        assert step.risk_level == RiskLevel.LOW
        assert step.requires_approval is False
        assert step.args is None
        assert step.capability_token_hash is None
        assert step.result is None
        assert step.error is None

    def test_create_step_with_all_fields(self, db_session: Session):
        task = Task(goal="parent task")
        db_session.add(task)
        db_session.commit()

        step = TaskStep(
            task_id=task.id,
            step_order=1,
            tool_name="file_write",
            args={"path": "/tmp/out.txt", "content": "hello"},
            risk_level=RiskLevel.CRITICAL,
            requires_approval=True,
            status=StepStatus.APPROVED,
            capability_token_hash="abc123hash",
        )
        db_session.add(step)
        db_session.commit()
        db_session.refresh(step)

        assert step.args == {"path": "/tmp/out.txt", "content": "hello"}
        assert step.risk_level == RiskLevel.CRITICAL
        assert step.requires_approval is True
        assert step.status == StepStatus.APPROVED
        assert step.capability_token_hash == "abc123hash"


@pytest.mark.unit
class TestTaskStepsRelationship:
    def test_steps_relationship(self, db_session: Session):
        task = Task(goal="multi-step task")
        db_session.add(task)
        db_session.commit()

        step0 = TaskStep(task_id=task.id, step_order=0, tool_name="bash")
        step1 = TaskStep(task_id=task.id, step_order=1, tool_name="file_read")
        step2 = TaskStep(task_id=task.id, step_order=2, tool_name="file_write")
        db_session.add_all([step0, step1, step2])
        db_session.commit()

        db_session.refresh(task)
        steps = task.steps
        assert len(steps) == 3
        assert [s.step_order for s in steps] == [0, 1, 2]
        assert steps[0].tool_name == "bash"
        assert steps[2].tool_name == "file_write"

    def test_cascade_delete(self, db_session: Session):
        task = Task(goal="to be deleted")
        db_session.add(task)
        db_session.commit()

        step = TaskStep(task_id=task.id, step_order=0, tool_name="bash")
        db_session.add(step)
        db_session.commit()

        step_id = step.id
        db_session.delete(task)
        db_session.commit()

        assert db_session.get(TaskStep, step_id) is None


@pytest.mark.unit
class TestAuditEventModel:
    def test_create_audit_event_minimal(self, db_session: Session):
        task = Task(goal="audited task")
        db_session.add(task)
        db_session.commit()

        event = AuditEvent(
            task_id=task.id,
            event_type=AuditEventType.TASK_CREATED,
        )
        db_session.add(event)
        db_session.commit()
        db_session.refresh(event)

        assert event.id is not None
        assert event.task_id == task.id
        assert event.event_type == AuditEventType.TASK_CREATED
        assert event.actor == "system"
        assert event.step_id is None
        assert event.detail is None

    def test_create_audit_event_with_detail(self, db_session: Session):
        event = AuditEvent(
            event_type=AuditEventType.POLICY_APPROVED,
            actor="admin",
            detail={"policy": "no-delete", "result": "pass"},
        )
        db_session.add(event)
        db_session.commit()
        db_session.refresh(event)

        assert event.actor == "admin"
        assert event.detail == {"policy": "no-delete", "result": "pass"}
        assert event.task_id is None


@pytest.mark.unit
class TestMemoryModel:
    def test_create_memory_minimal(self, db_session: Session):
        memory = Memory(
            memory_type=MemoryType.DOMAIN_KNOWLEDGE,
            title="SQLAlchemy tips",
            summary="Use mapped_column for type-safe columns",
        )
        db_session.add(memory)
        db_session.commit()
        db_session.refresh(memory)

        assert memory.id is not None
        assert memory.memory_type == MemoryType.DOMAIN_KNOWLEDGE
        assert memory.title == "SQLAlchemy tips"
        assert memory.summary == "Use mapped_column for type-safe columns"
        assert memory.importance_score == 0.5
        assert memory.confidence_score == 0.5
        assert memory.is_active is True
        assert memory.content is None
        assert memory.content_hash is None
        assert memory.source_task_id is None
        assert memory.expires_at is None

    def test_create_memory_with_all_fields(self, db_session: Session):
        memory = Memory(
            memory_type=MemoryType.ERROR_SOLUTION,
            title="Fix port conflict",
            summary="Kill process on port 8000",
            content={"command": "fuser -k 8000/tcp"},
            content_hash="sha256abc",
            importance_score=0.9,
            confidence_score=0.8,
            source_task_id="task-123",
            is_active=False,
        )
        db_session.add(memory)
        db_session.commit()
        db_session.refresh(memory)

        assert memory.content == {"command": "fuser -k 8000/tcp"}
        assert memory.content_hash == "sha256abc"
        assert memory.importance_score == 0.9
        assert memory.is_active is False


@pytest.mark.unit
class TestSkillModel:
    def test_create_skill_minimal(self, db_session: Session):
        skill = Skill(
            name="code-review",
            definition={"trigger": "review requested", "steps": ["analyze", "comment"]},
        )
        db_session.add(skill)
        db_session.commit()
        db_session.refresh(skill)

        assert skill.id is not None
        assert skill.name == "code-review"
        assert skill.definition == {"trigger": "review requested", "steps": ["analyze", "comment"]}
        assert skill.version == 1
        assert skill.status == SkillStatus.CANDIDATE
        assert skill.success_rate == 0.0
        assert skill.total_runs == 0
        assert skill.description is None
        assert skill.source_task_id is None


@pytest.mark.unit
class TestSkillRunModel:
    def test_create_skill_run(self, db_session: Session):
        skill = Skill(
            name="test-skill",
            definition={"steps": []},
        )
        db_session.add(skill)
        db_session.commit()

        run = SkillRun(
            skill_id=skill.id,
            task_id="task-99",
            success=True,
            metrics={"duration_ms": 150},
        )
        db_session.add(run)
        db_session.commit()
        db_session.refresh(run)

        assert run.id is not None
        assert run.skill_id == skill.id
        assert run.task_id == "task-99"
        assert run.success is True
        assert run.metrics == {"duration_ms": 150}
        assert run.error is None

    def test_skill_runs_relationship(self, db_session: Session):
        skill = Skill(name="multi-run", definition={"steps": []})
        db_session.add(skill)
        db_session.commit()

        run1 = SkillRun(skill_id=skill.id, task_id="t1", success=True)
        run2 = SkillRun(skill_id=skill.id, task_id="t2", success=False, error="timeout")
        db_session.add_all([run1, run2])
        db_session.commit()

        db_session.refresh(skill)
        assert len(skill.runs) == 2


@pytest.mark.unit
class TestApprovalModel:
    def test_create_approval_minimal(self, db_session: Session):
        approval = Approval(
            approval_type=ApprovalType.SKILL,
            target_id="skill-abc",
        )
        db_session.add(approval)
        db_session.commit()
        db_session.refresh(approval)

        assert approval.id is not None
        assert approval.approval_type == ApprovalType.SKILL
        assert approval.target_id == "skill-abc"
        assert approval.status == ApprovalStatus.PENDING
        assert approval.requested_by == "system"
        assert approval.approved_by is None
        assert approval.reason is None
        assert approval.resolved_at is None

    def test_create_approval_with_reason(self, db_session: Session):
        approval = Approval(
            approval_type=ApprovalType.HIGH_RISK_STEP,
            target_id="step-xyz",
            requested_by="agent",
            reason="Deleting production database",
        )
        db_session.add(approval)
        db_session.commit()
        db_session.refresh(approval)

        assert approval.approval_type == ApprovalType.HIGH_RISK_STEP
        assert approval.requested_by == "agent"
        assert approval.reason == "Deleting production database"


@pytest.mark.unit
class TestEditionProfileModel:
    def test_create_edition_profile(self, db_session: Session):
        profile = EditionProfile(
            edition=Edition.ENTERPRISE,
            name="default-enterprise",
            config={"max_concurrent_tasks": 10, "policy_engine": "strict"},
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)

        assert profile.id is not None
        assert profile.edition == Edition.ENTERPRISE
        assert profile.name == "default-enterprise"
        assert profile.config == {"max_concurrent_tasks": 10, "policy_engine": "strict"}
        assert profile.is_active is True

    def test_create_edition_profile_inactive(self, db_session: Session):
        profile = EditionProfile(
            edition=Edition.PERSONAL,
            name="old-personal",
            config={"max_concurrent_tasks": 1},
            is_active=False,
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)

        assert profile.is_active is False


@pytest.mark.unit
class TestEnumDefaults:
    def test_task_status_default(self, db_session: Session):
        task = Task(goal="check defaults")
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)
        assert task.status == TaskStatus.PENDING

    def test_step_status_default(self, db_session: Session):
        task = Task(goal="parent")
        db_session.add(task)
        db_session.commit()
        step = TaskStep(task_id=task.id, step_order=0, tool_name="bash")
        db_session.add(step)
        db_session.commit()
        db_session.refresh(step)
        assert step.status == StepStatus.PENDING

    def test_step_risk_level_default(self, db_session: Session):
        task = Task(goal="parent")
        db_session.add(task)
        db_session.commit()
        step = TaskStep(task_id=task.id, step_order=0, tool_name="bash")
        db_session.add(step)
        db_session.commit()
        db_session.refresh(step)
        assert step.risk_level == RiskLevel.LOW

    def test_approval_status_default(self, db_session: Session):
        approval = Approval(approval_type=ApprovalType.SKILL, target_id="x")
        db_session.add(approval)
        db_session.commit()
        db_session.refresh(approval)
        assert approval.status == ApprovalStatus.PENDING

    def test_skill_status_default(self, db_session: Session):
        skill = Skill(name="s", definition={})
        db_session.add(skill)
        db_session.commit()
        db_session.refresh(skill)
        assert skill.status == SkillStatus.CANDIDATE
