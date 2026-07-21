"""Analytics endpoints — time-series data and platform statistics."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

logger = logging.getLogger(__name__)
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from apps.api_server.dependencies import get_db, require_permission
from packages.agent_core.schemas import (
    AnomalyDetectionResponse,
    AnalyticsOverviewResponse,
    CostAnalyticsResponse,
    MemoriesGrowthResponse,
    RecentActivityResponse,
    RealtimeMetricsResponse,
    SkillBenchmarkResponse,
    SkillsPerformanceResponse,
    TaskStatusDistributionResponse,
    TaskTrendResponse,
)
from packages.db.models import (
    AuditEvent,
    LLMCostRecord,
    Memory,
    Skill,
    SkillRun,
    SkillStatus,
    Task,
    TaskStatus,
)
from packages.db.session import run_async

router = APIRouter()


def _overview_query(db: Session) -> dict[str, Any]:
    """Sync DB query for overview stats.

    Consolidates 4 queries (1 Task scan + 3 scalar queries) into 2 queries
    using a CTE that combines the Skill, Memory, and AuditEvent counts in a
    single round-trip.
    """
    # Single Task scan: total, completed, failed
    task_row = db.execute(
        select(
            func.count().label("total"),
            func.sum(case((Task.status == TaskStatus.COMPLETED, 1), else_=0)).label("completed"),
            func.sum(case((Task.status == TaskStatus.FAILED, 1), else_=0)).label("failed"),
        )
    ).one()

    total_tasks = int(task_row.total or 0)
    completed_tasks = int(task_row.completed or 0)
    failed_tasks = int(task_row.failed or 0)
    finished = completed_tasks + failed_tasks
    success_rate = round((completed_tasks / finished) * 100, 1) if finished > 0 else 0.0

    # Subqueries: combine active_skills, total_memories, recent_activity into one query
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    active_skills_sq = (
        select(func.count().label("v"))
        .select_from(Skill)
        .where(Skill.status != SkillStatus.DISABLED)
        .scalar_subquery()
    )
    total_memories_sq = (
        select(func.count().label("v"))
        .select_from(Memory)
        .scalar_subquery()
    )
    recent_activity_sq = (
        select(func.count().label("v"))
        .select_from(AuditEvent)
        .where(AuditEvent.created_at >= cutoff)
        .scalar_subquery()
    )

    counts_row = db.execute(
        select(
            active_skills_sq.label("active_skills"),
            total_memories_sq.label("total_memories"),
            recent_activity_sq.label("recent_activity"),
        )
    ).one()

    active_skills = int(counts_row.active_skills or 0)
    total_memories = int(counts_row.total_memories or 0)
    recent_activity = int(counts_row.recent_activity or 0)

    return {
        "total_tasks": total_tasks,
        "success_rate": success_rate,
        "active_skills": active_skills,
        "total_memories": total_memories,
        "recent_activity_24h": recent_activity,
    }


def _task_trend_query(db: Session, days: int) -> dict[str, Any]:
    """Sync DB query for daily task creation counts."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(func.date(Task.created_at), func.count())
        .where(Task.created_at >= cutoff)
        .group_by(func.date(Task.created_at))
        .order_by(func.date(Task.created_at))
    ).all()

    trend = [{"date": str(r[0]), "count": r[1]} for r in rows]
    return {"days": days, "trend": trend}


def _task_status_distribution_query(db: Session) -> dict[str, Any]:
    """Sync DB query for current task status distribution."""
    rows = db.execute(
        select(Task.status, func.count())
        .group_by(Task.status)
    ).all()

    distribution = {status.value: 0 for status in TaskStatus}
    for status_val, count in rows:
        distribution[status_val.value] = count

    return {"distribution": distribution}


def _skills_performance_query(db: Session) -> dict[str, Any]:
    """Sync DB query for skill performance ranking."""
    rows = db.execute(
        select(Skill.name, Skill.success_rate, Skill.total_runs, Skill.status)
        .order_by(Skill.success_rate.desc(), Skill.total_runs.desc())
        .limit(20)
    ).all()

    skills = [
        {
            "name": r[0],
            "success_rate": round(r[1] * 100, 1),
            "total_runs": r[2],
            "status": r[3].value,
        }
        for r in rows
    ]
    return {"skills": skills}


