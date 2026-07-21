"""Skill CLI commands — list and approve skills."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

console = Console()


def list_skills(edition: str = "personal") -> None:
    """List available skills."""
    from packages.db.models import Skill
    from packages.db.session import SessionLocal

    db = SessionLocal()
    try:
        skills = (
            db.query(Skill)
            .filter(Skill.edition == edition)
            .order_by(Skill.created_at.desc())
            .limit(30)
            .all()
        )

        if not skills:
            console.print("[dim]No skills found[/]")
            return

        table = Table(title=f"Skills (edition={edition})")
        table.add_column("ID", style="dim", max_width=12)
        table.add_column("Name", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Version", style="dim")
        table.add_column("Success Rate", style="yellow")

        for s in skills:
            rate = f"{s.success_rate:.0%}" if s.success_rate is not None else "N/A"
            table.add_row(
                s.id[:8] + "...",
                s.name,
                s.status,
                str(s.version),
                rate,
            )

        console.print(table)
    finally:
        db.close()


def approve_skill(skill_id: str) -> None:
    """Approve a candidate skill."""
    from packages.db.models import Skill
    from packages.db.session import SessionLocal

    db = SessionLocal()
    try:
        skill = db.query(Skill).filter(Skill.id == skill_id).first()
        if not skill:
            console.print(f"[red]Skill not found: {skill_id}[/]")
            return

        if skill.status != "CANDIDATE":
            console.print(f"[yellow]Skill is not in CANDIDATE status (current: {skill.status})[/]")
            return

        skill.status = "STABLE"
        db.commit()
        console.print(f"[green]Skill approved:[/] {skill.name} v{skill.version}")
    except Exception as e:
        console.print(f"[red]Failed to approve skill: {e}[/]")
    finally:
        db.close()
