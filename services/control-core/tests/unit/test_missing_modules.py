"""Unit tests for previously untested modules — risk_rules, importance_scorer, skill_evaluator, mcp_tool_adapter, edition_repo."""

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.agent_core.schemas import Edition, EditionProfileCreate
from packages.db.models import (
    Base,
    MemoryType,
    Skill,
    SkillRun,
    SkillStatus,
)
from packages.db.repositories.edition_repo import EditionRepository
from packages.mcp.mcp_tool_adapter import (
    MCPToolAdapter,
    register_mcp_tools,
    register_mcp_tools_async,
)
from packages.memory.importance_scorer import ImportanceScorer
from packages.policy import risk_rules
from packages.skills.skill_evaluator import SkillEvaluator

# ── Shared fixtures ────────────────────────────────────────────────────────


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


# ── 1. risk_rules — additional coverage ────────────────────────────────────
# Note: TestRiskRules in test_policy.py covers check_url_allowed, check_forbidden_path,
# check_tool_allowed, check_risk_level, check_path_in_workspace, check_args_hash.
# Here we add coverage for check_tool_enabled, edge cases, and path traversal.


@pytest.mark.unit
class TestRiskRulesExtended:
    def test_check_tool_enabled_registered_and_enabled(self):
        registry = MagicMock()
        registry.is_registered.return_value = True
        registry.is_enabled.return_value = True
        ok, reason = risk_rules.check_tool_enabled(registry, "browser.open")
        assert ok is True
        assert reason == ""

    def test_check_tool_enabled_not_registered(self):
        registry = MagicMock()
        registry.is_registered.return_value = False
        ok, reason = risk_rules.check_tool_enabled(registry, "unknown.tool")
        assert ok is False
        assert "not registered" in reason

    def test_check_tool_enabled_disabled(self):
        registry = MagicMock()
        registry.is_registered.return_value = True
        registry.is_enabled.return_value = False
        ok, reason = risk_rules.check_tool_enabled(registry, "shell.run")
        assert ok is False
        assert "disabled" in reason

    def test_check_path_in_workspace_traversal_attack(self):
        ok, reason = risk_rules.check_path_in_workspace("../../etc/passwd", "/home/user/workspace")
        assert ok is False
        assert "outside workspace" in reason

    def test_check_path_in_workspace_dotdot_normalized(self):
        ok, reason = risk_rules.check_path_in_workspace("./output.txt", "/home/user/workspace")
        assert ok is True

    def test_check_path_in_workspace_deep_subdirectory(self):
        ok, reason = risk_rules.check_path_in_workspace(
            "subdir/deep/nested/file.txt", "/home/user/workspace"
        )
        assert ok is True

    def test_check_risk_level_unknown_defaults_low(self):
        ok, reason = risk_rules.check_risk_level("unknown_level", "high")
        assert ok is True

    def test_check_risk_level_equal_ok(self):
        ok, reason = risk_rules.check_risk_level("high", "high")
        assert ok is True

    def test_check_risk_level_unknown_max_defaults_high(self):
        ok, reason = risk_rules.check_risk_level("critical", "unknown_max")
        # unknown_max defaults to 2 (high), critical is 3 -> exceeds
        assert ok is False

    def test_check_args_hash_empty_dict(self):
        args = {}
        expected = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]
        ok, reason = risk_rules.check_args_hash(args, expected)
        assert ok is True

    def test_check_args_hash_nested(self):
        args = {"a": {"b": 1, "c": [2, 3]}}
        expected = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]
        ok, reason = risk_rules.check_args_hash(args, expected)
        assert ok is True

    def test_check_forbidden_path_empty_list(self):
        ok, reason = risk_rules.check_forbidden_path("/etc/passwd", [])
        assert ok is True

    def test_check_url_allowed_empty_patterns(self):
        ok, reason = risk_rules.check_url_allowed("https://anything.com", [])
        assert ok is True

    def test_check_url_allowed_multiple_patterns(self):
        ok, reason = risk_rules.check_url_allowed(
            "http://evil.com", [r"evil\.com", r"bad\.org"]
        )
        assert ok is False

    def test_check_tool_allowed_empty_forbidden(self):
        ok, reason = risk_rules.check_tool_allowed("any.tool", [])
        assert ok is True


# ── 2. importance_scorer ───────────────────────────────────────────────────