def _memories_growth_query(db: Session, days: int) -> dict[str, Any]:
    """Sync DB query for memory creation trend."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(func.date(Memory.created_at), func.count())
        .where(Memory.created_at >= cutoff)
        .group_by(func.date(Memory.created_at))
        .order_by(func.date(Memory.created_at))
    ).all()

    # Build cumulative growth
    cumulative = 0
    growth = []
    for date_str, count in rows:
        cumulative += count
        growth.append({"date": str(date_str), "count": count, "cumulative": cumulative})

    return {"days": days, "growth": growth}


def _recent_activity_query(db: Session, limit: int) -> dict[str, Any]:
    """Sync DB query for recent audit events."""
    rows = db.execute(
        select(AuditEvent)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).scalars().all()

    events = [
        {
            "id": e.id,
            "event_type": e.event_type.value,
            "actor": e.actor,
            "task_id": e.task_id,
            "detail": e.detail,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]
    return {"events": events, "total": len(events)}


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/overview", response_model=AnalyticsOverviewResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_overview(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Overall platform statistics."""
    return await run_async(_overview_query, bind_engine=db.bind)


@router.get("/tasks/trend", response_model=TaskTrendResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_task_trend(
    days: int = Query(30, ge=1, le=365, description="Number of days"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Daily task creation counts for the last N days."""
    return await run_async(_task_trend_query, days, bind_engine=db.bind)


@router.get("/tasks/status-distribution", response_model=TaskStatusDistributionResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_task_status_distribution(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Current task status distribution."""
    return await run_async(_task_status_distribution_query, bind_engine=db.bind)


@router.get("/skills/performance", response_model=SkillsPerformanceResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_skills_performance(
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Top skills by success rate and usage."""
    return await run_async(_skills_performance_query, bind_engine=db.bind)


@router.get("/memories/growth", response_model=MemoriesGrowthResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_memories_growth(
    days: int = Query(30, ge=1, le=365, description="Number of days"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Memory creation trend over N days."""
    return await run_async(_memories_growth_query, days, bind_engine=db.bind)


@router.get("/activity/recent", response_model=RecentActivityResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_recent_activity(
    limit: int = Query(50, ge=1, le=200, description="Number of events"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent audit events."""
    return await run_async(_recent_activity_query, limit, bind_engine=db.bind)


# ── Real-time Execution Metrics ─────────────────────────────────────────


def _realtime_metrics_query(db: Session) -> dict[str, Any]:
    """Sync DB query for real-time execution metrics.

    Consolidates 4 queries into 1 using scalar subqueries:
    - task_agg: Task unconditional conditional aggregation
    - avg_exec: avg execution time for completed tasks in last 24h
    - active_skills: active skills count
    - total_cost: total cost from LLMCostRecord
    All subqueries are composed in a single SELECT, so only 1 DB round-trip.
    """
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)

    # Scalar subqueries — each returns a single value
    running_sq = (
        select(func.sum(case((Task.status == TaskStatus.EXECUTING, 1), else_=0)))
        .scalar_subquery()
    )
    completed_last_hour_sq = (
        select(func.sum(case(
            (and_(Task.status == TaskStatus.COMPLETED, Task.updated_at >= one_hour_ago), 1),
            else_=0,
        )))
        .scalar_subquery()
    )
    failed_last_hour_sq = (
        select(func.sum(case(
            (and_(Task.status == TaskStatus.FAILED, Task.updated_at >= one_hour_ago), 1),
            else_=0,
        )))
        .scalar_subquery()
    )
    tasks_24h_sq = (
        select(func.sum(case((Task.created_at >= day_ago, 1), else_=0)))
        .scalar_subquery()
    )

    # Subquery 2: avg execution time for completed tasks in last 24h
    avg_exec_sq = (
        select(
            func.avg(
                func.julianday(Task.updated_at) - func.julianday(Task.created_at)
            )
        )
        .where(
            Task.status == TaskStatus.COMPLETED,
            Task.updated_at >= day_ago,
        )
        .scalar_subquery()
    )

    # Subquery 3: active skills count
    active_skills_sq = (
        select(func.count())
        .select_from(Skill)
        .where(Skill.status != SkillStatus.DISABLED)
        .scalar_subquery()
    )

    # Subquery 4: total cost
    total_cost_sq = (
        select(func.coalesce(func.sum(LLMCostRecord.estimated_cost_usd), 0.0))
        .scalar_subquery()
    )

    # Single query composing all subqueries
    row = db.execute(
        select(
            running_sq.label("running"),
            completed_last_hour_sq.label("completed_last_hour"),
            failed_last_hour_sq.label("failed_last_hour"),
            tasks_24h_sq.label("tasks_24h"),
            avg_exec_sq.label("avg_exec_seconds"),
            active_skills_sq.label("active_skills"),
            total_cost_sq.label("total_cost"),
        )
    ).one()

    running = int(row.running or 0)
    completed_last_hour = int(row.completed_last_hour or 0)
    failed_last_hour = int(row.failed_last_hour or 0)
    tasks_24h = int(row.tasks_24h or 0)
    avg_execution_time = (
        round(float(row.avg_exec_seconds) * 86400, 2) if row.avg_exec_seconds else None
    )
    active_skills = int(row.active_skills or 0)
    total_cost = float(row.total_cost or 0.0)

    tasks_per_hour = round(tasks_24h / 24.0, 2)

    return {
        "running_tasks": running,
        "completed_last_hour": completed_last_hour,
        "failed_last_hour": failed_last_hour,
        "avg_execution_time_seconds": avg_execution_time,
        "tasks_per_hour": tasks_per_hour,
        "active_skills": active_skills,
        "total_cost_usd": round(total_cost, 6),
    }


@router.get("/execution/realtime", response_model=RealtimeMetricsResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_realtime_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Real-time execution metrics snapshot."""
    return await run_async(_realtime_metrics_query, bind_engine=db.bind)


# ── Cost Analytics ───────────────────────────────────────────────────────


def _cost_summary_query(db: Session, days: int) -> dict[str, Any]:
    """Sync DB query for cost summary with breakdown.

    Consolidates 4 scalar aggregates into a single query, then fetches
    the breakdown. Total: 2 queries (down from 5).
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Single query for totals
    totals_row = db.execute(
        select(
            func.coalesce(func.sum(LLMCostRecord.estimated_cost_usd), 0.0).label("total_cost"),
            func.coalesce(func.sum(LLMCostRecord.prompt_tokens), 0).label("total_prompt"),
            func.coalesce(func.sum(LLMCostRecord.completion_tokens), 0).label("total_completion"),
            func.count().label("total_requests"),
        ).where(LLMCostRecord.created_at >= cutoff)
    ).one()

    total_cost = float(totals_row.total_cost or 0.0)
    total_prompt = int(totals_row.total_prompt or 0)
    total_completion = int(totals_row.total_completion or 0)
    total_requests = int(totals_row.total_requests or 0)

    # Breakdown by provider/model
    breakdown_rows = db.execute(
        select(
            LLMCostRecord.provider,
            LLMCostRecord.model,
            func.sum(LLMCostRecord.prompt_tokens).label("prompt_tokens"),
            func.sum(LLMCostRecord.completion_tokens).label("completion_tokens"),
            func.count().label("requests"),
            func.sum(LLMCostRecord.estimated_cost_usd).label("cost"),
        ).where(LLMCostRecord.created_at >= cutoff)
        .group_by(LLMCostRecord.provider, LLMCostRecord.model)
        .order_by(func.sum(LLMCostRecord.estimated_cost_usd).desc())
    ).all()

    breakdown = [
        {
            "provider": r[0],
            "model": r[1],
            "prompt_tokens": r[2] or 0,
            "completion_tokens": r[3] or 0,
            "requests": r[4] or 0,
            "estimated_cost_usd": round(r[5] or 0.0, 6),
        }
        for r in breakdown_rows
    ]

    return {
        "days": days,
        "total_cost_usd": round(total_cost, 6),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_requests": total_requests,
        "breakdown": breakdown,
    }


def _cost_trend_query(db: Session, days: int) -> dict[str, Any]:
    """Sync DB query for daily cost trend."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(
            func.date(LLMCostRecord.created_at),
            func.sum(LLMCostRecord.estimated_cost_usd),
            func.sum(LLMCostRecord.prompt_tokens),
            func.sum(LLMCostRecord.completion_tokens),
            func.count(),
        ).where(LLMCostRecord.created_at >= cutoff)
        .group_by(func.date(LLMCostRecord.created_at))
        .order_by(func.date(LLMCostRecord.created_at))
    ).all()

    trend = [
        {
            "date": str(r[0]),
            "cost_usd": round(r[1] or 0.0, 6),
            "prompt_tokens": r[2] or 0,
            "completion_tokens": r[3] or 0,
            "requests": r[4] or 0,
        }
        for r in rows
    ]

    total_cost = sum(p["cost_usd"] for p in trend)
    total_prompt = sum(p["prompt_tokens"] for p in trend)
    total_completion = sum(p["completion_tokens"] for p in trend)
    total_requests = sum(p["requests"] for p in trend)

    return {
        "days": days,
        "total_cost_usd": round(total_cost, 6),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_requests": total_requests,
        "trend": trend,
    }


@router.get("/costs/summary", response_model=CostAnalyticsResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_cost_summary(
    days: int = Query(30, ge=1, le=365, description="Number of days"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Cost summary with breakdown by provider/model."""
    return await run_async(_cost_summary_query, days, bind_engine=db.bind)


@router.get("/costs/trend", response_model=CostAnalyticsResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_cost_trend(
    days: int = Query(30, ge=1, le=365, description="Number of days"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Daily cost trend over N days."""
    return await run_async(_cost_trend_query, days, bind_engine=db.bind)


# ── Skill Benchmarking ──────────────────────────────────────────────────


def _skill_benchmark_query(db: Session, top_n: int) -> dict[str, Any]:
    """Sync DB query for skill performance benchmarking.

    Uses batch aggregation to avoid N+1 queries (was 3 queries per skill,
    now a fixed small number of queries regardless of skill count).
    """
    # Get top skills
    skills = db.execute(
        select(Skill).where(Skill.status != SkillStatus.DISABLED)
        .order_by(Skill.total_runs.desc())
        .limit(top_n)
    ).scalars().all()

    if not skills:
        return {"skills": []}

    skill_ids = [s.id for s in skills]
    skill_map = {s.id: s for s in skills}

    # Single query: avg execution time + avg cost + run count + benchmark durations, grouped by skill_id
    bench_rows = db.execute(
        select(
            SkillRun.skill_id,
            func.avg(SkillRun.execution_time).label("avg_exec_time"),
            func.avg(SkillRun.estimated_cost_usd).label("avg_cost"),
            func.count(SkillRun.id).label("run_count"),
            func.avg(SkillRun.with_skill_duration).label("avg_with"),
            func.avg(SkillRun.without_skill_duration).label("avg_without"),
        ).where(SkillRun.skill_id.in_(skill_ids))
        .group_by(SkillRun.skill_id)
    ).all()

    bench_map = {r[0]: r for r in bench_rows}

    # Single query: recent runs for trend data (all at once, group in Python)
    recent_rows = db.execute(
        select(SkillRun.skill_id, SkillRun.success, SkillRun.created_at)
        .where(SkillRun.skill_id.in_(skill_ids))
        .order_by(SkillRun.created_at.desc())
        .limit(top_n * 7)
    ).all()

    # Group recent runs by skill_id, keep last 7 per skill
    trend_map: dict[str, list[dict]] = {}
    for skill_id, success, created_at in recent_rows:
        if skill_id not in trend_map:
            trend_map[skill_id] = []
        if len(trend_map[skill_id]) < 7:
            trend_map[skill_id].append({
                "success": success,
                "created_at": created_at.isoformat() if created_at else None,
            })

    # Build results preserving original skill ordering
    result = []
    for skill in skills:
        bench = bench_map.get(skill.id)
        avg_exec = bench[1] if bench else None
        avg_cost = bench[2] if bench else None

        trend = list(reversed(trend_map.get(skill.id, [])))

        avg_with = bench[4] if bench else None
        avg_without = bench[5] if bench else None
        improvement = round((avg_without - avg_with) / avg_without, 2) if avg_without and avg_with and avg_without > 0 else None

        result.append({
            "name": skill.name,
            "success_rate": round(skill.success_rate * 100, 1),
            "total_runs": skill.total_runs,
            "avg_execution_time": round(float(avg_exec), 2) if avg_exec else None,
            "avg_cost_usd": round(float(avg_cost), 6) if avg_cost else None,
            "with_skill_duration": round(float(avg_with), 2) if avg_with else None,
            "without_skill_duration": round(float(avg_without), 2) if avg_without else None,
            "improvement_ratio": improvement,
            "trend": trend,
        })

    return {"skills": result}


@router.get("/skills/benchmark", response_model=SkillBenchmarkResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_skill_benchmark(
    top_n: int = Query(20, ge=1, le=100, description="Number of top skills"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Skill performance benchmarking with execution time and cost."""
    return await run_async(_skill_benchmark_query, top_n, bind_engine=db.bind)


# ── Anomaly Detection ───────────────────────────────────────────────────


def _anomaly_detection_query(db: Session) -> dict[str, Any]:
    """Sync DB query for anomaly detection.

    Consolidates 4 Task scalar queries into 1 conditional-aggregation query
    and 2 LLMCostRecord scalar queries into 1. Total: 3 queries (down from 7).
    """
    now = datetime.now(UTC)
    alerts: list[dict[str, Any]] = []

    # 1. Failure spike detection: compare last 1h failure rate vs last 24h
    one_hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)

    # Single Task scan: compute recent/baseline failures and totals in one pass
    task_row = db.execute(
        select(
            func.sum(case(
                (and_(Task.status == TaskStatus.FAILED, Task.updated_at >= one_hour_ago), 1),
                else_=0,
            )).label("recent_failures"),
            func.sum(case((Task.updated_at >= one_hour_ago, 1), else_=0)).label("recent_total"),
            func.sum(case(
                (and_(Task.status == TaskStatus.FAILED, Task.updated_at >= day_ago), 1),
                else_=0,
            )).label("baseline_failures"),
            func.sum(case((Task.updated_at >= day_ago, 1), else_=0)).label("baseline_total"),
        )
    ).one()

    recent_failures = int(task_row.recent_failures or 0)
    recent_total = int(task_row.recent_total or 0)
    baseline_failures = int(task_row.baseline_failures or 0)
    baseline_total = int(task_row.baseline_total or 0)

    recent_rate = (recent_failures / recent_total) if recent_total > 0 else 0.0
    baseline_rate = (baseline_failures / baseline_total) if baseline_total > 0 else 0.0

    if recent_rate > 0.5 and recent_rate > baseline_rate * 2 and recent_total >= 3:
        severity = "critical" if recent_rate > 0.8 else "warning"
        alerts.append({
            "type": "failure_spike",
            "severity": severity,
            "message": f"Failure rate {(recent_rate*100):.1f}% in last hour (baseline: {(baseline_rate*100):.1f}%)",
            "resource": "tasks",
            "value": round(recent_rate, 4),
            "threshold": round(baseline_rate * 2, 4) if baseline_rate > 0 else 0.5,
            "detected_at": now.isoformat(),
        })

    # 2. Cost spike detection: recent cost and daily average in one query
    cost_row = db.execute(
        select(
            func.coalesce(func.sum(
                case(
                    (LLMCostRecord.created_at >= one_hour_ago, LLMCostRecord.estimated_cost_usd),
                    else_=0.0,
                )
            ), 0.0).label("recent_cost"),
            func.coalesce(func.sum(
                case(
                    (LLMCostRecord.created_at >= day_ago, LLMCostRecord.estimated_cost_usd),
                    else_=0.0,
                )
            ), 0.0).label("day_cost"),
        )
    ).one()

    recent_cost = float(cost_row.recent_cost or 0.0)
    daily_avg_cost = float(cost_row.day_cost or 0.0) / 24.0

    if daily_avg_cost > 0 and recent_cost > daily_avg_cost * 3:
        alerts.append({
            "type": "cost_spike",
            "severity": "warning",
            "message": f"Cost ${recent_cost:.4f} in last hour (daily avg/hour: ${daily_avg_cost:.4f})",
            "resource": "llm_costs",
            "value": round(recent_cost, 6),
            "threshold": round(daily_avg_cost * 3, 6),
            "detected_at": now.isoformat(),
        })

    # 3. Skill degradation detection: skills with declining success rate
    degraded_skills = db.execute(
        select(Skill.name, Skill.success_rate, Skill.total_runs)
        .where(
            Skill.status != SkillStatus.DISABLED,
            Skill.success_rate < 0.5,
            Skill.total_runs >= 5,
        )
    ).all()

    for name, rate, runs in degraded_skills:
        alerts.append({
            "type": "skill_degradation",
            "severity": "critical" if rate < 0.3 else "warning",
            "message": f"Skill '{name}' success rate {(rate*100):.1f}% ({runs} runs)",
            "resource": f"skill:{name}",
            "value": round(rate, 4),
            "threshold": 0.5,
            "detected_at": now.isoformat(),
        })

    return {"alerts": alerts, "checked_at": now.isoformat()}


@router.get("/anomalies", response_model=AnomalyDetectionResponse, dependencies=[Depends(require_permission("analytics", "read"))])
async def get_anomalies(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Detect anomalies: failure spikes, cost spikes, skill degradation."""
    return await run_async(_anomaly_detection_query, bind_engine=db.bind)
