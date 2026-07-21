"""Tests for Evaluation and Observability — TaskEvaluator, structured logger."""

import json
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.db.models import (
    Base,
    Edition,
    RiskLevel,
    StepStatus,
    Task,
    TaskStatus,
    TaskStep,
)
from packages.evaluation.task_evaluator import TaskEvaluator
import structlog

from packages.observability.structured_logger import get_task_logger, setup_logging


def _make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


# ── TaskEvaluator ─────────────────────────────────────────────────────────────


class TestTaskEvaluator:
    def setup_method(self):
        self.evaluator = TaskEvaluator()
        self.db = _make_session()

    def teardown_method(self):
        self.db.close()

    def _create_task(self, status=TaskStatus.COMPLETED):
        task = Task(goal="Test task", status=status, edition=Edition.ENTERPRISE)
        self.db.add(task)
        self.db.commit()
        return task

    def _add_step(self, task, order=1, status=StepStatus.COMPLETED, risk=RiskLevel.LOW):
        step = TaskStep(
            task_id=task.id, step_order=order, tool_name="test.tool",
            status=status, risk_level=risk,
        )
        self.db.add(step)
        self.db.commit()
        return step

    def test_evaluate_completed_task(self):
        task = self._create_task(TaskStatus.COMPLETED)
        s1 = self._add_step(task, 1, StepStatus.COMPLETED)
        s2 = self._add_step(task, 2, StepStatus.COMPLETED)

        steps = [s1, s2]
        result = self.evaluator.evaluate_task(task, steps)

        assert result["task_id"] == task.id
        assert result["success"] is True
        assert result["total_steps"] == 2
        assert result["completed_steps"] == 2
        assert result["failed_steps"] == 0
        assert result["step_success_rate"] == 1.0
        assert result["quality_score"] > 0

    def test_evaluate_failed_task(self):
        task = self._create_task(TaskStatus.FAILED)
        s1 = self._add_step(task, 1, StepStatus.COMPLETED)
        s2 = self._add_step(task, 2, StepStatus.FAILED)

        result = self.evaluator.evaluate_task(task, [s1, s2])
        assert result["success"] is False
        assert result["failed_steps"] == 1
        assert result["step_success_rate"] == 0.5

    def test_evaluate_with_skipped_steps(self):
        task = self._create_task()
        s1 = self._add_step(task, 1, StepStatus.COMPLETED)
        s2 = self._add_step(task, 2, StepStatus.SKIPPED)
        s3 = self._add_step(task, 3, StepStatus.COMPLETED)

        result = self.evaluator.evaluate_task(task, [s1, s2, s3])
        assert result["efficiency"] == pytest.approx(0.67, abs=0.01)

    def test_evaluate_high_risk_steps(self):
        task = self._create_task()
        s1 = self._add_step(task, 1, StepStatus.COMPLETED, RiskLevel.HIGH)
        s2 = self._add_step(task, 2, StepStatus.COMPLETED, RiskLevel.CRITICAL)

        result = self.evaluator.evaluate_task(task, [s1, s2])
        assert result["high_risk_steps"] == 2

    def test_evaluate_empty_steps(self):
        task = self._create_task()
        result = self.evaluator.evaluate_task(task, [])
        assert result["total_steps"] == 0
        assert result["step_success_rate"] == 0.0
        assert result["efficiency"] == 1.0

    def test_quality_score_formula(self):
        task = self._create_task()
        s1 = self._add_step(task, 1, StepStatus.COMPLETED)
        s2 = self._add_step(task, 2, StepStatus.COMPLETED)
        s3 = self._add_step(task, 3, StepStatus.SKIPPED)

        result = self.evaluator.evaluate_task(task, [s1, s2, s3])
        # success_rate = 2/3 ≈ 0.67, efficiency = 2/3 ≈ 0.67
        # quality = 0.67*0.6 + 0.67*0.4 ≈ 0.67
        assert result["quality_score"] == pytest.approx(0.67, abs=0.01)

    def test_get_system_metrics(self):
        t1 = self._create_task(TaskStatus.COMPLETED)
        t2 = self._create_task(TaskStatus.FAILED)
        t3 = self._create_task(TaskStatus.PENDING)

        metrics = self.evaluator.get_system_metrics(self.db)
        assert metrics["total_tasks"] == 3
        assert metrics["completed_tasks"] == 1
        assert metrics["failed_tasks"] == 1
        assert metrics["success_rate"] == pytest.approx(0.33, abs=0.01)

    def test_get_system_metrics_empty_db(self):
        metrics = self.evaluator.get_system_metrics(self.db)
        assert metrics["total_tasks"] == 0
        assert metrics["success_rate"] == 0.0


# ── structlog bridge (was JSONFormatter) ──────────────────────────────────────

_SHARED_PROCESSORS = [
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]


def _make_json_formatter():
    """Build a ProcessorFormatter with JSON renderer and shared pre-chain."""
    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=_SHARED_PROCESSORS,
    )


class TestStructlogJSONOutput:
    """Verify that stdlib loggers produce valid JSON when json_output=True."""

    def test_json_output_basic_record(self):
        setup_logging(level="DEBUG", json_output=True)

        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_make_json_formatter())
        root = logging.getLogger()
        root.handlers = [handler]

        logging.getLogger("test.json").info("Hello world")

        output = stream.getvalue().strip()
        data = json.loads(output)
        assert data["level"] == "info"
        assert data["event"] == "Hello world"
        assert data["logger"] == "test.json"

    def test_json_output_with_exception(self):
        setup_logging(level="DEBUG", json_output=True)

        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_make_json_formatter())
        root = logging.getLogger()
        root.handlers = [handler]

        try:
            raise ValueError("test error")
        except ValueError:
            logging.getLogger("test.exc").error("fail", exc_info=True)

        output = stream.getvalue().strip()
        data = json.loads(output)
        assert "exception" in data
        assert "test error" in data["exception"]

    def test_json_unicode_message(self):
        setup_logging(level="DEBUG", json_output=True)

        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_make_json_formatter())
        root = logging.getLogger()
        root.handlers = [handler]

        logging.getLogger("test.unicode").info("搜索中文内容")

        output = stream.getvalue().strip()
        data = json.loads(output)
        assert "搜索中文内容" in data["event"]


# ── setup_logging / get_task_logger ───────────────────────────────────────────


class TestSetupLogging:
    def test_setup_creates_handler(self):
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            setup_logging(level="DEBUG", json_output=False)
            assert len(root.handlers) >= 1
            assert root.level == logging.DEBUG
        finally:
            root.handlers = original_handlers

    def test_setup_json_uses_processor_formatter(self):
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            setup_logging(level="INFO", json_output=True)
            assert any(
                isinstance(h.formatter, structlog.stdlib.ProcessorFormatter)
                for h in root.handlers
            )
        finally:
            root.handlers = original_handlers


class TestGetTaskLogger:
    def test_task_logger_has_context(self):
        adapter = get_task_logger("task-42", edition="enterprise")
        # structlog BoundLogger stores context in _context dict
        assert adapter._context.get("task_id") == "task-42"
        assert adapter._context.get("edition") == "enterprise"

    def test_task_logger_default_edition(self):
        adapter = get_task_logger("task-1")
        assert adapter._context.get("edition") == "enterprise"
