"""Task CLI commands — create, list, and show task status."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

console = Console()


def create_task(goal: str, edition: str = "personal") -> None:
    """Create a new task via the database."""
    from packages.db.models import Task, TaskStatus
    from packages.db.session import SessionLocal

    db = SessionLocal()
    try:
        task = Task(
            id=str(uuid.uuid4()),
            goal=goal,
            status=TaskStatus.PENDING,
            edition=edition,
            created_at=datetime.now(UTC),
        )
        db.add(task)
        db.commit()
        console.print(f"[green]Task created:[/] {task.id}")
        console.print(f"  Goal: {goal}")
        console.print(f"  Edition: {edition}")
    except Exception as e:
        console.print(f"[red]Failed to create task: {e}[/]")
    finally:
        db.close()


def list_tasks(status: str | None = None, edition: str = "personal") -> None:
    """List tasks, optionally filtered by status."""
    from packages.db.models import Task
    from packages.db.session import SessionLocal

    db = SessionLocal()
    try:
        q = db.query(Task).filter(Task.edition == edition)
        if status:
            q = q.filter(Task.status == status)
        tasks = q.order_by(Task.created_at.desc()).limit(20).all()

        if not tasks:
            console.print("[dim]No tasks found[/]")
            return

        table = Table(title=f"Tasks (edition={edition})")
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("Goal", max_width=50)
        table.add_column("Status", style="cyan")
        table.add_column("Created", style="dim")

        for t in tasks:
            table.add_row(
                t.id[:8] + "...",
                t.goal[:50],
                t.status,
                str(t.created_at)[:19] if t.created_at else "",
            )

        console.print(table)
    finally:
        db.close()


def show_task_status(task_id: str) -> None:
    """Show detailed task status including steps."""
    from packages.db.models import Task, TaskStep
    from packages.db.session import SessionLocal

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            console.print(f"[red]Task not found: {task_id}[/]")
            return

        console.print(f"[bold]Task:[/] {task.id}")
        console.print(f"  Goal: {task.goal}")
        console.print(f"  Status: [cyan]{task.status}[/]")
        console.print(f"  Edition: {task.edition}")

        steps = db.query(TaskStep).filter(TaskStep.task_id == task_id).all()
        if steps:
            table = Table(title="Steps")
            table.add_column("#", style="dim")
            table.add_column("Tool", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Result", max_width=40)

            for i, s in enumerate(steps, 1):
                result = ""
                if s.result:
                    result = str(s.result)[:40]
                table.add_row(str(i), s.tool_name or "", s.status, result)

            console.print(table)
    finally:
        db.close()
