"""Structured Logging — structlog-backed JSON/console output with stdlib bridge."""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure structured logging for the platform.

    Uses structlog with a stdlib bridge so that *all* ``logging.getLogger()``
    calls automatically get structlog formatting (JSON or console).
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )

    # Pick renderer
    renderer = (
        structlog.processors.JSONRenderer() if json_output
        else structlog.dev.ConsoleRenderer()
    )

    # Bridge stdlib logging through structlog's formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_task_logger(task_id: str, edition: str = "enterprise") -> structlog.stdlib.BoundLogger:
    """Get a logger with task context pre-attached."""
    return structlog.get_logger("agent.task", task_id=task_id, edition=edition)
