"""Plan validator — parses and validates LLM plan output against tool registry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """A single step in a validated plan."""

    step_id: int = Field(..., ge=1)
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""


class Plan(BaseModel):
    """A validated plan with one or more steps."""

    reasoning: str = ""
    steps: list[PlanStep] = Field(..., min_length=1, max_length=20)


class PlanValidator:
    """Validates plan dicts against the tool registry."""

    def __init__(self, tool_registry: Any):
        self.tool_registry = tool_registry

    def validate(self, plan_dict: dict[str, Any]) -> Plan:
        """Validate and parse a plan dict into a Plan model.

        Checks:
        - Schema conformance (step_id >= 1, 1-20 steps, required fields).
        - All tool_names are registered in the tool registry.
        - All tool_names are enabled.

        Raises:
            ValueError: If a tool is unknown or disabled.
            pydantic.ValidationError: If the plan does not match the schema.
        """
        plan = Plan.model_validate(plan_dict)

        for step in plan.steps:
            if not self.tool_registry.is_registered(step.tool_name):
                raise ValueError(f"Unknown tool: {step.tool_name}")
            if not self.tool_registry.is_enabled(step.tool_name):
                raise ValueError(f"Tool is disabled: {step.tool_name}")

        return plan
