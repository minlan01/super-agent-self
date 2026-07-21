"""Full lifecycle E2E test -- create task, plan, execute, verify status, write memory, extract skill, query audit."""

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.agent_core.schemas import AuditEventCreate, TaskCreate
from packages.db.models import (
    AuditEventType,
    Base,
    MemoryType,
    SkillStatus,
    StepStatus,
    Task,
    TaskStatus,
)
from packages.db.repositories.audit_repo import AuditRepository
from packages.db.repositories.memory_repo import MemoryRepository
from packages.db.repositories.task_repo import TaskRepository
from packages.executor.executor_service import ExecutorService
from packages.executor.tool_runner import ToolRunner
from packages.executor.tools.base import ExecutionContext
from packages.executor.tools.file_tools import FileList, FileRead, FileWriteMarkdown
from packages.llm_gateway.mock_provider import MockProvider
from packages.llm_gateway.provider_router import ProviderRouter
from packages.memory.memory_service import MemoryService
from packages.memory.schemas import MemoryWriteRequest
from packages.memory.summarizer import MemorySummarizer
from packages.planner.plan_validator import Plan, PlanStep
from packages.planner.planner_service import PlannerService
from packages.policy.capability_token import TokenIssuer
from packages.policy.policy_engine import PolicyEngine
from packages.policy.tool_registry import ToolRegistry
from packages.skills.skill_extractor import SkillExtractor
from packages.skills.skill_service import SkillService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    session = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)()
    yield session
    session.close()


@pytest.fixture
def tool_registry():
    return ToolRegistry(config_path="configs/tools.yaml")


@pytest.fixture
def token_issuer():
    return TokenIssuer("e2e-lifecycle-secret", expire_minutes=5)


@pytest.fixture
def policy_engine(tool_registry, token_issuer):
    return PolicyEngine(tool_registry, token_issuer, config_path="configs/policy.yaml")


@pytest.fixture
def tool_runner(token_issuer):
    runner = ToolRunner(token_issuer)
    runner.register(FileWriteMarkdown())
    runner.register(FileRead())
    runner.register(FileList())
    return runner


@pytest.fixture
def mock_provider():
    """Create a MockProvider with a file-tools-only planning response."""
    plan_response = {
        "reasoning": "Write a markdown report and then read it back to verify.",
        "steps": [
            {
                "step_id": 1,
                "tool_name": "file.write_markdown",
                "args": {
                    "output_path": "lifecycle_report.md",
                    "content": "# Lifecycle Report\n\nThis is a full lifecycle E2E test.\n\n## Summary\n\nTask completed successfully.",
                },
                "reasoning": "Write the markdown report file.",
            },
            {
                "step_id": 2,
                "tool_name": "file.write_markdown",
                "args": {
                    "output_path": "summary.md",
                    "content": "# Summary\n\nA second file for skill extraction eligibility.",
                },
                "reasoning": "Write a second file to ensure multi-step plan.",
            },
        ],
    }
    return MockProvider({
        "name": "mock",
        "mock_config": {
            "planning_responses": {
                "lifecycle": json.dumps(plan_response),
            },
        },
    })


@pytest.fixture
def planner_service(tool_registry, mock_provider):
    return PlannerService(
        provider_router=_make_router(mock_provider),
        tool_registry=tool_registry,
        max_retries=1,
    )


@pytest.fixture
def memory_service():
    summarizer = MemorySummarizer(provider_router=None)
    return MemoryService(summarizer=summarizer)


@pytest.fixture
def skill_service():
    return SkillService()


def _make_router(mock_provider):
    """Create a minimal ProviderRouter that always uses the given provider."""
    from packages.llm_gateway.smart_router import SmartModelRouter
    from packages.llm_gateway.health_tracker import ProviderHealthTracker
    from packages.llm_gateway.cost_tracker import CostTracker

    router = ProviderRouter.__new__(ProviderRouter)
    router.providers = {"mock": mock_provider}
    router.default_provider = "mock"
    router.smart_router = SmartModelRouter()
    router.health_tracker = ProviderHealthTracker()
    router.cost_tracker = CostTracker()
    router.failover_chains = {}
    router.credential_pools = {}
    return router


