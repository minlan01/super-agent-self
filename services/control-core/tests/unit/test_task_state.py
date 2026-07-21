"""Tests for task_state module."""

import pytest

from packages.agent_core.task_state import (
    TERMINAL_STATES,
    InvalidTransition,
    TaskStateMachine,
)
from packages.db.models import TaskStatus


class TestTaskStateMachine:
    """Test state machine transition logic."""

    def test_valid_transition_pending_to_planning(self):
        assert TaskStateMachine.can_transition(TaskStatus.PENDING, TaskStatus.PLANNING)

    def test_valid_transition_pending_to_cancelled(self):
        assert TaskStateMachine.can_transition(TaskStatus.PENDING, TaskStatus.CANCELLED)

    def test_valid_transition_planning_to_executing(self):
        assert TaskStateMachine.can_transition(TaskStatus.PLANNING, TaskStatus.EXECUTING)

    def test_valid_transition_planning_to_awaiting_approval(self):
        assert TaskStateMachine.can_transition(TaskStatus.PLANNING, TaskStatus.AWAITING_APPROVAL)

    def test_valid_transition_planning_to_failed(self):
        assert TaskStateMachine.can_transition(TaskStatus.PLANNING, TaskStatus.FAILED)

    def test_valid_transition_planning_to_cancelled(self):
        assert TaskStateMachine.can_transition(TaskStatus.PLANNING, TaskStatus.CANCELLED)

    def test_valid_transition_awaiting_to_executing(self):
        assert TaskStateMachine.can_transition(TaskStatus.AWAITING_APPROVAL, TaskStatus.EXECUTING)

    def test_valid_transition_awaiting_to_failed(self):
        assert TaskStateMachine.can_transition(TaskStatus.AWAITING_APPROVAL, TaskStatus.FAILED)

    def test_valid_transition_executing_to_completed(self):
        assert TaskStateMachine.can_transition(TaskStatus.EXECUTING, TaskStatus.COMPLETED)

    def test_valid_transition_executing_to_failed(self):
        assert TaskStateMachine.can_transition(TaskStatus.EXECUTING, TaskStatus.FAILED)

    # Invalid transitions
    def test_invalid_pending_to_completed(self):
        assert not TaskStateMachine.can_transition(TaskStatus.PENDING, TaskStatus.COMPLETED)

    def test_invalid_pending_to_executing(self):
        assert not TaskStateMachine.can_transition(TaskStatus.PENDING, TaskStatus.EXECUTING)

    def test_invalid_completed_to_anything(self):
        for target in TaskStatus:
            if target == TaskStatus.COMPLETED:
                continue
            assert not TaskStateMachine.can_transition(TaskStatus.COMPLETED, target), \
                f"Completed should not transition to {target.value}"

    def test_invalid_failed_to_anything(self):
        for target in TaskStatus:
            if target == TaskStatus.FAILED:
                continue
            assert not TaskStateMachine.can_transition(TaskStatus.FAILED, target), \
                f"Failed should not transition to {target.value}"

    def test_invalid_cancelled_to_anything(self):
        for target in TaskStatus:
            if target == TaskStatus.CANCELLED:
                continue
            assert not TaskStateMachine.can_transition(TaskStatus.CANCELLED, target), \
                f"Cancelled should not transition to {target.value}"

    def test_invalid_executing_to_planning(self):
        assert not TaskStateMachine.can_transition(TaskStatus.EXECUTING, TaskStatus.PLANNING)

    # Transition method
    def test_transition_returns_target(self):
        result = TaskStateMachine.transition(TaskStatus.PENDING, TaskStatus.PLANNING)
        assert result == TaskStatus.PLANNING

    def test_transition_raises_on_invalid(self):
        with pytest.raises(InvalidTransition) as exc_info:
            TaskStateMachine.transition(TaskStatus.COMPLETED, TaskStatus.PENDING)
        assert "completed" in str(exc_info.value).lower()
        assert "pending" in str(exc_info.value).lower()

    # Terminal states
    def test_terminal_states(self):
        assert TaskStatus.COMPLETED in TERMINAL_STATES
        assert TaskStatus.FAILED in TERMINAL_STATES
        assert TaskStatus.CANCELLED in TERMINAL_STATES

    def test_is_terminal(self):
        assert TaskStateMachine.is_terminal(TaskStatus.COMPLETED)
        assert TaskStateMachine.is_terminal(TaskStatus.FAILED)
        assert TaskStateMachine.is_terminal(TaskStatus.CANCELLED)

    def test_not_terminal(self):
        assert not TaskStateMachine.is_terminal(TaskStatus.PENDING)
        assert not TaskStateMachine.is_terminal(TaskStatus.PLANNING)
        assert not TaskStateMachine.is_terminal(TaskStatus.EXECUTING)

    # Full lifecycle happy path
    def test_full_lifecycle_happy_path(self):
        states = [
            TaskStatus.PENDING,
            TaskStatus.PLANNING,
            TaskStatus.EXECUTING,
            TaskStatus.COMPLETED,
        ]
        for i in range(len(states) - 1):
            assert TaskStateMachine.can_transition(states[i], states[i + 1])

    def test_full_lifecycle_with_approval(self):
        states = [
            TaskStatus.PENDING,
            TaskStatus.PLANNING,
            TaskStatus.AWAITING_APPROVAL,
            TaskStatus.EXECUTING,
            TaskStatus.COMPLETED,
        ]
        for i in range(len(states) - 1):
            assert TaskStateMachine.can_transition(states[i], states[i + 1])


class TestInvalidTransition:
    def test_attributes(self):
        exc = InvalidTransition(TaskStatus.COMPLETED, TaskStatus.PENDING)
        assert exc.current == TaskStatus.COMPLETED
        assert exc.target == TaskStatus.PENDING

    def test_message_format(self):
        exc = InvalidTransition(TaskStatus.COMPLETED, TaskStatus.PENDING)
        assert "completed" in str(exc)
        assert "pending" in str(exc)
        assert "→" in str(exc)
