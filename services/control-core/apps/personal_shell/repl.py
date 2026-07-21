"""REPL loop — prompt_toolkit interactive chat with the agent."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console
from rich.panel import Panel

from apps.personal_shell.history import ChatHistory

logger = logging.getLogger(__name__)
console = Console()


def _get_completer() -> Any:
    """Build a prompt_toolkit completer with slash commands and tool names."""
    try:
        from prompt_toolkit.completion import WordCompleter

        slash_commands = [
            "/help", "/tools", "/tasks", "/skills", "/edition",
            "/history", "/search", "/sessions", "/exit",
        ]
        return WordCompleter(slash_commands, ignore_case=True)
    except ImportError:
        return None


def start_repl(edition: str = "personal") -> None:
    """Start the interactive REPL loop."""
    console.print(
        Panel(
            f"[bold green]myself-agent[/] — Personal Shell\n"
            f"Edition: [cyan]{edition}[/] | Type [bold]/help[/] for commands",
            title="Welcome",
            border_style="green",
        )
    )

    history_mgr = ChatHistory(user_id="default", edition=edition)

    while True:
        try:
            from prompt_toolkit import prompt as pt_prompt
            from prompt_toolkit.history import InMemoryHistory

            mem_history = InMemoryHistory()
            user_input = pt_prompt(
                f"[{edition}]> ",
                completer=_get_completer(),
                history=mem_history,
            ).strip()
        except ImportError:
            # Fallback without prompt_toolkit
            user_input = input(f"[{edition}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]Goodbye![/]")
            break

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            if _handle_slash_command(user_input, edition, history_mgr):
                break  # /exit returns True
            continue

        if user_input.lower() in ("exit", "quit"):
            console.print("[dim]Goodbye![/]")
            break

        # Chat with LLM — persist and stream
        history_mgr.add_message("user", user_input)
        _chat_turn(history_mgr, edition)


def _handle_slash_command(cmd: str, edition: str, history_mgr: ChatHistory) -> bool:
    """Handle REPL slash commands. Returns True if /exit."""
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        console.print(
            Panel(
                "[bold]/help[/]       Show this help\n"
                "[bold]/tools[/]     List available tools\n"
                "[bold]/tasks[/]     Show recent tasks\n"
                "[bold]/skills[/]    List skills\n"
                "[bold]/edition[/]   <name> Switch edition\n"
                "[bold]/sessions[/]  List recent chat sessions\n"
                "[bold]/history[/]   Show current session messages\n"
                "[bold]/search[/]    <query> Search chat history\n"
                "[bold]/exit[/]      Exit the REPL",
                title="Commands",
                border_style="blue",
            )
        )
    elif command == "/tools":
        _show_tools(edition)
    elif command == "/tasks":
        from apps.personal_shell.commands.task import list_tasks
        list_tasks(edition=edition)
    elif command == "/skills":
        from apps.personal_shell.commands.skill import list_skills
        list_skills(edition)
    elif command == "/edition":
        if arg:
            console.print(f"Edition switched to [cyan]{arg}[/] (for this session)")
        else:
            console.print(f"Current edition: [cyan]{edition}[/]")
    elif command == "/sessions":
        history_mgr.display_sessions()
    elif command == "/history":
        msgs = history_mgr.messages
        if not msgs:
            console.print("[dim]No messages in this session yet.[/]")
        else:
            for m in msgs:
                role_style = "cyan" if m["role"] == "user" else "green"
                console.print(f"[{role_style}]{m['role']}[/]: {m['content'][:200]}")
    elif command == "/search":
        if not arg:
            console.print("[yellow]Usage: /search <query>[/]")
        else:
            history_mgr.display_search(arg)
    elif command == "/exit":
        return True
    else:
        console.print(f"[yellow]Unknown command: {command}[/]")

    return False


def _show_tools(edition: str) -> None:
    """List available tools from the registry."""
    from packages.policy.unified_registry import UnifiedToolRegistry

    registry = UnifiedToolRegistry.get_instance()
    tools = registry.list_tools(edition=edition, enabled_only=True)
    if not tools:
        console.print("[dim]No tools available[/]")
        return

    from rich.table import Table

    table = Table(title="Available Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Risk", style="yellow")
    table.add_column("Emoji")

    for t in tools:
        table.add_row(t.name, t.category, t.risk_level, t.emoji)

    console.print(table)


def _chat_turn(history_mgr: ChatHistory, edition: str) -> None:
    """Send a chat message to the LLM and stream the response."""
    try:
        assistant_text = asyncio.run(_async_chat_turn(history_mgr, edition))
        if assistant_text:
            history_mgr.add_message("assistant", assistant_text)
    except RuntimeError as e:
        if "Event loop is already running" in str(e):
            console.print(f"[red]Cannot start async chat: {e}[/]")
        else:
            console.print(f"[red]Error: {e}[/]")
    except Exception as e:
        console.print(f"[red]Chat error: {e}[/]")


async def _async_chat_turn(history_mgr: ChatHistory, edition: str) -> str:
    """Async implementation of a chat turn with streaming."""
    from apps.personal_shell.streaming import stream_response

    messages = history_mgr.messages
    try:
        return await stream_response(messages, edition)
    except Exception as e:
        console.print(f"[red]LLM error: {e}[/]")
        return ""
