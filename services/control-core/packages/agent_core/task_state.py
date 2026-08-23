"""Task State Machine — validates and manages task lifecycle transitions."""

from __future__ import annotations

from packages.db.models import TaskStatus

# Valid transitions: from_status → set of allowed to_statuses
_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.PLANNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.PLANNING: {
        TaskStatus.AWAITING_APPROVAL,
        TaskStatus.EXECUTING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.AWAITING_APPROVAL: {
        TaskStatus.EXECUTING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.EXECUTING: {
        TaskStatus.AWAITING_APPROVAL,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    # Terminal states — no outgoing transitions
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}

TERMINAL_STATES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class TaskStateMachine:
    """Validates and applies state transitions for tasks."""

    @staticmethod
    def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
        return target in _TRANSITIONS.get(current, set())

    @staticmethod
    def transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
        if not TaskStateMachine.can_transition(current, target):
            raise InvalidTransition(current, target)
        return target

    @staticmethod
    def is_terminal(status: TaskStatus) -> bool:
        return status in TERMINAL_STATES


class InvalidTransition(Exception):
    def __init__(self, current: TaskStatus, target: TaskStatus):
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid transition: {current.value} → {target.value}"
        )