@pytest.mark.unit
class TestImportanceScorer:
    @pytest.fixture
    def scorer(self):
        return ImportanceScorer()

    def test_score_default_params(self, scorer):
        result = scorer.score(MemoryType.DOMAIN_KNOWLEDGE)
        assert 0.0 <= result <= 1.0
        # base=0.5, type_weight=0.7 -> 0.4*0.5 + 0.6*0.7 = 0.62
        assert result == 0.62

    def test_score_error_solution_high(self, scorer):
        result = scorer.score(MemoryType.ERROR_SOLUTION)
        # type_weight=0.9 -> 0.4*0.5 + 0.6*0.9 = 0.74
        assert result == 0.74

    def test_score_daily_context_low(self, scorer):
        result = scorer.score(MemoryType.DAILY_CONTEXT)
        # type_weight=0.4 -> 0.4*0.5 + 0.6*0.4 = 0.44
        assert result == 0.44

    def test_score_failure_boost(self, scorer):
        success_score = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, success=True)
        failure_score = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, success=False)
        assert failure_score > success_score

    def test_score_failure_does_not_exceed_1(self, scorer):
        # Even with high base + failure + many steps, capped at 1.0
        result = scorer.score(
            MemoryType.ERROR_SOLUTION,
            base_importance=1.0,
            success=False,
            step_count=10,
            is_unique=True,
        )
        assert result == 1.0

    def test_score_complex_task_boost(self, scorer):
        few_steps = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, step_count=1)
        many_steps = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, step_count=8)
        assert many_steps > few_steps

    def test_score_step_count_4_boost(self, scorer):
        zero_steps = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, step_count=0)
        four_steps = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, step_count=4)
        assert four_steps > zero_steps

    def test_score_step_count_5_no_boost(self, scorer):
        four_steps = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, step_count=4)
        five_steps = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, step_count=5)
        # step_count 5 is not > 5 and not > 3, so no boost over step_count 5
        # Actually 5 > 3 -> +0.05 boost, same as 4. So they should be equal.
        assert four_steps == five_steps

    def test_score_duplicate_penalty(self, scorer):
        unique_score = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, is_unique=True)
        dup_score = scorer.score(MemoryType.DOMAIN_KNOWLEDGE, is_unique=False)
        assert dup_score < unique_score

    def test_score_duplicate_penalty_floor(self, scorer):
        # Very low base + duplicate should not go below 0.0
        result = scorer.score(
            MemoryType.DAILY_CONTEXT,
            base_importance=0.0,
            is_unique=False,
        )
        assert result >= 0.0

    def test_score_returns_rounded(self, scorer):
        result = scorer.score(MemoryType.USER_PREFERENCE)
        # Should be rounded to 2 decimal places
        assert result == round(result, 2)

    def test_score_all_memory_types(self, scorer):
        for mt in MemoryType:
            result = scorer.score(mt)
            assert 0.0 <= result <= 1.0, f"Failed for {mt.value}: {result}"

    def test_should_retrieve_both_above_threshold(self, scorer):
        assert scorer.should_retrieve(0.8, 0.9) is True

    def test_should_retrieve_importance_below(self, scorer):
        assert scorer.should_retrieve(0.2, 0.9) is False

    def test_should_retrieve_confidence_below(self, scorer):
        assert scorer.should_retrieve(0.8, 0.3) is False

    def test_should_retrieve_both_below(self, scorer):
        assert scorer.should_retrieve(0.1, 0.1) is False

    def test_should_retrieve_custom_thresholds(self, scorer):
        assert scorer.should_retrieve(0.5, 0.5, min_importance=0.6) is False
        assert scorer.should_retrieve(0.7, 0.5, min_importance=0.6) is True

    def test_should_retrieve_exact_threshold(self, scorer):
        assert scorer.should_retrieve(0.3, 0.5) is True
        assert scorer.should_retrieve(0.5, 0.3) is False


# ── 3. skill_evaluator — extended coverage ────────────────────────────────
# Note: TestSkillEvaluator in test_skills.py covers record_success_run,
# consecutive_failures_degrade, no_degrade_on_mixed_results.
# Here we add degradation checks, config loading, and edge cases.


