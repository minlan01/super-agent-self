"""Add audit/approval/dependency/messaging indexes uncovered by round-5 audit.

Revision ID: m1n2o3p4q5r6
Revises: k7l8m9n0o1p2
Create Date: 2026-06-12

Adds indexes that the round-5 deep audit identified as missing for high-frequency
filter columns:

* ``audit_events.actor`` — filter audit log by acting user.
* ``approvals.requested_by`` / ``approvals.approved_by`` — "my submissions" /
  "my approvals" views.
* ``task_dependencies (task_id, depends_on_id)`` — composite index covering both
  ``remove_dependency`` lookup and ``get_execution_order`` IN-clause filter
  (the existing single-column indexes can each only serve one half).
* ``message_logs.platform`` — cross-channel filter by platform.

All ``op.create_index`` calls use ``IF NOT EXISTS`` semantics via inspector
guards so re-running on databases that already have these indexes (e.g. a
fresh ``models.py``-generated SQLite) is a no-op.
"""

from alembic import op
from sqlalchemy import inspect

revision = "m1n2o3p4q5r6"
down_revision = "k7l8m9n0o1p2"
branch_labels = None
depends_on = None


def _index_names(inspector, table: str) -> set[str]:
    try:
        return {idx["name"] for idx in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    audit_idx = _index_names(inspector, "audit_events")
    if "ix_audit_events_actor" not in audit_idx:
        op.create_index("ix_audit_events_actor", "audit_events", ["actor"])

    approval_idx = _index_names(inspector, "approvals")
    if "ix_approvals_requested_by" not in approval_idx:
        op.create_index("ix_approvals_requested_by", "approvals", ["requested_by"])
    if "ix_approvals_approved_by" not in approval_idx:
        op.create_index("ix_approvals_approved_by", "approvals", ["approved_by"])

    dep_idx = _index_names(inspector, "task_dependencies")
    if "ix_task_dependencies_task_depends" not in dep_idx:
        op.create_index(
            "ix_task_dependencies_task_depends",
            "task_dependencies",
            ["task_id", "depends_on_id"],
        )

    msg_idx = _index_names(inspector, "message_logs")
    if "ix_message_logs_platform" not in msg_idx:
        op.create_index("ix_message_logs_platform", "message_logs", ["platform"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    msg_idx = _index_names(inspector, "message_logs")
    if "ix_message_logs_platform" in msg_idx:
        op.drop_index("ix_message_logs_platform", table_name="message_logs")

    dep_idx = _index_names(inspector, "task_dependencies")
    if "ix_task_dependencies_task_depends" in dep_idx:
        op.drop_index("ix_task_dependencies_task_depends", table_name="task_dependencies")

    approval_idx = _index_names(inspector, "approvals")
    if "ix_approvals_approved_by" in approval_idx:
        op.drop_index("ix_approvals_approved_by", table_name="approvals")
    if "ix_approvals_requested_by" in approval_idx:
        op.drop_index("ix_approvals_requested_by", table_name="approvals")

    audit_idx = _index_names(inspector, "audit_events")
    if "ix_audit_events_actor" in audit_idx:
        op.drop_index("ix_audit_events_actor", table_name="audit_events")
