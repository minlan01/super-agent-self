"""Config CLI commands — show config and switch edition."""

from __future__ import annotations

import os

from rich.console import Console
from rich.table import Table

console = Console()


def show_config() -> None:
    """Show current platform configuration."""
    from packages.agent_core.version import __version__
    from packages.config import get_settings

    settings = get_settings()

    table = Table(title="Platform Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    table.add_row("Version", __version__)
    table.add_row("App Name", settings.app_name)
    table.add_row("Edition", settings.edition)
    table.add_row("Log Level", settings.log_level)
    table.add_row("Workspace", settings.workspace_root)
    table.add_row("Database", "sqlite" if "sqlite" in settings.database.url else "postgresql")
    table.add_row(
        "LLM Provider", os.environ.get("LLM_PROVIDER", "mock")
    )

    console.print(table)


def switch_edition(edition: str) -> None:
    """Switch the active edition context (runtime only)."""
    if edition not in ("personal", "enterprise"):
        console.print(f"[red]Unknown edition: {edition}. Use 'personal' or 'enterprise'[/]")
        return

    from packages.config import get_settings

    settings = get_settings()
    settings.edition = edition
    console.print(f"[green]Edition switched to:[/] {edition}")
    console.print("[dim]Note: this change is runtime-only and will reset on restart.[/]")
