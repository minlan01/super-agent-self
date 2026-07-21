"""Tests for Skill system — extractor, registry, evaluator, service."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.db.models import Base, SkillStatus
from packages.skills.schemas import SkillDefinition
from packages.skills.skill_evaluator import SkillEvaluator
from packages.skills.skill_extractor import SkillExtractor
from packages.skills.skill_registry import SkillRegistryService
from packages.skills.skill_service import SkillService


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def extractor():
    return SkillExtractor()


@pytest.fixture
def sample_steps():
    return [
        {"step_id": 1, "tool_name": "browser.open", "args": {"url": "https://example.com"}, "status": "completed"},
        {"step_id": 2, "tool_name": "browser.extract_text", "args": {"selectors": ["h1"]}, "status": "completed"},
        {"step_id": 3, "tool_name": "file.write_docx", "args": {"output_path": "report.docx"}, "status": "completed"},
    ]


# ── SkillExtractor ───────────────────────────────────────────────────────────


class TestSkillExtractor:
    def test_extract_success(self, extractor, sample_steps):
        result = extractor.extract("Open website and extract text", sample_steps, success=True)
        assert result.extracted
        assert result.skill is not None
        assert len(result.skill.steps_template) == 3
        assert "browser" in result.skill.tags

    def test_extract_failure_no_skill(self, extractor, sample_steps):
        result = extractor.extract("Open website", sample_steps, success=False)
        assert not result.extracted
        assert "failed" in result.reason.lower()

    def test_extract_too_few_steps(self, extractor):
        steps = [{"step_id": 1, "tool_name": "browser.open", "status": "completed"}]
        result = extractor.extract("Open website", steps, success=True, min_steps=2)
        assert not result.extracted
        assert "at least" in result.reason.lower()

    def test_extract_filters_rejected_steps(self, extractor):
        steps = [
            {"step_id": 1, "tool_name": "browser.open", "status": "completed"},
            {"step_id": 2, "tool_name": "shell.run", "status": "rejected"},
            {"step_id": 3, "tool_name": "file.write_docx", "status": "completed"},
        ]
        result = extractor.extract("Do things", steps, success=True, min_steps=2)
        assert result.extracted
        assert len(result.skill.steps_template) == 2

    def test_generate_name(self, extractor):
        name = extractor._generate_name("Open the browser and extract text")
        assert "browser" in name
        assert "extract" in name

    def test_generalize_args_url(self, extractor):
        result = extractor._generalize_args({"url": "https://example.com"})
        assert result["url"] == "{{url}}"

    def test_generalize_args_preserves_short(self, extractor):
        result = extractor._generalize_args({"title": "Hello"})
        assert result["title"] == "Hello"


# ── SkillRegistryService ─────────────────────────────────────────────────────


class TestSkillRegistryService:
    def test_create_skill(self):
        db = _make_session()
        registry = SkillRegistryService()
        definition = SkillDefinition(
            name="web_scrape",
            description="Scrape website",
            steps_template=[
                {"step_id": 1, "tool_name": "browser.open"},
                {"step_id": 2, "tool_name": "browser.extract_text"},
            ],
            tags=["browser"],
        )
        skill = registry.create(db, definition, source_task_id="t1")
        assert skill.name == "web_scrape"
        assert skill.status == SkillStatus.CANDIDATE
        assert skill.version == 1
        db.close()

    def test_approve_skill(self):
        db = _make_session()
        registry = SkillRegistryService()
        definition = SkillDefinition(name="test_skill", steps_template=[
            {"step_id": 1, "tool_name": "browser.open"},
            {"step_id": 2, "tool_name": "file.write_docx"},
        ])
        skill = registry.create(db, definition)
        approved = registry.approve(db, skill.id)
        assert approved.status == SkillStatus.STABLE
        db.close()

    def test_approve_non_candidate_fails(self):
        db = _make_session()
        registry = SkillRegistryService()
        definition = SkillDefinition(name="test_skill", steps_template=[
            {"step_id": 1, "tool_name": "browser.open"},
            {"step_id": 2, "tool_name": "file.write_docx"},
        ])
        skill = registry.create(db, definition)
        registry.approve(db, skill.id)
        with pytest.raises(ValueError, match="candidate"):
            registry.approve(db, skill.id)
        db.close()

    def test_disable_and_rollback(self):
        db = _make_session()
        registry = SkillRegistryService()
        definition = SkillDefinition(name="test_skill", steps_template=[
            {"step_id": 1, "tool_name": "browser.open"},
            {"step_id": 2, "tool_name": "file.write_docx"},
        ])
        skill = registry.create(db, definition)
        registry.approve(db, skill.id)
        disabled = registry.disable(db, skill.id)
        assert disabled.status == SkillStatus.DISABLED
        rolled_back = registry.rollback(db, skill.id)
        assert rolled_back.status == SkillStatus.STABLE
        db.close()

    def test_version_bump_on_change(self):
        db = _make_session()
        registry = SkillRegistryService()
        def1 = SkillDefinition(name="web_scrape", steps_template=[
            {"step_id": 1, "tool_name": "browser.open"},
            {"step_id": 2, "tool_name": "browser.extract_text"},
        ])
        s1 = registry.create(db, def1)
        assert s1.version == 1

        def2 = SkillDefinition(name="web_scrape", steps_template=[
            {"step_id": 1, "tool_name": "browser.open"},
            {"step_id": 2, "tool_name": "browser.click"},
        ])
        s2 = registry.create(db, def2)
        assert s2.version == 2
        db.close()

    def test_duplicate_definition_no_new_version(self):
        db = _make_session()
        registry = SkillRegistryService()
        definition = SkillDefinition(name="web_scrape", steps_template=[
            {"step_id": 1, "tool_name": "browser.open"},
            {"step_id": 2, "tool_name": "browser.extract_text"},
        ])
        s1 = registry.create(db, definition)
        s2 = registry.create(db, definition)
        assert s1.id == s2.id


# ── SkillEvaluator ───────────────────────────────────────────────────────────


class TestSkillEvaluator:
    def _create_approved_skill(self, db):
        registry = SkillRegistryService()
        definition = SkillDefinition(name="test_skill", steps_template=[
            {"step_id": 1, "tool_name": "browser.open"},
            {"step_id": 2, "tool_name": "file.write_docx"},
        ])
        skill = registry.create(db, definition)
        return registry.approve(db, skill.id)

    def test_record_success_run(self):
        db = _make_session()
        skill = self._create_approved_skill(db)
        evaluator = SkillEvaluator()
        run = evaluator.record_run(db, skill.id, "t1", success=True)
        assert run.success
        db.close()

    def test_consecutive_failures_degrade(self):
        db = _make_session()
        skill = self._create_approved_skill(db)
        evaluator = SkillEvaluator()
        for i in range(3):
            evaluator.record_run(db, skill.id, f"t{i}", success=False)

        from packages.db.models import Skill
        refreshed = db.get(Skill, skill.id)
        assert refreshed.status == SkillStatus.DISABLED
        db.close()

    def test_no_degrade_on_mixed_results(self):
        db = _make_session()
        skill = self._create_approved_skill(db)
        evaluator = SkillEvaluator()
        # 4 runs: 3 success first, then 1 failure → 75% rate, above 70%
        evaluator.record_run(db, skill.id, "t1", success=True)
        evaluator.record_run(db, skill.id, "t2", success=True)
        evaluator.record_run(db, skill.id, "t3", success=True)
        # 4th run failure: rate = 3/4 = 75%, consecutive = 1 → no degrade
        evaluator.record_run(db, skill.id, "t4", success=False)

        from packages.db.models import Skill
        refreshed = db.get(Skill, skill.id)
        assert refreshed.status == SkillStatus.STABLE
        db.close()


# ── SkillService ─────────────────────────────────────────────────────────────


class TestSkillService:
    def test_on_task_completed_extracts_skill(self):
        db = _make_session()
        service = SkillService()
        steps = [
            {"step_id": 1, "tool_name": "browser.open", "status": "completed"},
            {"step_id": 2, "tool_name": "file.write_docx", "status": "completed"},
        ]
        skill = service.on_task_completed(
            db, task_id="t1", goal="Open website and save report",
            steps=steps, success=True,
        )
        assert skill is not None
        assert skill.status == SkillStatus.CANDIDATE
        db.close()

    def test_on_task_failed_no_extraction(self):
        db = _make_session()
        service = SkillService()
        steps = [{"step_id": 1, "tool_name": "browser.open", "status": "failed"}]
        result = service.on_task_completed(
            db, task_id="t1", goal="Failed task",
            steps=steps, success=False,
        )
        assert result is None
        db.close()

    def test_approve_skill(self):
        db = _make_session()
        service = SkillService()
        steps = [
            {"step_id": 1, "tool_name": "browser.open", "status": "completed"},
            {"step_id": 2, "tool_name": "file.write_docx", "status": "completed"},
        ]
        skill = service.on_task_completed(
            db, task_id="t1", goal="Open website and save report",
            steps=steps, success=True,
        )
        approved = service.approve_skill(db, skill.id)
        assert approved.status == SkillStatus.STABLE
        db.close()

    def test_get_skills_for_planner(self):
        db = _make_session()
        service = SkillService()
        steps = [
            {"step_id": 1, "tool_name": "browser.open", "status": "completed"},
            {"step_id": 2, "tool_name": "browser.extract_text", "status": "completed"},
        ]
        skill = service.on_task_completed(
            db, task_id="t1", goal="Open website and extract text",
            steps=steps, success=True,
        )
        service.approve_skill(db, skill.id)

        planner_skills = service.get_skills_for_planner(db, goal="Open browser and extract content")
        assert len(planner_skills) >= 1
        assert planner_skills[0]["name"] is not None
        db.close()
