#!/usr/bin/env python3
"""Seed demo data into the agent platform database.

Usage:
    python scripts/seed_demo_data.py              # seed into default DB
    python scripts/seed_demo_data.py --clear       # clear existing data first
    python scripts/seed_demo_data.py --db-path ./data/demo.db
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.db.models import (
    Approval,
    ApprovalStatus,
    ApprovalType,
    AuditEvent,
    AuditEventType,
    Base,
    Edition,
    Memory,
    MemoryType,
    RiskLevel,
    Skill,
    SkillRun,
    SkillStatus,
    StepStatus,
    Task,
    TaskStep,
    TaskStatus,
)
from packages.db.session import _DEFAULT_DB_URL


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


# ── Demo Data Definitions ────────────────────────────────────────────────


def _seed_tasks() -> list[dict]:
    """Return task definitions to seed."""
    return [
        {
            "id": "task-001",
            "goal": "搜索竞争对手产品定价并生成 Word 报告",
            "status": TaskStatus.COMPLETED,
            "risk_level": RiskLevel.LOW,
            "result": "已完成竞品定价分析报告，保存至 workspace/outputs/pricing_report.docx",
            "steps": [
                {"order": 1, "tool": "browser.open", "args": {"url": "https://example.com/products"}, "status": StepStatus.COMPLETED, "result": "页面加载成功"},
                {"order": 2, "tool": "browser.extract_text", "args": {"selectors": [".price", ".product-name"]}, "status": StepStatus.COMPLETED, "result": "提取到 15 个产品价格"},
                {"order": 3, "tool": "file.write_docx", "args": {"filename": "pricing_report.docx"}, "status": StepStatus.COMPLETED, "result": "报告已生成"},
            ],
            "audits": [
                AuditEventType.TASK_CREATED,
                AuditEventType.PLAN_GENERATED,
                AuditEventType.POLICY_APPROVED,
                AuditEventType.STEP_COMPLETED,
                AuditEventType.TASK_COMPLETED,
            ],
        },
        {
            "id": "task-002",
            "goal": "自动化填写内部系统测试表单",
            "status": TaskStatus.FAILED,
            "risk_level": RiskLevel.HIGH,
            "result": None,
            "error": "Policy rejected: 表单提交操作被安全策略拦截",
            "steps": [
                {"order": 1, "tool": "browser.open", "args": {"url": "https://internal.example.com/form"}, "status": StepStatus.COMPLETED, "result": "页面加载成功"},
                {"order": 2, "tool": "browser.click", "args": {"selector": "#submit-btn"}, "status": StepStatus.REJECTED, "result": None, "error": "Policy rejected: 自动提交表单被禁止"},
            ],
            "audits": [
                AuditEventType.TASK_CREATED,
                AuditEventType.PLAN_GENERATED,
                AuditEventType.POLICY_REJECTED,
                AuditEventType.TASK_FAILED,
            ],
        },
        {
            "id": "task-003",
            "goal": "提取官网新闻列表并整理为 Markdown",
            "status": TaskStatus.COMPLETED,
            "risk_level": RiskLevel.LOW,
            "result": "已提取 20 条新闻，保存至 workspace/outputs/news.md",
            "steps": [
                {"order": 1, "tool": "browser.open", "args": {"url": "https://example.com/news"}, "status": StepStatus.COMPLETED, "result": "页面加载成功"},
                {"order": 2, "tool": "browser.extract_text", "args": {"selectors": [".news-item"]}, "status": StepStatus.COMPLETED, "result": "提取到 20 条新闻"},
                {"order": 3, "tool": "file.write_md", "args": {"filename": "news.md"}, "status": StepStatus.COMPLETED, "result": "Markdown 已保存"},
            ],
            "audits": [
                AuditEventType.TASK_CREATED,
                AuditEventType.PLAN_GENERATED,
                AuditEventType.TASK_COMPLETED,
            ],
        },
        {
            "id": "task-004",
            "goal": "分析季度销售数据并生成可视化报告",
            "status": TaskStatus.EXECUTING,
            "risk_level": RiskLevel.MEDIUM,
            "result": None,
            "steps": [
                {"order": 1, "tool": "file.list", "args": {"path": "workspace/raw/"}, "status": StepStatus.COMPLETED, "result": "找到 3 个 CSV 文件"},
                {"order": 2, "tool": "file.read", "args": {"path": "workspace/raw/q1_sales.csv"}, "status": StepStatus.COMPLETED, "result": "读取 1500 行数据"},
                {"order": 3, "tool": "file.write_docx", "args": {"filename": "sales_report.docx"}, "status": StepStatus.EXECUTING, "result": None},
            ],
            "audits": [
                AuditEventType.TASK_CREATED,
                AuditEventType.PLAN_GENERATED,
                AuditEventType.POLICY_APPROVED,
            ],
        },
        {
            "id": "task-005",
            "goal": "抓取 GitHub 热门项目列表",
            "status": TaskStatus.PENDING,
            "risk_level": RiskLevel.LOW,
            "steps": [],
            "audits": [AuditEventType.TASK_CREATED],
        },
    ]


def _seed_memories() -> list[dict]:
    return [
        {
            "type": MemoryType.EXECUTION_EXPERIENCE,
            "title": "竞品网站爬取最佳实践",
            "summary": "使用 browser.extract_text 配合 CSS 选择器批量提取价格信息，比 browser.click 逐个点击效率高 5 倍",
            "content": {"tool": "browser.extract_text", "tip": "使用 .price 选择器", "source_url": "https://example.com"},
            "importance": 0.85,
            "confidence": 0.9,
            "source_task_id": "task-001",
        },
        {
            "type": MemoryType.WORKFLOW_PATTERN,
            "title": "网页→Word 报告标准流程",
            "summary": "标准三步流程：browser.open → browser.extract_text → file.write_docx，适用于大多数信息采集场景",
            "content": {"steps": ["browser.open", "browser.extract_text", "file.write_docx"], "avg_time_seconds": 45},
            "importance": 0.75,
            "confidence": 0.95,
            "source_task_id": "task-001",
        },
        {
            "type": MemoryType.ERROR_SOLUTION,
            "title": "表单提交被 Policy 拦截的解决方案",
            "summary": "自动提交表单被安全策略禁止。解决方案：改用 file.write_docx 生成离线表单，或申请人工审批",
            "content": {"error": "Policy rejected: auto-submit", "solution": "use file.write_docx or request approval"},
            "importance": 0.7,
            "confidence": 0.8,
            "source_task_id": "task-002",
        },
        {
            "type": MemoryType.DOMAIN_KNOWLEDGE,
            "title": "内部系统 URL 规则",
            "summary": "内网系统使用 internal.example.com 域名，需配置 allowed_domains 才可访问",
            "content": {"domain": "internal.example.com", "requires_config": "allowed_domains"},
            "importance": 0.6,
            "confidence": 0.85,
        },
        {
            "type": MemoryType.USER_PREFERENCE,
            "title": "用户偏好：报告格式",
            "summary": "用户倾向使用 Word 格式而非 PDF，文件名使用中文描述",
            "content": {"preferred_format": "docx", "naming": "chinese_descriptive"},
            "importance": 0.5,
            "confidence": 0.9,
        },
    ]


def _seed_skills() -> list[dict]:
    return [
        {
            "id": "skill-001",
            "name": "web_scrape_to_docx",
            "status": SkillStatus.STABLE,
            "description": "从网页抓取信息并生成 Word 报告的标准流程",
            "definition": {
                "steps": [
                    {"tool": "browser.open", "args_template": {"url": "{{target_url}}"}},
                    {"tool": "browser.extract_text", "args_template": {"selectors": "{{selectors}}"}},
                    {"tool": "file.write_docx", "args_template": {"filename": "{{output_name}}.docx"}},
                ],
                "trigger_patterns": ["抓取", "爬取", "报告", "采集"],
            },
            "success_rate": 0.92,
            "total_runs": 12,
            "source_task_id": "task-001",
            "runs": [
                {"task_id": "task-001", "success": True, "metrics": {"duration_s": 35}},
                {"task_id": "task-003", "success": True, "metrics": {"duration_s": 28}},
                {"task_id": "task-004", "success": False, "metrics": {"duration_s": 12}, "error": "文件路径错误"},
            ],
        },
        {
            "id": "skill-002",
            "name": "price_monitor",
            "status": SkillStatus.CANDIDATE,
            "description": "监控指定商品价格变动并发送通知（待审批）",
            "definition": {
                "steps": [
                    {"tool": "browser.open", "args_template": {"url": "{{product_url}}"}},
                    {"tool": "browser.extract_text", "args_template": {"selectors": [".price"]}},
                ],
                "trigger_patterns": ["价格", "监控", "比价"],
            },
            "success_rate": 0.0,
            "total_runs": 0,
        },
        {
            "id": "skill-003",
            "name": "legacy_report_gen",
            "status": SkillStatus.DISABLED,
            "description": "旧版报告生成流程（已被 web_scrape_to_docx 替代）",
            "definition": {
                "steps": [
                    {"tool": "browser.open", "args_template": {"url": "{{url}}"}},
                    {"tool": "browser.click", "args_template": {"selector": "#download"}},
                ],
            },
            "success_rate": 0.45,
            "total_runs": 5,
        },
    ]


def _seed_approvals(skills: list[dict]) -> list[dict]:
    return [
        {
            "id": "approval-001",
            "approval_type": ApprovalType.SKILL,
            "target_id": skills[0]["id"],
            "status": ApprovalStatus.APPROVED,
            "requested_by": "system",
            "approved_by": "admin",
            "reason": "自动审批：成功率 > 80%",
        },
        {
            "id": "approval-002",
            "approval_type": ApprovalType.SKILL,
            "target_id": skills[1]["id"],
            "status": ApprovalStatus.PENDING,
            "requested_by": "system",
            "reason": "新技能待审批：price_monitor 需要确认安全性",
        },
        {
            "id": "approval-003",
            "approval_type": ApprovalType.HIGH_RISK_STEP,
            "target_id": "task-002",
            "status": ApprovalStatus.REJECTED,
            "requested_by": "system",
            "approved_by": "admin",
            "reason": "拒绝：自动提交表单不符合安全策略",
        },
    ]


# ── Seed Logic ───────────────────────────────────────────────────────────


def clear_db(session: Session) -> None:
    """Delete all data from all tables."""
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    print("  Cleared all tables.")


def seed_all(session: Session) -> dict[str, int]:
    """Seed all demo data. Returns counts."""
    counts = {}
    now = _now()

    # ── Tasks + Steps + Audits ─────────────────────────────────────────
    task_defs = _seed_tasks()
    for td in task_defs:
        task = Task(
            id=td["id"],
            goal=td["goal"],
            status=td.get("status", TaskStatus.PENDING),
            risk_level=td.get("risk_level"),
            result=td.get("result"),
            error=td.get("error"),
            created_at=now - timedelta(minutes=len(task_defs) * 10),
            updated_at=now - timedelta(minutes=5),
        )
        session.add(task)
        counts.setdefault("tasks", 0)
        counts["tasks"] += 1

        for sd in td.get("steps", []):
            step = TaskStep(
                task_id=td["id"],
                step_order=sd["order"],
                tool_name=sd["tool"],
                args=sd.get("args"),
                status=sd.get("status", StepStatus.PENDING),
                result=sd.get("result"),
                error=sd.get("error"),
            )
            session.add(step)
            counts["steps"] = counts.get("steps", 0) + 1

        for i, evt in enumerate(td.get("audits", [])):
            audit = AuditEvent(
                task_id=td["id"],
                edition=Edition.ENTERPRISE,
                event_type=evt,
                detail={"source": "demo_seed"},
            )
            session.add(audit)
            counts["audits"] = counts.get("audits", 0) + 1

    # ── Memories ───────────────────────────────────────────────────────
    for md in _seed_memories():
        mem = Memory(
            memory_type=md["type"],
            title=md["title"],
            summary=md["summary"],
            content=md.get("content"),
            content_hash=_hash(md["summary"]),
            importance_score=md.get("importance", 0.5),
            confidence_score=md.get("confidence", 0.5),
            source_task_id=md.get("source_task_id"),
        )
        session.add(mem)
        counts["memories"] = counts.get("memories", 0) + 1

    # ── Skills + Runs ──────────────────────────────────────────────────
    skill_defs = _seed_skills()
    for sd in skill_defs:
        skill = Skill(
            id=sd.get("id"),
            name=sd["name"],
            status=sd.get("status", SkillStatus.CANDIDATE),
            definition=sd["definition"],
            description=sd.get("description"),
            success_rate=sd.get("success_rate", 0.0),
            total_runs=sd.get("total_runs", 0),
            source_task_id=sd.get("source_task_id"),
        )
        session.add(skill)
        counts["skills"] = counts.get("skills", 0) + 1

        for rd in sd.get("runs", []):
            run = SkillRun(
                skill_id=sd.get("id"),
                task_id=rd["task_id"],
                success=rd["success"],
                metrics=rd.get("metrics"),
                error=rd.get("error"),
            )
            session.add(run)
            counts["skill_runs"] = counts.get("skill_runs", 0) + 1

    # ── Approvals ──────────────────────────────────────────────────────
    for ad in _seed_approvals(skill_defs):
        approval = Approval(
            id=ad.get("id"),
            approval_type=ad["approval_type"],
            target_id=ad["target_id"],
            status=ad.get("status", ApprovalStatus.PENDING),
            requested_by=ad.get("requested_by", "system"),
            approved_by=ad.get("approved_by"),
            reason=ad.get("reason"),
            resolved_at=now if ad.get("status") != ApprovalStatus.PENDING else None,
        )
        session.add(approval)
        counts["approvals"] = counts.get("approvals", 0) + 1

    session.commit()
    return counts


logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Seed demo data into the agent platform DB")
    parser.add_argument("--db-path", default=None, help="Path to SQLite DB file (default: data/agent_platform.db)")
    parser.add_argument("--clear", action="store_true", help="Clear existing data before seeding")
    args = parser.parse_args()

    db_url = _DEFAULT_DB_URL
    if args.db_path:
        db_url = f"sqlite:///{args.db_path}"

    print(f"Seeding demo data into {db_url}")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    SessionMaker = sessionmaker(bind=engine)
    session = SessionMaker()

    try:
        if args.clear:
            clear_db(session)

        counts = seed_all(session)
        print("  Seeded:")
        for name, count in counts.items():
            print(f"    {name}: {count}")
        print(f"  Total records: {sum(counts.values())}")
        print("Done!")
    except Exception as e:
        session.rollback()
        logger.exception("Seeding failed")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
