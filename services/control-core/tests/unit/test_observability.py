"""Tests for observability — structlog setup, stdlib bridge, task logger."""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from packages.observability.structured_logger import (
    get_task_logger,
    setup_logging,
)


# Shared processors for test formatters — must match setup_logging()
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


@pytest.mark.unit
class TestStructlogJSONOutput:
    """Verify that stdlib loggers produce valid JSON when json_output=True."""

    def test_json_output_basic_record(self):
        setup_logging(level="DEBUG", json_output=True)
        root = logging.getLogger()

        # Capture the output
        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record)  # type: ignore[assignment]
        root.handlers = [handler]

        logger = logging.getLogger("test.json")
        logger.info("hello world")

        assert len(records) == 1
        assert records[0].getMessage() == "hello world"
        assert records[0].levelname == "INFO"
        assert records[0].name == "test.json"

    def test_json_formatter_produces_valid_json(self):
        setup_logging(level="DEBUG", json_output=True)

        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_make_json_formatter())
        root = logging.getLogger()
        root.handlers = [handler]

        logging.getLogger("test.json.fields").info("test message", extra={"task_id": "t-1"})

        output = stream.getvalue().strip()
        data = json.loads(output)
        assert data["level"] == "info"
        assert data["event"] == "test message"
        assert data["logger"] == "test.json.fields"

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
            logging.getLogger("test.exc").error("failed", exc_info=True)

        output = stream.getvalue().strip()
        data = json.loads(output)
        assert "exception" in data

    def test_json_unicode_message(self):
        setup_logging(level="DEBUG", json_output=True)

        import io

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_make_json_formatter())
        root = logging.getLogger()
        root.handlers = [handler]

        logging.getLogger("test.unicode").info("你好世界 🌍")

        output = stream.getvalue().strip()
        data = json.loads(output)
        assert "你好世界" in data["event"]


@pytest.mark.unit
class TestSetupLogging:
    def test_setup_changes_root_level(self):
        root = logging.getLogger()
        original_level = root.level

        setup_logging(level="DEBUG", json_output=False)

        assert root.level == logging.DEBUG
        # Restore
        root.setLevel(original_level)

    def test_setup_json_uses_processor_formatter(self):
        root = logging.getLogger()
        setup_logging(level="INFO", json_output=True)

        # Should have a handler with structlog ProcessorFormatter
        has_processor = any(
            isinstance(h.formatter, structlog.stdlib.ProcessorFormatter)
            for h in root.handlers
        )
        assert has_processor

    def test_setup_text_uses_processor_formatter(self):
        root = logging.getLogger()
        setup_logging(level="INFO", json_output=False)

        # Both modes use ProcessorFormatter — the renderer differs
        has_processor = any(
            isinstance(h.formatter, structlog.stdlib.ProcessorFormatter)
            for h in root.handlers
        )
        assert has_processor

    def test_setup_clears_existing_handlers(self):
        root = logging.getLogger()
        root.addHandler(logging.StreamHandler())
        original_count = len(root.handlers)

        setup_logging(level="INFO", json_output=False)

        # Should have exactly 1 handler (cleared + added one)
        assert len(root.handlers) == 1


@pytest.mark.unit
class TestGetTaskLogger:
    def test_returns_structlog_bound_logger(self):
        bound_logger = get_task_logger("task-abc")
        # structlog.get_logger returns a BoundLoggerLazyProxy; after binding it's a BoundLogger
        assert hasattr(bound_logger, "info")
        assert hasattr(bound_logger, "warning")
        assert hasattr(bound_logger, "error")

    def test_bound_context_has_task_id(self):
        bound_logger = get_task_logger("task-xyz", edition="personal")
        # The initial_values are stored in the proxy's _context dict
        assert bound_logger._context.get("task_id") == "task-xyz"
        assert bound_logger._context.get("edition") == "personal"

    def test_bound_context_default_edition(self):
        bound_logger = get_task_logger("task-default")
        assert bound_logger._context.get("edition") == "enterprise"