@pytest.mark.unit
class TestSkillEvaluatorExtended:
    @pytest.fixture
    def evaluator_no_config(self, tmp_path):
        """Evaluator with a nonexistent config path (uses defaults)."""
        return SkillEvaluator(config_path=str(tmp_path / "nonexistent.yaml"))

    def _create_stable_skill(self, db: Session) -> Skill:
        """Create a skill in STABLE status for testing."""
        skill = Skill(
            name="test_skill",
            status=SkillStatus.STABLE,
            definition={"steps": ["step1"]},
            success_rate=1.0,
            total_runs=0,
        )
        db.add(skill)
        db.commit()
        db.refresh(skill)
        return skill

    def _add_runs(self, db: Session, skill_id: str, results: list[bool]) -> list[SkillRun]:
        """Add skill runs with given success/failure results."""
        runs = []
        for i, success in enumerate(results):
            run = SkillRun(
                skill_id=skill_id,
                task_id=f"task-{i}",
                success=success,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            runs.append(run)
        return runs

    def test_check_degradation_not_found(self, db_session, evaluator_no_config):
        check = evaluator_no_config.check_degradation(db_session, "nonexistent-id")
        assert check.should_degrade is False
        assert "Not found" in check.reason

    def test_check_degradation_non_stable_skill(self, db_session, evaluator_no_config):
        skill = Skill(
            name="candidate_skill",
            status=SkillStatus.CANDIDATE,
            definition={"steps": []},
        )
        db_session.add(skill)
        db_session.commit()
        db_session.refresh(skill)

        check = evaluator_no_config.check_degradation(db_session, skill.id)
        assert check.should_degrade is False
        assert "not monitored" in check.reason

    def test_check_degradation_no_runs(self, db_session, evaluator_no_config):
        skill = self._create_stable_skill(db_session)
        check = evaluator_no_config.check_degradation(db_session, skill.id)
        assert check.should_degrade is False
        assert check.consecutive_failures == 0
        assert check.current_success_rate == 1.0

    def test_check_degradation_low_success_rate(self, db_session, evaluator_no_config):
        skill = self._create_stable_skill(db_session)
        skill.success_rate = 0.5
        db_session.commit()

        # Add 3+ runs so success rate check kicks in
        self._add_runs(db_session, skill.id, [True, False, False])

        check = evaluator_no_config.check_degradation(db_session, skill.id)
        assert check.should_degrade is True
        assert "Success rate" in check.reason

    def test_check_degradation_custom_config(self, tmp_path):
        config_file = tmp_path / "skills.yaml"
        config_file.write_text(
            "skills:\n"
            "  degradation:\n"
            "    consecutive_failures: 2\n"
            "    min_success_rate: 0.5\n"
            "    action: deprecate\n"
        )
        evaluator = SkillEvaluator(config_path=str(config_file))
        assert evaluator.consecutive_failures_limit == 2
        assert evaluator.min_success_rate == 0.5
        assert evaluator.degradation_action == "deprecate"

    def test_degrade_action_deprecate(self, db_session, tmp_path):
        config_file = tmp_path / "skills.yaml"
        config_file.write_text(
            "skills:\n"
            "  degradation:\n"
            "    consecutive_failures: 2\n"
            "    action: deprecate\n"
        )
        evaluator = SkillEvaluator(config_path=str(config_file))
        skill = self._create_stable_skill(db_session)
        self._add_runs(db_session, skill.id, [False, False])

        # Trigger degradation
        check = evaluator.check_degradation(db_session, skill.id)
        assert check.should_degrade is True
        evaluator._degrade(db_session, skill.id, check.reason)

        db_session.refresh(skill)
        assert skill.status == SkillStatus.DEPRECATED

    def test_check_degradation_success_rate_below_threshold_needs_3_runs(
        self, db_session, evaluator_no_config
    ):
        skill = self._create_stable_skill(db_session)
        skill.success_rate = 0.3
        db_session.commit()

        # Only 2 runs — should NOT degrade (need >= 3)
        self._add_runs(db_session, skill.id, [True, False])
        check = evaluator_no_config.check_degradation(db_session, skill.id)
        assert check.should_degrade is False

    def test_record_run_with_metrics(self, db_session, evaluator_no_config):
        skill = self._create_stable_skill(db_session)
        with patch.object(evaluator_no_config, "_update_metrics"):
            with patch.object(evaluator_no_config, "check_degradation") as mock_check:
                mock_check.return_value = MagicMock(should_degrade=False)
                run = evaluator_no_config.record_run(
                    db_session, skill.id, "task-1",
                    success=True, metrics={"duration_ms": 150},
                )
        assert run.success is True
        assert run.metrics == {"duration_ms": 150}

    def test_record_run_with_error(self, db_session, evaluator_no_config):
        skill = self._create_stable_skill(db_session)
        with patch.object(evaluator_no_config, "_update_metrics"):
            with patch.object(evaluator_no_config, "check_degradation") as mock_check:
                mock_check.return_value = MagicMock(should_degrade=False)
                run = evaluator_no_config.record_run(
                    db_session, skill.id, "task-1",
                    success=False, error="Connection timeout",
                )
        assert run.success is False
        assert run.error == "Connection timeout"


# ── 4. mcp_tool_adapter ────────────────────────────────────────────────────


@pytest.mark.unit
class TestMCPToolAdapter:
    def test_adapter_init_with_name_and_description(self):
        client = MagicMock()
        tool_info = {"name": "mcp.search", "description": "Search the web"}
        adapter = MCPToolAdapter(client, tool_info)
        assert adapter.name == "mcp.search"
        assert adapter.description == "Search the web"

    def test_adapter_init_defaults(self):
        client = MagicMock()
        adapter = MCPToolAdapter(client, {})
        assert adapter.name == "mcp.unknown"
        assert adapter.description == ""

    def test_adapter_stores_input_schema(self):
        client = MagicMock()
        tool_info = {"name": "tool1", "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}}
        adapter = MCPToolAdapter(client, tool_info)
        assert adapter._input_schema["type"] == "object"
        assert "q" in adapter._input_schema["properties"]

    @pytest.mark.asyncio
    async def test_adapter_execute_success(self):
        client = MagicMock()
        client.call_tool = AsyncMock(return_value={"result": "ok"})
        tool_info = {"name": "mcp.echo", "description": "Echo tool"}
        adapter = MCPToolAdapter(client, tool_info)

        context = MagicMock()
        result = await adapter.execute({"msg": "hello"}, context)
        assert result.success is True
        assert result.output == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_adapter_execute_failure(self):
        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=RuntimeError("MCP server down"))
        tool_info = {"name": "mcp.broken", "description": "Broken tool"}
        adapter = MCPToolAdapter(client, tool_info)

        context = MagicMock()
        result = await adapter.execute({}, context)
        assert result.success is False
        assert "MCP server down" in result.error

    @pytest.mark.asyncio
    async def test_adapter_execute_preserves_error_message(self):
        client = MagicMock()
        client.call_tool = AsyncMock(side_effect=ValueError("invalid argument"))
        tool_info = {"name": "mcp.bad", "description": "Bad tool"}
        adapter = MCPToolAdapter(client, tool_info)

        context = MagicMock()
        result = await adapter.execute({"x": -1}, context)
        assert result.success is False
        assert "invalid argument" in result.error


@pytest.mark.unit
class TestRegisterMCPTools:
    def test_register_mcp_tools_sync(self):
        async def fake_list_tools():
            return [
                {"name": "mcp.tool_a", "description": "Tool A"},
                {"name": "mcp.tool_b", "description": "Tool B"},
            ]

        mcp_client = MagicMock()
        mcp_client.list_tools = fake_list_tools
        tool_runner = MagicMock()

        adapters = register_mcp_tools(tool_runner, mcp_client)
        assert len(adapters) == 2
        assert adapters[0].name == "mcp.tool_a"
        assert adapters[1].name == "mcp.tool_b"
        assert tool_runner.register.call_count == 2

    def test_register_mcp_tools_empty(self):
        async def fake_list_tools_empty():
            return []

        mcp_client = MagicMock()
        mcp_client.list_tools = fake_list_tools_empty
        tool_runner = MagicMock()

        adapters = register_mcp_tools(tool_runner, mcp_client)
        assert len(adapters) == 0
        tool_runner.register.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_mcp_tools_async(self):
        mcp_client = MagicMock()
        mcp_client.list_tools = AsyncMock(return_value=[
            {"name": "mcp.async_tool", "description": "Async Tool"},
        ])
        tool_runner = MagicMock()

        adapters = await register_mcp_tools_async(tool_runner, mcp_client)
        assert len(adapters) == 1
        assert adapters[0].name == "mcp.async_tool"
        tool_runner.register.assert_called_once()


# ── 5. edition_repo ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestEditionRepository:
    def test_create_enterprise(self, db_session: Session):
        schema = EditionProfileCreate(
            edition=Edition.ENTERPRISE,
            name="enterprise-default",
            config={"max_tasks": 100, "features": ["browser", "memory"]},
        )
        profile = EditionRepository.create(db_session, schema)
        assert profile.id is not None
        assert profile.edition == Edition.ENTERPRISE
        assert profile.name == "enterprise-default"
        assert profile.config["max_tasks"] == 100
        assert profile.is_active is True

    def test_create_personal(self, db_session: Session):
        schema = EditionProfileCreate(
            edition=Edition.PERSONAL,
            name="personal-default",
            config={"max_tasks": 10, "features": ["browser"]},
        )
        profile = EditionRepository.create(db_session, schema)
        assert profile.edition == Edition.PERSONAL
        assert profile.name == "personal-default"

    def test_get_active_returns_latest(self, db_session: Session):
        for i in range(3):
            schema = EditionProfileCreate(
                edition=Edition.ENTERPRISE,
                name=f"profile-{i}",
                config={"index": i},
            )
            EditionRepository.create(db_session, schema)

        active = EditionRepository.get_active(db_session, Edition.ENTERPRISE)
        assert active is not None
        assert active.name == "profile-2"
        assert active.config["index"] == 2

    def test_get_active_skips_inactive(self, db_session: Session):
        schema1 = EditionProfileCreate(
            edition=Edition.PERSONAL,
            name="old-profile",
            config={"v": 1},
        )
        p1 = EditionRepository.create(db_session, schema1)

        # Deactivate the first one
        p1.is_active = False
        db_session.commit()

        schema2 = EditionProfileCreate(
            edition=Edition.PERSONAL,
            name="new-profile",
            config={"v": 2},
        )
        EditionRepository.create(db_session, schema2)

        active = EditionRepository.get_active(db_session, Edition.PERSONAL)
        assert active is not None
        assert active.name == "new-profile"

    def test_get_active_no_profiles(self, db_session: Session):
        active = EditionRepository.get_active(db_session, Edition.ENTERPRISE)
        assert active is None

    def test_get_active_all_inactive(self, db_session: Session):
        schema = EditionProfileCreate(
            edition=Edition.ENTERPRISE,
            name="inactive-profile",
            config={},
        )
        p = EditionRepository.create(db_session, schema)
        p.is_active = False
        db_session.commit()

        active = EditionRepository.get_active(db_session, Edition.ENTERPRISE)
        assert active is None

    def test_list_profiles_all(self, db_session: Session):
        EditionRepository.create(db_session, EditionProfileCreate(
            edition=Edition.ENTERPRISE, name="ent-1", config={}
        ))
        EditionRepository.create(db_session, EditionProfileCreate(
            edition=Edition.PERSONAL, name="pers-1", config={}
        ))
        EditionRepository.create(db_session, EditionProfileCreate(
            edition=Edition.ENTERPRISE, name="ent-2", config={}
        ))

        all_profiles = EditionRepository.list_profiles(db_session)
        assert len(all_profiles) == 3

    def test_list_profiles_filtered_by_edition(self, db_session: Session):
        EditionRepository.create(db_session, EditionProfileCreate(
            edition=Edition.ENTERPRISE, name="ent-1", config={}
        ))
        EditionRepository.create(db_session, EditionProfileCreate(
            edition=Edition.PERSONAL, name="pers-1", config={}
        ))
        EditionRepository.create(db_session, EditionProfileCreate(
            edition=Edition.ENTERPRISE, name="ent-2", config={}
        ))

        enterprise = EditionRepository.list_profiles(db_session, edition=Edition.ENTERPRISE)
        assert len(enterprise) == 2
        for p in enterprise:
            assert p.edition == Edition.ENTERPRISE

        personal = EditionRepository.list_profiles(db_session, edition=Edition.PERSONAL)
        assert len(personal) == 1

    def test_list_profiles_ordered_by_created_at_desc(self, db_session: Session):
        for i in range(5):
            EditionRepository.create(db_session, EditionProfileCreate(
                edition=Edition.ENTERPRISE,
                name=f"profile-{i}",
                config={"i": i},
            ))

        profiles = EditionRepository.list_profiles(db_session, edition=Edition.ENTERPRISE)
        assert len(profiles) == 5
        # Most recent first — profile-4 should be first
        assert profiles[0].name == "profile-4"
        assert profiles[-1].name == "profile-0"

    def test_list_profiles_empty(self, db_session: Session):
        profiles = EditionRepository.list_profiles(db_session)
        assert profiles == []

    def test_create_preserves_config_dict(self, db_session: Session):
        complex_config = {
            "features": ["browser", "memory", "voice"],
            "limits": {"max_concurrent": 5, "timeout": 300},
            "nested": {"deep": {"value": True}},
        }
        schema = EditionProfileCreate(
            edition=Edition.ENTERPRISE,
            name="complex-profile",
            config=complex_config,
        )
        profile = EditionRepository.create(db_session, schema)
        assert profile.config == complex_config
        assert profile.config["nested"]["deep"]["value"] is True
