"""Repository for Task and TaskStep CRUD operations."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from packages.agent_core.schemas import TaskCreate, TaskStepCreate, TaskStepUpdate, TaskUpdate
from packages.db.models import Task, TaskStep


class TaskRepository:
    @staticmethod
    def create(db: Session, schema: TaskCreate) -> Task:
        task = Task(
            goal=schema.goal,
            edition=schema.edition,
            user_id=schema.user_id,
        )
        db.add(task)
        db.flush()
        db.refresh(task)
        return task

    @staticmethod
    def batch_create(db: Session, schemas: list[TaskCreate]) -> list[Task]:
        """Create multiple tasks in a single ``add_all`` + ``flush`` round-trip.

        Avoids the per-row flush+refresh cost of calling :meth:`create` in a
        loop.  The returned ORM objects have their primary keys populated by
        the single flush; callers that need server-generated columns beyond
        the PK should refresh on demand.
        """
        if not schemas:
            return []
        tasks = [
            Task(goal=s.goal, edition=s.edition, user_id=s.user_id)
            for s in schemas
        ]
        db.add_all(tasks)
        db.flush()
        return tasks

    @staticmethod
    def get_by_id(db: Session, task_id: str, include_steps: bool = True) -> Task | None:
        stmt = select(Task).where(Task.id == task_id)
        if include_steps:
            stmt = stmt.options(joinedload(Task.steps))
        return db.scalar(stmt)

    @staticmethod
    def list_tasks(
        db: Session,
        status=None,
        edition=None,
        skip: int = 0,
        limit: int = 20,
        include_steps: bool = False,
    ) -> list[Task]:
        """List tasks with optional filters.

        By default steps are **not** loaded to avoid N+1 queries on list views.
        Set *include_steps* to True when steps data is needed.
        """
        stmt = select(Task).order_by(Task.created_at.desc())
        if include_steps:
            stmt = stmt.options(selectinload(Task.steps))
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if edition is not None:
            stmt = stmt.where(Task.edition == edition)
        stmt = stmt.offset(skip).limit(limit)
        return list(db.scalars(stmt).all())

    @staticmethod
    def count(db: Session, status=None, edition=None) -> int:
        stmt = select(Task)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if edition is not None:
            stmt = stmt.where(Task.edition == edition)
        return db.scalar(select(func.count()).select_from(stmt.subquery()))  # type: ignore[arg-type]

    @staticmethod
    def update(db: Session, task_id: str, schema: TaskUpdate) -> Task | None:
        task = db.get(Task, task_id)
        if task is None:
            return None
        update_data = schema.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(task, field, value)
        db.flush()
        db.refresh(task)
        return task

    @staticmethod
    def atomic_status_transition(db: Session, task_id: str, from_status, to_status) -> Task | None:
        """Atomically transition a task from *from_status* to *to_status*.

        Returns the updated Task on success, or None if the row was not
        in *from_status* (i.e. another request already changed it).
        """
        from packages.db.models import TaskStatus
        result = db.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == from_status)
            .values(status=to_status)
        )
        if result.rowcount == 0:
            return None
        db.flush()
        return db.get(Task, task_id)

    @staticmethod
    def add_step(db: Session, task_id: str, schema: TaskStepCreate) -> TaskStep:
        step = TaskStep(
            task_id=task_id,
            step_order=schema.step_order,
            tool_name=schema.tool_name,
            args=schema.args,
            risk_level=schema.risk_level,
            requires_approval=schema.requires_approval,
        )
        db.add(step)
        db.flush()
        db.refresh(step)
        return step

    @staticmethod
    def update_step(db: Session, step_id: str, schema: TaskStepUpdate) -> TaskStep | None:
        step = db.get(TaskStep, step_id)
        if step is None:
            return None
        update_data = schema.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(step, field, value)
        db.flush()
        db.refresh(step)
        return step

    @staticmethod
    def get_steps(db: Session, task_id: str) -> list[TaskStep]:
        stmt = (
            select(TaskStep)
            .where(TaskStep.task_id == task_id)
            .order_by(TaskStep.step_order)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_avg_duration_without_skill(db: Session, edition: str = "enterprise", limit: int = 100) -> float | None:
        """Get average task duration for completed tasks without skill runs (baseline)."""
        from sqlalchemy import and_
        from packages.db.models import SkillRun, TaskStatus

        # Subquery: task IDs that have skill runs
        skilled_task_ids = select(SkillRun.task_id).where(SkillRun.task_id.isnot(None))
        stmt = select(
            func.avg(
                func.julianday(Task.updated_at) - func.julianday(Task.created_at)
            ) * 86400
        ).where(
            and_(
                Task.edition == edition,
                Task.status == TaskStatus.COMPLETED,
                Task.id.notin(skilled_task_ids),
            )
        ).limit(limit)
        result = db.scalar(stmt)
        return float(result) if result else None
