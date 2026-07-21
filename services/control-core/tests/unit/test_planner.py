"""Unit tests for Planner — prompt templates, Plan validation, PlanValidator."""

import pytest
from pydantic import ValidationError

from packages.planner.plan_validator import Plan, PlanStep, PlanValidator
from packages.planner.prompt_templates import build_planning_prompt

# ── build_planning_prompt tests ────────────────────────────────────────────


@pytest.mark.unit
class TestBuildPlanningPrompt:
    def test_returns_system_and_user_messages(self):
        messages = build_planning_prompt("do task", [])

        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        assert messages[1].content == "do task"

    def test_system_prompt_contains_edition(self):
        messages = build_planning_prompt("task", [], edition="personal")
        assert "personal" in messages[0].content

    def test_system_prompt_contains_tool_info(self):
        tools = [
            {
                "name": "browser.open",
                "description": "Open URL",
                "category": "browser",
                "params": {"url": "string"},
                "required_params": ["url"],
            }
        ]
        messages = build_planning_prompt("task", tools)
        assert "browser.open" in messages[0].content
        assert "Open URL" in messages[0].content

    def test_memories_injected_into_prompt(self):
        memories = [
            {"title": "Prior attempt", "summary": "Failed due to timeout"},
        ]
        messages = build_planning_prompt("task", [], memories=memories)
        assert "Prior attempt" in messages[0].content
        assert "Failed due to timeout" in messages[0].content
        assert "Relevant Past Experiences" in messages[0].content

    def test_skills_injected_into_prompt(self):
        skills = [
            {"name": "web-scrape", "description": "Scrape web pages"},
        ]
        messages = build_planning_prompt("task", [], skills=skills)
        assert "web-scrape" in messages[0].content
        assert "Scrape web pages" in messages[0].content
        assert "Approved Skills" in messages[0].content

    def test_no_memories_no_section(self):
        messages = build_planning_prompt("task", [], memories=None)
        assert "Relevant Past Experiences" not in messages[0].content

    def test_no_skills_no_section(self):
        messages = build_planning_prompt("task", [], skills=None)
        assert "Approved Skills" not in messages[0].content

    def test_empty_tools_shows_no_tools_available(self):
        messages = build_planning_prompt("task", [])
        assert "No tools available" in messages[0].content

    def test_memories_limited_to_five(self):
        memories = [{"title": f"mem-{i}", "summary": f"sum-{i}"} for i in range(10)]
        messages = build_planning_prompt("task", [], memories=memories)
        assert "mem-5" not in messages[0].content  # 6th (0-indexed 5) should be excluded
        assert "mem-4" in messages[0].content


# ── PlanStep validation tests ──────────────────────────────────────────────


@pytest.mark.unit
class TestPlanStepValidation:
    def test_valid_step(self):
        step = PlanStep(step_id=1, tool_name="browser.open", args={"url": "https://example.com"})
        assert step.step_id == 1
        assert step.tool_name == "browser.open"

    def test_step_id_zero_rejected(self):
        with pytest.raises(ValidationError):
            PlanStep(step_id=0, tool_name="browser.open")

    def test_step_id_negative_rejected(self):
        with pytest.raises(ValidationError):
            PlanStep(step_id=-1, tool_name="browser.open")

    def test_step_id_must_be_int(self):
        with pytest.raises(ValidationError):
            PlanStep(step_id="one", tool_name="browser.open")

    def test_args_defaults_to_empty_dict(self):
        step = PlanStep(step_id=1, tool_name="file.read")
        assert step.args == {}

    def test_reasoning_defaults_to_empty_string(self):
        step = PlanStep(step_id=1, tool_name="file.read")
        assert step.reasoning == ""


# ── Plan validation tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestPlanValidation:
    def test_valid_plan(self):
        plan = Plan(
            reasoning="do things",
            steps=[
                PlanStep(step_id=1, tool_name="browser.open", args={"url": "https://example.com"}),
            ],
        )
        assert len(plan.steps) == 1

    def test_plan_min_one_step(self):
        with pytest.raises(ValidationError):
            Plan(reasoning="empty", steps=[])

    def test_plan_max_twenty_steps(self):
        steps = [PlanStep(step_id=i, tool_name="file.read") for i in range(1, 21)]
        plan = Plan(steps=steps)  # exactly 20, should pass
        assert len(plan.steps) == 20

    def test_plan_exceeds_max_steps(self):
        steps = [PlanStep(step_id=i, tool_name="file.read") for i in range(1, 22)]
        with pytest.raises(ValidationError):
            Plan(steps=steps)


# ── PlanValidator tests ────────────────────────────────────────────────────


class _FakeRegistry:
    """Minimal fake tool registry for PlanValidator tests."""

    def __init__(self, registered: set[str], enabled: set[str]):
        self._registered = registered
        self._enabled = enabled

    def is_registered(self, name: str) -> bool:
        return name in self._registered

    def is_enabled(self, name: str) -> bool:
        return name in self._enabled


@pytest.mark.unit
class TestPlanValidator:
    def test_rejects_unknown_tool(self):
        registry = _FakeRegistry(
            registered={"browser.open", "file.read"},
            enabled={"browser.open", "file.read"},
        )
        validator = PlanValidator(registry)

        plan_dict = {
            "steps": [
                {"step_id": 1, "tool_name": "unknown.tool", "args": {}},
            ]
        }
        with pytest.raises(ValueError, match="Unknown tool"):
            validator.validate(plan_dict)

    def test_rejects_disabled_tool(self):
        registry = _FakeRegistry(
            registered={"browser.open", "shell.run"},
            enabled={"browser.open"},  # shell.run not enabled
        )
        validator = PlanValidator(registry)

        plan_dict = {
            "steps": [
                {"step_id": 1, "tool_name": "shell.run", "args": {"command": "rm -rf /"}},
            ]
        }
        with pytest.raises(ValueError, match="disabled"):
            validator.validate(plan_dict)

    def test_accepts_valid_plan(self):
        registry = _FakeRegistry(
            registered={"browser.open", "file.read"},
            enabled={"browser.open", "file.read"},
        )
        validator = PlanValidator(registry)

        plan_dict = {
            "reasoning": "open page then read file",
            "steps": [
                {"step_id": 1, "tool_name": "browser.open", "args": {"url": "https://example.com"}, "reasoning": "open"},
                {"step_id": 2, "tool_name": "file.read", "args": {"path": "data.txt"}, "reasoning": "read"},
            ],
        }
        plan = validator.validate(plan_dict)
        assert len(plan.steps) == 2
        assert plan.steps[0].tool_name == "browser.open"
        assert plan.steps[1].tool_name == "file.read"

    def test_rejects_mixed_unknown_and_valid(self):
        registry = _FakeRegistry(
            registered={"browser.open"},
            enabled={"browser.open"},
        )
        validator = PlanValidator(registry)

        plan_dict = {
            "steps": [
                {"step_id": 1, "tool_name": "browser.open", "args": {}},
                {"step_id": 2, "tool_name": "evil.tool", "args": {}},
            ]
        }
        with pytest.raises(ValueError, match="Unknown tool"):
            validator.validate(plan_dict)

    def test_rejects_invalid_schema_before_tool_check(self):
        registry = _FakeRegistry(
            registered={"browser.open"},
            enabled={"browser.open"},
        )
        validator = PlanValidator(registry)

        plan_dict = {"steps": [{"tool_name": "browser.open"}]}  # missing step_id
        with pytest.raises(ValidationError):
            validator.validate(plan_dict)
