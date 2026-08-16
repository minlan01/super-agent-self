"""Tests for Sprint 9-10 — EditionManager, Personal Tools, ReminderService, PersonalContextService, Personal Prompts."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.db.models import Base, MemoryType
from packages.memory.memory_service import MemoryService
from packages.memory.summarizer import MemorySummarizer
from packages.personal_context.personal_context_service import PersonalContextService


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


# ── EditionManager ────────────────────────────────────────────────────────────


class TestEditionManager:
    def setup_method(self):
        from packages.agent_core.edition_manager import EditionManager
        # Use the real configs/editions directory
        editions_dir = str(Path(__file__).resolve().parent.parent.parent / "configs" / "editions")
        self.mgr = EditionManager(editions_dir=editions_dir)

    def test_loads_both_editions(self):
        editions = self.mgr.list_editions()
        assert "personal" in editions
        assert "enterprise" in editions

    def test_get_config_returns_dict(self):
        cfg = self.mgr.get_config("personal")
        assert isinstance(cfg, dict)
        assert cfg["edition"] == "personal"

    def test_get_config_unknown_edition(self):
        cfg = self.mgr.get_config("nonexistent")
        assert cfg == {}

    def test_get_enabled_tools_personal(self):
        tools = self.mgr.get_enabled_tools("personal")
        assert "browser.open" in tools
        assert "file.search" in tools
        assert "file.summarize" in tools

    def test_get_enabled_tools_enterprise(self):
        tools = self.mgr.get_enabled_tools("enterprise")
        assert "browser.open" in tools
        # file.search is NOT in enterprise
        assert "file.search" not in tools

    def test_get_disabled_tools_personal(self):
        tools = self.mgr.get_disabled_tools("personal")
        assert "shell.run" in tools

    def test_get_memory_types_personal(self):
        types = self.mgr.get_memory_types("personal")
        assert "user_preference" in types
        assert "reminder" in types
        assert "daily_context" in types

    def test_get_memory_types_enterprise(self):
        types = self.mgr.get_memory_types("enterprise")
        assert "execution_experience" in types
        assert "domain_knowledge" in types

    def test_get_retention_days_personal(self):
        assert self.mgr.get_retention_days("personal") == 365

    def test_get_retention_days_enterprise(self):
        assert self.mgr.get_retention_days("enterprise") == 90

    def test_is_personal(self):
        assert self.mgr.is_personal("personal") is True
        assert self.mgr.is_personal("enterprise") is False

    def test_is_enterprise(self):
        assert self.mgr.is_enterprise("enterprise") is True
        assert self.mgr.is_enterprise("personal") is False

    def test_auto_approve_low_risk(self):
        assert self.mgr.auto_approve_low_risk("personal") is True
        assert self.mgr.auto_approve_low_risk("enterprise") is True

    def test_get_max_risk_level(self):
        assert self.mgr.get_max_risk_level("personal") == "medium"
        assert self.mgr.get_max_risk_level("enterprise") == "medium"

    def test_get_name_and_description(self):
        name = self.mgr.get_name("personal")
        assert name == "Personal Jarvis Edition"
        desc = self.mgr.get_description("personal")
        assert "extended capabilities" in desc

    def test_nonexistent_dir_loads_empty(self):
        from packages.agent_core.edition_manager import EditionManager
        mgr = EditionManager(editions_dir="/nonexistent/path/editions")
        assert mgr.list_editions() == []


# ── FileSearch Tool ──────────────────────────────────────────────────────────


class TestFileSearch:
    @pytest.mark.asyncio
    async def test_search_by_filename(self):
        from packages.executor.tools.base import ExecutionContext
        from packages.executor.tools.personal_tools import FileSearch

        with tempfile.TemporaryDirectory() as tmpdir:
            # Use resolve() to avoid Windows short-path name mismatches
            workspace = str(Path(tmpdir).resolve())
            # Create test files via resolved path
            (Path(workspace) / "report.txt").write_text("test content", encoding="utf-8")
            (Path(workspace) / "data.csv").write_text("a,b,c\n1,2,3", encoding="utf-8")

            tool = FileSearch()
            ctx = ExecutionContext(task_id="t1", step_id="s1", workspace_root=workspace)
            result = await tool.execute({"keyword": "report"}, ctx)

            assert result.success is True
            assert result.output["matches"] >= 1
            paths = [r["path"] for r in result.output["results"]]
            assert "report.txt" in paths

    @pytest.mark.asyncio
    async def test_search_by_content(self):
        from packages.executor.tools.base import ExecutionContext
        from packages.executor.tools.personal_tools import FileSearch

        with tempfile.TemporaryDirectory() as tmpdir:
            # Use resolve() to avoid Windows short-path name mismatches
            workspace = str(Path(tmpdir).resolve())
            (Path(workspace) / "notes.md").write_text("This file contains secret keywords", encoding="utf-8")

            tool = FileSearch()
            ctx = ExecutionContext(task_id="t1", step_id="s1", workspace_root=workspace)
            result = await tool.execute({"keyword": "secret"}, ctx)

            assert result.success is True
            assert result.output["matches"] >= 1

    @pytest.mark.asyncio
    async def test_search_empty_keyword(self):
        from packages.executor.tools.base import ExecutionContext
        from packages.executor.tools.personal_tools import FileSearch

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileSearch()
            ctx = ExecutionContext(task_id="t1", step_id="s1", workspace_root=tmpdir)
            result = await tool.execute({"keyword": ""}, ctx)
            assert result.success is False
            assert "keyword is required" in result.error

    @pytest.mark.asyncio
    async def test_search_path_traversal_blocked(self):
        from packages.executor.tools.base import ExecutionContext
        from packages.executor.tools.personal_tools import FileSearch

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileSearch()
            ctx = ExecutionContext(task_id="t1", step_id="s1", workspace_root=tmpdir)
            result = await tool.execute({"keyword": "test", "path": "../../etc"}, ctx)
            assert result.success is False
            assert "outside workspace" in result.error

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        from packages.executor.tools.base import ExecutionContext
        from packages.executor.tools.personal_tools import FileSearch

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileSearch()
            ctx = ExecutionContext(task_id="t1", step_id="s1", workspace_root=tmpdir)
            result = await tool.execute({"keyword": "nonexistent_file_xyz"}, ctx)
            assert result.success is True
            assert result.output["matches"] == 0


# ── FileSummarize Tool ───────────────────────────────────────────────────────


class TestFileSummarize:
    @pytest.mark.asyncio
    async def test_summarize_existing_file(self):
        from packages.executor.tools.base import ExecutionContext
        from packages.executor.tools.personal_tools import FileSummarize

        with tempfile.TemporaryDirectory() as tmpdir:
            content = "\n".join(f"Line {i}" for i in range(1, 50))
            (Path(tmpdir) / "bigfile.txt").write_text(content, encoding="utf-8")

            tool = FileSummarize()
            ctx = ExecutionContext(task_id="t1", step_id="s1", workspace_root=tmpdir)
            result = await tool.execute({"path": "bigfile.txt"}, ctx)

            assert result.success is True
            assert result.output["lines"] == 49
            assert "Line 1" in result.output["summary"]

    @pytest.mark.asyncio
    async def test_summarize_file_not_found(self):
        from packages.executor.tools.base import ExecutionContext
        from packages.executor.tools.personal_tools import FileSummarize

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileSummarize()
            ctx = ExecutionContext(task_id="t1", step_id="s1", workspace_root=tmpdir)
            result = await tool.execute({"path": "missing.txt"}, ctx)
            assert result.success is False
            assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_summarize_empty_path(self):
        from packages.executor.tools.base import ExecutionContext
        from packages.executor.tools.personal_tools import FileSummarize

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileSummarize()
            ctx = ExecutionContext(task_id="t1", step_id="s1", workspace_root=tmpdir)
            result = await tool.execute({"path": ""}, ctx)
            assert result.success is False
            assert "path is required" in result.error

    @pytest.mark.asyncio
    async def test_summarize_path_traversal_blocked(self):
        from packages.executor.tools.base import ExecutionContext
        from packages.executor.tools.personal_tools import FileSummarize

        with tempfile.TemporaryDirectory() as tmpdir:
            tool = FileSummarize()
            ctx = ExecutionContext(task_id="t1", step_id="s1", workspace_root=tmpdir)
            result = await tool.execute({"path": "../../etc/passwd"}, ctx)
            assert result.success is False
            assert "outside workspace" in result.error


# ── ReminderService ──────────────────────────────────────────────────────────


class TestReminderService:
    def setup_method(self):
        from packages.personal_context.reminder_service import ReminderService
        self.svc = ReminderService()

    def test_create_reminder(self):
        db = _make_session()
        reminder = self.svc.create_reminder(db, title="Buy groceries", description="Milk and bread")
        assert reminder.id is not None
        assert reminder.title == "Buy groceries"
        assert reminder.memory_type == MemoryType.REMINDER
        assert reminder.is_active is True
        db.close()

    def test_create_reminder_with_expiry(self):
        from datetime import UTC, datetime, timedelta
        db = _make_session()
        expires = datetime.now(UTC) + timedelta(days=7)
        reminder = self.svc.create_reminder(
            db, title="Weekly review", description="Check progress", expires_at=expires,
        )
        assert reminder.expires_at is not None
        db.close()

    def test_list_active_reminders(self):
        db = _make_session()
        self.svc.create_reminder(db, title="Reminder 1")
        self.svc.create_reminder(db, title="Reminder 2")
        reminders = self.svc.list_active(db)
        assert len(reminders) == 2
        db.close()

    def test_dismiss_reminder(self):
        db = _make_session()
        r = self.svc.create_reminder(db, title="Dismiss me")
        result = self.svc.dismiss(db, r.id, user_id="default")
        assert result is not None
        assert result.is_active is False

        # Should no longer appear in active list
        active = self.svc.list_active(db)
        assert len(active) == 0
        db.close()

    def test_dismiss_nonexistent_reminder(self):
        db = _make_session()
        result = self.svc.dismiss(db, "nonexistent-id", user_id="default")
        assert result is None
        db.close()

    def test_get_reminder(self):
        db = _make_session()
        r = self.svc.create_reminder(db, title="Find me")
        found = self.svc.get(db, r.id)
        assert found is not None
        assert found.title == "Find me"
        db.close()

    def test_expired_reminder_not_in_active(self):
        from datetime import UTC, datetime, timedelta
        db = _make_session()
        # Create a reminder that already expired
        past = datetime.now(UTC) - timedelta(days=1)
        self.svc.create_reminder(db, title="Expired", expires_at=past)
        active = self.svc.list_active(db)
        assert len(active) == 0
        db.close()


# ── PersonalContextService ───────────────────────────────────────────────────


class TestPersonalContextService:
    def _make_service(self):
        return PersonalContextService(memory_service=MemoryService(summarizer=MemorySummarizer()))

    @pytest.mark.asyncio
    async def test_get_user_preferences_empty(self):
        db = _make_session()
        svc = self._make_service()
        prefs = svc.get_user_preferences(db)
        assert prefs == []
        db.close()

    @pytest.mark.asyncio
    async def test_save_and_get_preference(self):
        db = _make_session()
        svc = self._make_service()
        result = await svc.save_preference(db, key="theme", value="dark")
        assert result is not None

        prefs = svc.get_user_preferences(db)
        assert len(prefs) >= 1
        db.close()

    @pytest.mark.asyncio
    async def test_get_active_reminders(self):
        db = _make_session()
        svc = self._make_service()
        from packages.personal_context.reminder_service import ReminderService
        ReminderService().create_reminder(db, title="Context reminder")

        reminders = svc.get_active_reminders(db)
        assert len(reminders) >= 1
        assert reminders[0]["title"] == "Context reminder"
        db.close()

    @pytest.mark.asyncio
    async def test_get_daily_context(self):
        db = _make_session()
        svc = self._make_service()
        from packages.personal_context.reminder_service import ReminderService
        ReminderService().create_reminder(db, title="Daily task")

        context = svc.get_daily_context(db)
        assert "daily_context" in context
        assert "reminders" in context
        assert "preferences_count" in context
        assert "projects_count" in context
        assert len(context["reminders"]) >= 1
        db.close()

    @pytest.mark.asyncio
    async def test_get_project_context_empty(self):
        db = _make_session()
        svc = self._make_service()
        projects = svc.get_project_context(db)
        assert projects == []
        db.close()


# ── Personal Planning Prompt ─────────────────────────────────────────────────


class TestPersonalPlanningPrompt:
    def test_basic_prompt(self):
        from packages.planner.personal_prompts import build_personal_planning_prompt

        messages = build_personal_planning_prompt(
            goal="Search the web for Python tutorials",
            tools_summary=[
                {"name": "browser.open", "description": "Open a URL"},
                {"name": "file.search", "description": "Search files"},
            ],
        )
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert "Jarvis" in messages[0].content
        assert messages[1].role == "user"
        assert "Python tutorials" in messages[1].content
        assert "browser.open" in messages[1].content

    def test_prompt_with_memories(self):
        from packages.planner.personal_prompts import build_personal_planning_prompt

        messages = build_personal_planning_prompt(
            goal="Do something",
            tools_summary=[],
            memories=[
                {"title": "Past task", "summary": "Successfully browsed website"},
            ],
        )
        user_content = messages[1].content
        assert "Past Experiences" in user_content
        assert "Past task" in user_content

    def test_prompt_with_skills(self):
        from packages.planner.personal_prompts import build_personal_planning_prompt

        messages = build_personal_planning_prompt(
            goal="Do something",
            tools_summary=[],
            skills=[{"name": "web-scrape", "description": "Scrape websites"}],
        )
        user_content = messages[1].content
        assert "Available Skills" in user_content
        assert "web-scrape" in user_content

    def test_prompt_with_preferences(self):
        from packages.planner.personal_prompts import build_personal_planning_prompt

        messages = build_personal_planning_prompt(
            goal="Do something",
            tools_summary=[],
            preferences=[{"title": "Language", "summary": "Prefer Chinese responses"}],
        )
        user_content = messages[1].content
        assert "User Preferences" in user_content
        assert "Language" in user_content

    def test_prompt_with_reminders(self):
        from packages.planner.personal_prompts import build_personal_planning_prompt

        messages = build_personal_planning_prompt(
            goal="Do something",
            tools_summary=[],
            reminders=[{"title": "Buy milk"}, {"title": "Call mom"}],
        )
        user_content = messages[1].content
        assert "Active Reminders" in user_content
        assert "Buy milk" in user_content
        assert "Call mom" in user_content

    def test_prompt_json_instruction(self):
        from packages.planner.personal_prompts import build_personal_planning_prompt

        messages = build_personal_planning_prompt(
            goal="Test",
            tools_summary=[],
        )
        system_content = messages[0].content
        assert "JSON" in system_content
        assert "reasoning" in system_content
        assert "steps" in system_content

    def test_prompt_truncation(self):
        from packages.planner.personal_prompts import build_personal_planning_prompt

        # 10 memories, but only 5 should appear
        memories = [{"title": f"Memory {i}", "summary": f"Summary {i}"} for i in range(10)]
        messages = build_personal_planning_prompt(
            goal="Test", tools_summary=[], memories=memories,
        )
        user_content = messages[1].content
        assert "Memory 4" in user_content
        assert "Memory 5" not in user_content
