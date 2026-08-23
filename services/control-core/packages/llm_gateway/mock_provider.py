"""Mock LLM provider for testing without API keys."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from packages.llm_gateway.base import BaseLLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)

_DEFAULT_PLAN = {
    "steps": [
        {
            "step_id": 1,
            "tool_name": "browser.open",
            "args": {"url": "https://example.com"},
            "reasoning": "Open the target webpage to retrieve content.",
        },
        {
            "step_id": 2,
            "tool_name": "browser.extract_text",
            "args": {"selectors": ["h1", "article"]},
            "reasoning": "Extract key text content from the page.",
        },
        {
            "step_id": 3,
            "tool_name": "file.write_docx",
            "args": {
                "output_path": "report.docx",
                "title": "Extracted Report",
                "paragraphs": ["Content extracted from the webpage."],
            },
            "reasoning": "Write extracted content to a DOCX file.",
        },
    ]
}

_READ_SMOKE_PLAN = {
    "reasoning": "Create a workspace fixture and read it back through the controlled file tool.",
    "steps": [
        {
            "step_id": 1,
            "tool_name": "file.write_markdown",
            "args": {"output_path": "read-target.md", "content": "# P4 read smoke\n"},
            "reasoning": "Create a deterministic workspace file for the read operation.",
        },
        {
            "step_id": 2,
            "tool_name": "file.read",
            "args": {"path": "outputs/read-target.md"},
            "reasoning": "Read the workspace file through the low-risk file tool.",
        },
    ],
}

_DELETE_APPROVAL_PLAN = {
    "reasoning": "Create a workspace fixture, then request approval before deleting it.",
    "steps": [
        {
            "step_id": 1,
            "tool_name": "file.write_markdown",
            "args": {"output_path": "approval-target.md", "content": "# P4 approval smoke\n"},
            "reasoning": "Create the file that the approved destructive step will remove.",
        },
        {
            "step_id": 2,
            "tool_name": "file.delete",
            "args": {"path": "outputs/approval-target.md"},
            "reasoning": "Delete the workspace file only after a human approval is recorded.",
        },
    ],
}


@dataclass
class MockProviderConfig:
    planning_responses: dict[str, str] = field(default_factory=dict)


class MockProvider(BaseLLMProvider):
    """Mock provider that returns pre-defined responses. No API key needed."""

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        mock_cfg = config.get("mock_config", {})
        self.planning_responses: dict[str, str] = mock_cfg.get(
            "planning_responses", {}
        )

    async def generate(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Return a plain-text mock response summarizing the last user message."""
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.role == "user":
                last_user_msg = msg.content
                break

        content = f"[Mock] Received task: {last_user_msg or '(no user message)'}"
        logger.debug("MockProvider.generate: %s", content)

        return LLMResponse(
            content=content,
            model="mock",
            provider="mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0},
        )

    async def generate_json(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        """Return a JSON plan response, matched from keywords or default."""
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.role == "user":
                last_user_msg = msg.content
                break

        plan = _DEFAULT_PLAN
        # Deterministic desktop acceptance plans. The user message is separate
        # from the system tool summary, so these checks only match the goal.
        goal = last_user_msg.lower()
        if "file.delete" in goal or "delete" in goal or "删除" in last_user_msg:
            plan = _DELETE_APPROVAL_PLAN
        elif "file.read" in goal or "read" in goal or "读取" in last_user_msg:
            plan = _READ_SMOKE_PLAN
        # Try to find a matching pre-defined response by keyword
        if self.planning_responses and last_user_msg:
            for keyword, response_json in self.planning_responses.items():
                if keyword.lower() in last_user_msg.lower():
                    try:
                        plan = json.loads(response_json)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Invalid JSON in planning_responses for keyword '%s'",
                            keyword,
                        )
                    else:
                        logger.debug(
                            "MockProvider: matched keyword '%s'", keyword
                        )
                        break

        content = json.dumps(plan, ensure_ascii=False)
        logger.debug("MockProvider.generate_json: %s", content)

        return LLMResponse(
            content=content,
            model="mock",
            provider="mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0},
        )
