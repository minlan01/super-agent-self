"""Personal planner prompt templates — conversational, project-oriented."""

from __future__ import annotations

from typing import Any

from packages.llm_gateway.base import LLMMessage


def build_personal_planning_prompt(
    goal: str,
    tools_summary: list[dict[str, Any]],
    memories: list[dict[str, Any]] | None = None,
    skills: list[dict[str, Any]] | None = None,
    preferences: list[dict[str, Any]] | None = None,
    reminders: list[dict[str, Any]] | None = None,
) -> list[LLMMessage]:
    """Build planning prompt for Personal Jarvis Edition.

    More conversational and context-aware than enterprise version.
    Injects user preferences, reminders, and personal context.
    """
    tools_text = "\n".join(
        f"  - {t['name']}: {t['description']}" for t in tools_summary
    )

    memory_text = ""
    if memories:
        memory_text = "\n\n## Past Experiences\n"
        for m in memories[:5]:
            memory_text += f"- {m.get('title', '')}: {m.get('summary', '')}\n"

    skills_text = ""
    if skills:
        skills_text = "\n\n## Available Skills\n"
        for s in skills[:3]:
            skills_text += f"- {s.get('name', '')}: {s.get('description', '')}\n"

    prefs_text = ""
    if preferences:
        prefs_text = "\n\n## User Preferences\n"
        for p in preferences[:5]:
            prefs_text += f"- {p.get('title', '')}: {p.get('summary', '')}\n"

    reminders_text = ""
    if reminders:
        reminders_text = "\n\n## Active Reminders\n"
        for r in reminders[:3]:
            reminders_text += f"- {r.get('title', '')}\n"

    system = (
        "You are a personal AI assistant (Jarvis). You help with web browsing, "
        "file management, information retrieval, and task automation.\n"
        "You plan tasks as a JSON object with a 'reasoning' field and 'steps' array.\n"
        "Each step has: step_id (int >= 1), tool_name, args (object), reasoning.\n"
        "Be concise and helpful. Use the user's preferences and past experiences.\n"
        "Respond ONLY with valid JSON, no markdown fences."
    )

    user = (
        f"## Available Tools\n{tools_text}\n\n"
        f"## User Request\n{goal}\n"
        f"{memory_text}{skills_text}{prefs_text}{reminders_text}\n"
        f"Create a plan as JSON: {{\"reasoning\": \"...\", \"steps\": [...]}}"
    )

    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user),
    ]
