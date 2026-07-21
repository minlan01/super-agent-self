"""Streaming output — wraps ProviderRouter.stream() and renders to rich.Console."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

logger = logging.getLogger(__name__)
console = Console()


async def stream_response(
    messages: list[dict[str, str]],
    edition: str = "personal",
    *,
    provider: str | None = None,
) -> str:
    """Stream an LLM response and render incrementally in the terminal.

    Returns the full assembled text after streaming completes.
    """
    from packages.llm_gateway.base import LLMMessage
    from packages.llm_gateway.provider_router import ProviderRouter

    router = ProviderRouter()
    llm_messages = [LLMMessage(role=m["role"], content=m["content"]) for m in messages]

    collected: list[str] = []

    try:
        async for chunk in router.stream(llm_messages, provider=provider):
            if chunk.delta:
                collected.append(chunk.delta)
                # Print each chunk incrementally
                console.print(Text(chunk.delta), end="")

            if chunk.finished:
                break

        console.print()  # Final newline
    except Exception as e:
        logger.warning("Streaming failed, falling back to non-streaming: %s", e)
        # Fallback to non-streaming generate
        response = await router.generate(llm_messages, provider=provider)
        collected = [response.content]
        console.print()
        console.print(Markdown(response.content))
        console.print()

    return "".join(collected)


async def stream_response_live(
    messages: list[dict[str, str]],
    edition: str = "personal",
    *,
    provider: str | None = None,
) -> str:
    """Stream an LLM response with a Rich Live display that refreshes markdown.

    This provides a smoother UX by re-rendering the full accumulated text
    as markdown on each chunk, giving proper formatting in real-time.

    Falls back to ``stream_response`` if Live is unavailable.
    """
    from packages.llm_gateway.base import LLMMessage
    from packages.llm_gateway.provider_router import ProviderRouter

    router = ProviderRouter()
    llm_messages = [LLMMessage(role=m["role"], content=m["content"]) for m in messages]

    collected: list[str] = []

    try:
        with Live(console=console, refresh_per_second=8, vertical_overflow="visible") as live:
            async for chunk in router.stream(llm_messages, provider=provider):
                if chunk.delta:
                    collected.append(chunk.delta)
                    live.update(Markdown("".join(collected)))
                if chunk.finished:
                    break

        console.print()
    except Exception as e:
        logger.warning("Live streaming failed, falling back to simple streaming: %s", e)
        return await stream_response(messages, edition, provider=provider)

    return "".join(collected)
