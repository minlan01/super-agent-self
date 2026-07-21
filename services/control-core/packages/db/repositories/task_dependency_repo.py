"""Repository for TaskDependency CRUD and DAG operations (cycle detection, topological sort)."""

from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import TaskDependency


class TaskDependencyRepository:
    """Manage task dependencies as a directed acyclic graph (DAG)."""

    @staticmethod
    def add_dependency(db: Session, task_id: str, depends_on_id: str) -> TaskDependency:
        """Create a dependency edge: *task_id* depends on *depends_on_id*."""
        dep = TaskDependency(task_id=task_id, depends_on_id=depends_on_id)
        db.add(dep)
        db.flush()
        db.refresh(dep)
        return dep

    @staticmethod
    def remove_dependency(db: Session, task_id: str, depends_on_id: str) -> bool:
        """Remove a dependency edge.  Returns True if a row was deleted."""
        stmt = select(TaskDependency).where(
            TaskDependency.task_id == task_id,
            TaskDependency.depends_on_id == depends_on_id,
        )
        dep = db.scalar(stmt)
        if dep is None:
            return False
        db.delete(dep)
        db.flush()
        return True

    @staticmethod
    def get_dependencies(db: Session, task_id: str) -> list[TaskDependency]:
        """Return all dependencies *task_id* depends on (outgoing edges)."""
        stmt = (
            select(TaskDependency)
            .where(TaskDependency.task_id == task_id)
            .order_by(TaskDependency.created_at)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def get_dependents(db: Session, task_id: str) -> list[TaskDependency]:
        """Return all tasks that depend on *task_id* (incoming edges)."""
        stmt = (
            select(TaskDependency)
            .where(TaskDependency.depends_on_id == task_id)
            .order_by(TaskDependency.created_at)
        )
        return list(db.scalars(stmt).all())

    @staticmethod
    def detect_cycle(db: Session, task_id: str, depends_on_id: str) -> bool:
        """Check whether adding task_id->depends_on_id would create a cycle.

        The proposed edge means *task_id* depends on *depends_on_id*.
        A cycle exists if *depends_on_id* is already reachable from *task_id*
        through existing dependency edges (task_id -> depends_on_id direction).
        We therefore walk from *depends_on_id* following the dependency graph
        (each row: task_id depends_on depends_on_id) to see if we can reach
        *task_id*.

        Iteratively expands one BFS layer at a time, fetching only the edges
        whose ``task_id`` is in the current frontier (``WHERE task_id IN (...)``).
        This bounds memory by the size of the reachable sub-graph instead of
        the entire ``task_dependencies`` table.
        """
        if task_id == depends_on_id:
            return True  # self-dependency

        visited: set[str] = {depends_on_id}
        frontier: list[str] = [depends_on_id]

        while frontier:
            stmt = select(TaskDependency.task_id, TaskDependency.depends_on_id).where(
                TaskDependency.task_id.in_(frontier)
            )
            next_frontier: list[str] = []
            for src, dst in db.execute(stmt).all():
                if dst == task_id:
                    return True
                if dst not in visited:
                    visited.add(dst)
                    next_frontier.append(dst)
            frontier = next_frontier
        return False

    @staticmethod
    def get_execution_order(db: Session, task_ids: list[str]) -> list[str]:
        """Return a topological ordering of *task_ids* using Kahn's algorithm.

        Handles disconnected sub-graphs within the provided set.
        Tasks with no dependencies among the set come first.
        """
        if not task_ids:
            return []

        task_id_set = set(task_ids)

        # Fetch only dependencies relevant to the requested task_ids
        stmt = select(TaskDependency).where(
            TaskDependency.task_id.in_(task_id_set),
            TaskDependency.depends_on_id.in_(task_id_set),
        )
        all_deps = list(db.scalars(stmt).all())

        # Build in-degree map and adjacency list (reverse direction for Kahn's)
        in_degree: dict[str, int] = {tid: 0 for tid in task_id_set}
        # dependents[X] = tasks that depend on X (X must finish before they can start)
        dependents: dict[str, list[str]] = defaultdict(list)

        for dep in all_deps:
            # dep.task_id depends on dep.depends_on_id
            in_degree[dep.task_id] = in_degree.get(dep.task_id, 0) + 1
            dependents[dep.depends_on_id].append(dep.task_id)

        # Seed queue with zero in-degree nodes
        queue: deque[str] = deque(
            tid for tid in task_id_set if in_degree.get(tid, 0) == 0
        )

        result: list[str] = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for child in dependents.get(node, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        # If there are cycles, remaining nodes won't be in result — append them
        # in original order as a fallback
        if len(result) < len(task_id_set):
            remaining = [tid for tid in task_ids if tid not in set(result)]
            result.extend(remaining)

        return result

    @staticmethod
    def get_all_dependencies_recursive(db: Session, task_id: str) -> list[str]:
        """Recursively resolve all transitive dependencies of *task_id*.

        Iteratively expands one BFS layer at a time, fetching only the edges
        whose ``task_id`` is in the current frontier (``WHERE task_id IN (...)``).
        Bounds memory by the size of the reachable sub-graph rather than
        the entire ``task_dependencies`` table.
        """
        visited: set[str] = {task_id}
        result: list[str] = []
        frontier: list[str] = [task_id]

        while frontier:
            stmt = select(TaskDependency.task_id, TaskDependency.depends_on_id).where(
                TaskDependency.task_id.in_(frontier)
            )
            next_frontier: list[str] = []
            for _src, dst in db.execute(stmt).all():
                if dst not in visited:
                    visited.add(dst)
                    result.append(dst)
                    next_frontier.append(dst)
            frontier = next_frontier

        return result