def _create_task(db) -> Task:
    task = Task(id=str(uuid.uuid4()), goal="e2e full lifecycle test", user_id="default")
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# E2E: Full lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.asyncio
class TestFullLifecycle:
    async def test_complete_lifecycle(
        self,
        db_session,
        tool_runner,
        policy_engine,
        mock_provider,
        memory_service,
        skill_service,
        tmp_path,
    ):
        """Full lifecycle: create task -> plan -> execute -> verify -> memory -> skill -> audit."""

        # ── 1. Create a task via TaskRepository (mirrors API) ──────────────
        task_create = TaskCreate(goal="e2e full lifecycle test", user_id="default")
        task = TaskRepository.create(db_session, task_create)

        AuditRepository.create(db_session, AuditEventCreate(
            task_id=task.id,
            event_type=AuditEventType.TASK_CREATED,
            detail={"goal": task.goal},
        ))

        assert task.id is not None
        assert task.status == TaskStatus.PENDING

        # ── 2. Plan the task (using mock LLM provider) ───────────────────
        planner = PlannerService(
            provider_router=_make_router(mock_provider),
            tool_registry=ToolRegistry(config_path="configs/tools.yaml"),
            max_retries=1,
        )
        plan = await planner.plan(goal="e2e full lifecycle test", edition="enterprise")

        assert isinstance(plan, Plan)
        assert len(plan.steps) >= 1
        # Mock should return file tools only (no browser)
        for step in plan.steps:
            assert step.tool_name.startswith("file."), (
                f"Expected file tool, got {step.tool_name}"
            )

        AuditRepository.create(db_session, AuditEventCreate(
            task_id=task.id,
            event_type=AuditEventType.PLAN_GENERATED,
            detail={"steps": len(plan.steps)},
        ))

        # ── 3. Execute the plan ──────────────────────────────────────────
        service = ExecutorService(tool_runner=tool_runner, policy_engine=policy_engine)
        ctx = ExecutionContext(
            task_id=task.id,
            step_id="s1",
            workspace_root=str(tmp_path),
            outputs_dir="outputs",
        )

        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        assert result["success"] is True
        assert result["task_id"] == task.id
        assert all(r["status"] == "completed" for r in result["results"])

        # ── 4. Verify task status is COMPLETED ───────────────────────────
        db_session.refresh(task)
        assert task.status == TaskStatus.COMPLETED

        # Verify files were actually written
        assert (tmp_path / "outputs" / "lifecycle_report.md").is_file()
        assert (tmp_path / "outputs" / "summary.md").is_file()
        report_content = (tmp_path / "outputs" / "lifecycle_report.md").read_text(encoding="utf-8")
        assert "Lifecycle Report" in report_content

        # Verify step records
        steps = TaskRepository.get_steps(db_session, task.id)
        assert len(steps) == len(plan.steps)
        for step in steps:
            assert step.status == StepStatus.COMPLETED
            assert step.capability_token_hash is not None

        # ── 5. Write a memory from the completed task ────────────────────
        steps_summary = [
            {
                "step_id": s.step_order,
                "tool_name": s.tool_name,
                "status": "completed" if s.status == StepStatus.COMPLETED else s.status.value,
            }
            for s in steps
        ]

        memory_request = MemoryWriteRequest(
            task_id=task.id,
            goal=task.goal,
            steps_summary=steps_summary,
            success=True,
            memory_type=MemoryType.EXECUTION_EXPERIENCE,
        )

        memory = await memory_service.write_from_task(
            db_session, memory_request, user_id="default", edition="enterprise",
        )

        assert memory is not None
        assert memory.id is not None
        assert memory.source_task_id == task.id
        assert memory.memory_type == MemoryType.EXECUTION_EXPERIENCE
        assert memory.is_active is True

        # Verify memory was created in DB
        retrieved = MemoryRepository.get_by_id(db_session, memory.id)
        assert retrieved is not None
        assert retrieved.title == memory.title

        # ── 6. Extract a skill from the completed task ───────────────────
        extractor = SkillExtractor()
        extraction_steps = [
            {"tool_name": s.tool_name, "args": s.args or {}, "status": "completed"}
            for s in steps
        ]

        extraction_result = extractor.extract(
            goal=task.goal,
            steps=extraction_steps,
            success=True,
            min_steps=2,
        )

        # Should extract because we have 2+ completed steps
        assert extraction_result.extracted is True
        assert extraction_result.skill is not None

        # Save via SkillService
        skill = skill_service.on_task_completed(
            db_session,
            task_id=task.id,
            goal=task.goal,
            steps=extraction_steps,
            success=True,
            edition="enterprise",
        )

        assert skill is not None
        assert skill.id is not None
        assert skill.status == SkillStatus.CANDIDATE
        assert skill.source_task_id == task.id
        assert skill.version == 1

        # ── 7. Query audit trail ─────────────────────────────────────────
        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]

        # Core lifecycle events must be present
        assert AuditEventType.TASK_CREATED in event_types
        assert AuditEventType.PLAN_GENERATED in event_types
        assert AuditEventType.POLICY_APPROVED in event_types
        assert AuditEventType.STEP_EXECUTING in event_types
        assert AuditEventType.STEP_COMPLETED in event_types
        assert AuditEventType.TASK_COMPLETED in event_types
        assert AuditEventType.MEMORY_WRITTEN in event_types
        assert AuditEventType.SKILL_EXTRACTED in event_types

        # Verify execution audit counts match step count
        step_count = len(plan.steps)
        assert event_types.count(AuditEventType.POLICY_APPROVED) == step_count
        assert event_types.count(AuditEventType.STEP_EXECUTING) == step_count
        assert event_types.count(AuditEventType.STEP_COMPLETED) == step_count

        # Verify no failure events
        assert AuditEventType.POLICY_REJECTED not in event_types
        assert AuditEventType.STEP_FAILED not in event_types
        assert AuditEventType.TASK_FAILED not in event_types

    async def test_lifecycle_memory_deduplication(
        self,
        db_session,
        tool_runner,
        policy_engine,
        mock_provider,
        memory_service,
        tmp_path,
    ):
        """Writing the same memory twice should be deduplicated (second write returns None)."""
        # Create and execute a task
        task_create = TaskCreate(goal="dedup test task", user_id="default")
        task = TaskRepository.create(db_session, task_create)

        plan = Plan(
            reasoning="Write a file",
            steps=[
                PlanStep(
                    step_id=1,
                    tool_name="file.write_markdown",
                    args={"output_path": "dedup.md", "content": "# Dedup Test"},
                ),
                PlanStep(
                    step_id=2,
                    tool_name="file.write_markdown",
                    args={"output_path": "dedup2.md", "content": "# Dedup Test 2"},
                ),
            ],
        )

        service = ExecutorService(tool_runner=tool_runner, policy_engine=policy_engine)
        ctx = ExecutionContext(
            task_id=task.id, step_id="s1",
            workspace_root=str(tmp_path), outputs_dir="outputs",
        )
        await service.execute_plan(task.id, plan, ctx, db=db_session)

        # Write memory first time
        request = MemoryWriteRequest(
            task_id=task.id,
            goal="dedup test task",
            steps_summary=[{"step_id": 1, "tool_name": "file.write_markdown", "status": "completed"}],
            success=True,
        )
        memory1 = await memory_service.write_from_task(db_session, request)
        assert memory1 is not None

        # Write identical memory second time -- should be deduplicated
        memory2 = await memory_service.write_from_task(db_session, request)
        assert memory2 is None  # Deduplicated

    async def test_lifecycle_skill_not_extracted_from_failed_task(
        self,
        db_session,
        skill_service,
    ):
        """Skill extraction from a failed task must return None."""
        extractor = SkillExtractor()
        steps = [
            {"tool_name": "file.write_markdown", "args": {}, "status": "failed"},
            {"tool_name": "file.read", "args": {}, "status": "completed"},
        ]

        result = extractor.extract(goal="failed task", steps=steps, success=False)
        assert result.extracted is False
        assert "failed" in result.reason.lower()

        # SkillService.on_task_completed should also return None
        skill = skill_service.on_task_completed(
            db_session, task_id="fake-id", goal="failed task",
            steps=steps, success=False,
        )
        assert skill is None

    async def test_lifecycle_audit_trail_for_rejected_step(
        self,
        db_session,
        tool_runner,
        policy_engine,
        tmp_path,
    ):
        """A plan with a forbidden tool must produce POLICY_REJECTED and TASK_FAILED audit events."""
        task = _create_task(db_session)

        plan = Plan(
            reasoning="Try forbidden tool",
            steps=[
                PlanStep(
                    step_id=1,
                    tool_name="shell.run",
                    args={"command": "echo hello"},
                ),
            ],
        )

        service = ExecutorService(tool_runner=tool_runner, policy_engine=policy_engine)
        ctx = ExecutionContext(task_id=task.id, step_id="s1", workspace_root=str(tmp_path))
        result = await service.execute_plan(task.id, plan, ctx, db=db_session)

        assert result["success"] is False

        db_session.refresh(task)
        assert task.status == TaskStatus.FAILED

        events = AuditRepository.list_by_task(db_session, task.id)
        event_types = [e.event_type for e in events]

        assert AuditEventType.POLICY_REJECTED in event_types
        assert AuditEventType.TASK_FAILED in event_types
        assert AuditEventType.TASK_COMPLETED not in event_types
