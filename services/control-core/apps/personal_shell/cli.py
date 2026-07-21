"""CLI entry point — typer app with subcommands for task, skill, config, and chat."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="myself",
    help="Controlled Agent Platform — Personal Shell CLI",
    no_args_is_help=True,
)


@app.command()
def chat(
    edition: str = typer.Option(
        "personal", "--edition", "-e", help="Edition context (personal|enterprise)"
    ),
) -> None:
    """Start an interactive REPL chat session with the agent."""
    from apps.personal_shell.repl import start_repl

    start_repl(edition=edition)


@app.command()
def version() -> None:
    """Show platform version."""
    from packages.agent_core.version import __version__

    typer.echo(f"myself-agent v{__version__}")


# ── Task subcommands ─────────────────────────────────────────────────────


@app.command("task-create")
def task_create(
    goal: str = typer.Argument(..., help="Task goal description"),
    edition: str = typer.Option("personal", "--edition", "-e"),
) -> None:
    """Create a new task."""
    from apps.personal_shell.commands.task import create_task

    create_task(goal, edition)


@app.command("task-list")
def task_list(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    edition: str = typer.Option("personal", "--edition", "-e"),
) -> None:
    """List tasks."""
    from apps.personal_shell.commands.task import list_tasks

    list_tasks(status=status, edition=edition)


@app.command("task-status")
def task_status(
    task_id: str = typer.Argument(..., help="Task ID"),
) -> None:
    """Show task status and steps."""
    from apps.personal_shell.commands.task import show_task_status

    show_task_status(task_id)


# ── Skill subcommands ────────────────────────────────────────────────────


@app.command("skill-list")
def skill_list(
    edition: str = typer.Option("personal", "--edition", "-e"),
) -> None:
    """List available skills."""
    from apps.personal_shell.commands.skill import list_skills

    list_skills(edition)


@app.command("skill-approve")
def skill_approve(
    skill_id: str = typer.Argument(..., help="Skill ID to approve"),
) -> None:
    """Approve a candidate skill."""
    from apps.personal_shell.commands.skill import approve_skill

    approve_skill(skill_id)


# ── Config subcommands ───────────────────────────────────────────────────


@app.command("config-show")
def config_show() -> None:
    """Show current configuration."""
    from apps.personal_shell.commands.config import show_config

    show_config()


@app.command("config-edition")
def config_edition(
    edition: str = typer.Argument(..., help="Edition to switch to (personal|enterprise)"),
) -> None:
    """Switch the active edition context."""
    from apps.personal_shell.commands.config import switch_edition

    switch_edition(edition)


if __name__ == "__main__":
    app()
