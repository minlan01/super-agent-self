"""Prompt templates for the Planner — forces structured JSON output."""

from __future__ import annotations

from typing import Any

from packages.llm_gateway.base import LLMMessage


def _format_tools(tools_summary: list[dict[str, Any]]) -> str:
    """Format tool definitions for injection into the system prompt."""
    if not tools_summary:
        return "No tools available."
    lines = []
    for t in tools_summary:
        line = f"- {t['name']}: {t['description']}"
        if t.get("params"):
            param_names = list(t["params"].keys())
            line += f" | params: {', '.join(param_names)}"
        if t.get("required_params"):
            line += f" | required: {', '.join(t['required_params'])}"
        lines.append(line)
    return "\n".join(lines)


def _format_memories(memories: list[dict[str, Any]] | None) -> str:
    """Format past experiences for prompt injection."""
    if not memories:
        return ""
    lines = ["## Relevant Past Experiences"]
    for m in memories[:5]:  # Respect token budget
        title = m.get("title", "")
        summary = m.get("summary", "")
        lines.append(f"- {title}: {summary}")
    return "\n".join(lines)


def _format_skills(skills: list[dict[str, Any]] | None) -> str:
    """Format approved skills for prompt injection."""
    if not skills:
        return ""
    lines = ["## Approved Skills (Reusable Plans)"]
    for s in skills[:5]:
        name = s.get("name", "")
        description = s.get("description", "")
        lines.append(f"- {name}: {description}")
    return "\n".join(lines)


_SYSTEM_PROMPT = """\
You are a task planner for a controlled agent platform. You MUST output ONLY valid JSON — no markdown, no explanation, no commentary.

## Edition
{edition}

## Available Tools
{tools}

{memories}

{skills}

## Output Format
Return a single JSON object with this exact structure:
```json
{{
  "reasoning": "Brief analysis of the task and approach",
  "steps": [
    {{
      "step_id": 1,
      "tool_name": "tool.name",
      "args": {{}},
      "reasoning": "Why this step is needed"
    }}
  ]
}}
```

## Rules
1. Maximum 20 steps per plan.
2. Only use tools listed in Available Tools above.
3. All file paths MUST be within the workspace directory. Never use absolute paths outside workspace.
4. Never include shell commands or arbitrary code execution.
5. Each step_id must be a positive integer, sequential starting from 1.
6. The "args" object must match the tool's required and optional parameters.
7. Provide a brief reasoning for each step.
"""


def build_planning_prompt(
    goal: str,
    tools_summary: list[dict[str, Any]],
    edition: str = "enterprise",
    memories: list[dict[str, Any]] | None = None,
    skills: list[dict[str, Any]] | None = None,
) -> list[LLMMessage]:
    """Construct system + user messages for planning.

    Args:
        goal: The task goal description.
        tools_summary: List of tool dicts from ToolRegistry.get_tools_summary().
        edition: "enterprise" or "personal".
        memories: Optional list of past experience dicts with title/summary.
        skills: Optional list of approved skill dicts with name/description.

    Returns:
        A list of LLMMessage objects ready for the LLM gateway.
    """
    tools_text = _format_tools(tools_summary)
    memories_text = _format_memories(memories)
    skills_text = _format_skills(skills)

    system_content = _SYSTEM_PROMPT.format(
        edition=edition,
        tools=tools_text,
        memories=memories_text,
        skills=skills_text,
    )

    return [
        LLMMessage(role="system", content=system_content),
        LLMMessage(role="user", content=goal),
    ]
