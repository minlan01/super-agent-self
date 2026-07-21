"""Health and metrics endpoints — readiness probe and platform statistics."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends
from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_db
from packages.agent_core.schemas import PlatformMetricsResponse, ReadinessCheckResponse
from packages.agent_core.version import __version__
from packages.db.models import Memory, Task, TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter()

_start_time = time.time()
_redis_pool: Any | None = None


def _get_redis_pool(redis_url: str) -> Any:
    """Get or create a shared Redis connection pool for health checks."""
    global _redis_pool
    try:
        import redis
    except ImportError:
        return None
    if _redis_pool is None:
        try:
            _redis_pool = redis.Redis(
                connection_pool=redis.ConnectionPool.from_url(
                    redis_url,
                    socket_connect_timeout=3,
                    max_connections=2,
                ),
            )
        except Exception:
            return None
    return _redis_pool


def _check_redis() -> str:
    config_path = Path("configs/cache.yaml")
    if not config_path.exists():
        return "not_configured"
    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return "not_configured"
    cache_cfg = cfg.get("cache", {})
    if cache_cfg.get("backend") != "redis":
        return "not_configured"
    try:
        import redis
        redis_url = cache_cfg.get("redis_url", "redis://localhost:6379/0")
        client = _get_redis_pool(redis_url)
        if client is None:
            return "not_installed"
        client.ping()
        return "ok"
    except ImportError:
        return "not_installed"
    except Exception as e:
        global _redis_pool
        _redis_pool = None
        logger.warning("Redis health check failed: %s", e)
        return "error"


@router.get(
    "/ready",
    response_model=ReadinessCheckResponse,
    summary="Readiness probe",
    description="Deep readiness probe — checks DB and LLM provider health.",
)
def readiness_check(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Deep readiness probe — checks DB connectivity and LLM providers.

    Returns HTTP 503 when any critical dependency is unhealthy so that
    orchestrators (Kubernetes, load balancers) can route traffic away.
    """
    checks: dict[str, str] = {}
    status_code = 200

    try:
        if db is not None:
            db.scalar(select(1))
        checks["db"] = "ok"
    except Exception:
        logger.warning("Readiness check: DB health check failed", exc_info=True)
        checks["db"] = "error"
        status_code = 503

    try:
        from packages.llm_gateway.provider_router import get_module_router
        router = get_module_router()
        if router is not None:
            health = router.get_health_summary()
            unhealthy = [name for name, info in health.items() if not info.get("healthy", True)]
            if unhealthy:
                checks["llm"] = f"degraded: {len(unhealthy)} unhealthy"
            else:
                checks["llm"] = "ok"
        else:
            checks["llm"] = "not_initialized"
    except Exception:
        logger.warning("Readiness check: LLM health check failed", exc_info=True)
        checks["llm"] = "error"
        # LLM degraded is not fatal — still serve 200

    redis_status = _check_redis()
    if redis_status != "not_configured":
        checks["redis"] = redis_status

    ready = all(v == "ok" for v in checks.values())
    if not ready:
        status_code = 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "ready": ready,
            "checks": checks,
        },
    )


@router.get(
    "/metrics",
    response_model=PlatformMetricsResponse,
    summary="Platform metrics",
    description="Aggregate platform statistics including task counts by status, memory counts, uptime, and version.",
)
def get_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Platform metrics — task counts, memory count, uptime."""
    # Task counts by status — single GROUP BY query instead of N+1
    rows = db.execute(
        select(Task.status, func.count()).group_by(Task.status)
    ).all()
    task_counts = {status.value: 0 for status in TaskStatus}
    for status, count in rows:
        task_counts[status.value] = count

    # Memory counts — single query with conditional aggregation
    memory_row = db.execute(
        select(
            func.count().label("total"),
            func.sum(func.cast(Memory.is_active, Integer)).label("active"),
        )
    ).one()
    memory_count = memory_row.total or 0
    active_memories = memory_row.active or 0

    uptime_seconds = int(time.time() - _start_time)

    pool_info: dict[str, Any] = {}
    try:
        engine = db.get_bind()
        pool = engine.pool
        pool_info = {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
        }
    except Exception:
        logger.debug("Could not extract DB pool info", exc_info=True)

    return {
        "tasks": task_counts,
        "total_tasks": sum(task_counts.values()),
        "memories": {"total": memory_count, "active": active_memories},
        "db_pool": pool_info,
        "uptime_seconds": uptime_seconds,
        "version": __version__,
    }
