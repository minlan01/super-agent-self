"""Tests for Alembic migrations — verify all 24 models have tables after upgrade."""

import os

os.environ["TESTING"] = "1"

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

# All 23 tables that should exist after a full upgrade
ALL_TABLES = sorted([
    "tasks",
    "task_steps",
    "audit_events",
    "memories",
    "skills",
    "skill_runs",
    "approvals",
    "edition_profiles",
    "conversations",
    "conversation_messages",
    "users",
    "task_templates",
    "task_dependencies",
    "notifications",
    "messaging_channels",
    "message_logs",
    "skill_ratings",
    "skill_subscriptions",
    "skill_promotions",
    "roles",
    "permissions",
    "role_permissions",
    "user_role_assignments",
    "llm_cost_records",
])

ALEMBIC_SCRIPT_LOC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "alembic")
)


def _make_config(db_url: str) -> Config:
    """Build an Alembic Config for testing."""
    cfg = Config()
    cfg.set_main_option("script_location", ALEMBIC_SCRIPT_LOC)
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("prepend_sys_path", ".")
    return cfg


@pytest.fixture(scope="function")
def db_path(tmp_path):
    """Return a path to a fresh SQLite database file."""
    return str(tmp_path / "test_alembic.db")


@pytest.fixture(scope="function")
def db_url(db_path):
    return f"sqlite:///{db_path}"


@pytest.fixture(scope="function")
def alembic_config(db_url):
    return _make_config(db_url)


@pytest.fixture(scope="function")
def engine(db_path):
    """Engine connected to the same SQLite file Alembic migrates."""
    eng = create_engine(f"sqlite:///{db_path}")
    yield eng
    eng.dispose()


def _upgrade(cfg):
    command.upgrade(cfg, "head")


def _downgrade(cfg, target):
    command.downgrade(cfg, target)


# ── Test: all 13 tables exist after upgrade ──────────────────────────────────


class TestAlembicUpgrade:
    """Verify that `alembic upgrade head` creates all 24 tables."""

    def test_all_24_tables_created(self, alembic_config, engine):
        """After upgrade head, all 24 ORM model tables must exist."""
        _upgrade(alembic_config)
        inspector = inspect(engine)
        actual_tables = sorted(inspector.get_table_names())

        for table in ALL_TABLES:
            assert table in actual_tables, f"Table '{table}' missing after upgrade. Got: {actual_tables}"

        non_alembic = [t for t in actual_tables if not t.startswith("alembic_")]
        assert len(non_alembic) == 24, f"Expected 24 tables, got {len(non_alembic)}: {non_alembic}"

    def test_task_templates_columns(self, alembic_config, engine):
        """task_templates table has the correct columns from TaskTemplate model."""
        _upgrade(alembic_config)
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("task_templates")}

        expected = {"id", "name", "description", "goal_template", "edition",
                    "is_builtin", "parameters", "usage_count", "created_at", "updated_at"}
        assert expected == columns, f"task_templates columns mismatch. Got: {columns}"

    def test_task_dependencies_columns(self, alembic_config, engine):
        """task_dependencies table has the correct columns from TaskDependency model."""
        _upgrade(alembic_config)
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("task_dependencies")}

        expected = {"id", "task_id", "depends_on_id", "created_at"}
        assert expected == columns, f"task_dependencies columns mismatch. Got: {columns}"

    def test_task_dependencies_unique_constraint(self, alembic_config, engine):
        """task_dependencies has a unique constraint on (task_id, depends_on_id)."""
        _upgrade(alembic_config)
        inspector = inspect(engine)

        constraints = inspector.get_unique_constraints("task_dependencies")
        constraint_names = [c["name"] for c in constraints]
        assert "uq_task_dep" in constraint_names, (
            f"Unique constraint 'uq_task_dep' not found. Got: {constraint_names}"
        )

        uq = [c for c in constraints if c["name"] == "uq_task_dep"][0]
        assert sorted(uq["column_names"]) == ["depends_on_id", "task_id"]

    def test_task_dependencies_indexes(self, alembic_config, engine):
        """task_dependencies has indexes on task_id and depends_on_id."""
        _upgrade(alembic_config)
        inspector = inspect(engine)
        indexes = inspector.get_indexes("task_dependencies")
        index_names = {idx["name"] for idx in indexes}

        assert "ix_task_deps_task_id" in index_names, f"Missing ix_task_deps_task_id. Got: {index_names}"
        assert "ix_task_deps_depends_on_id" in index_names, f"Missing ix_task_deps_depends_on_id. Got: {index_names}"

    def test_task_dependencies_foreign_keys(self, alembic_config, engine):
        """task_dependencies has foreign keys pointing to tasks.id."""
        _upgrade(alembic_config)
        inspector = inspect(engine)
        fks = inspector.get_foreign_keys("task_dependencies")

        assert len(fks) == 2, f"Expected 2 FK constraints, got {len(fks)}"
        fk_targets = {(fk["constrained_columns"][0], fk["referred_table"]) for fk in fks}
        assert ("task_id", "tasks") in fk_targets
        assert ("depends_on_id", "tasks") in fk_targets


# ── Test: downgrade drops both tables ────────────────────────────────────────


class TestAlembicDowngrade:
    """Verify that downgrade removes the new tables."""

    def test_downgrade_drops_newest_tables(self, alembic_config, engine):
        """Downgrading by one revision should revert the newest migration
        (k7l8m9n0o1p2 — unique constraint on users.sso_id)."""
        _upgrade(alembic_config)

        inspector = inspect(engine)
        indexes = inspector.get_indexes("users")
        sso_idx = [idx for idx in indexes if idx["name"] == "ix_users_sso_id"]
        assert len(sso_idx) == 1
        assert sso_idx[0]["unique"] is True or sso_idx[0]["unique"] == 1

        _downgrade(alembic_config, "-1")

        inspector = inspect(engine)
        indexes = inspector.get_indexes("users")
        sso_idx = [idx for idx in indexes if idx["name"] == "ix_users_sso_id"]
        assert len(sso_idx) == 1
        assert not sso_idx[0]["unique"], "ix_users_sso_id should be non-unique after downgrade"

    def test_downgrade_preserves_other_tables(self, alembic_config, engine):
        """Downgrading by one revision should keep all prior tables intact."""
        _upgrade(alembic_config)
        _downgrade(alembic_config, "-1")

        inspector = inspect(engine)
        tables_after = set(inspector.get_table_names())

        expected_remaining = [
            "tasks", "task_steps", "audit_events", "memories", "skills",
            "skill_runs", "approvals", "edition_profiles", "conversations",
            "conversation_messages", "users", "task_templates", "task_dependencies",
            "notifications", "messaging_channels", "message_logs", "skill_ratings",
            "skill_subscriptions", "skill_promotions",
            "roles", "permissions", "role_permissions", "user_role_assignments",
        ]
        for t in expected_remaining:
            assert t in tables_after, f"Table '{t}' should still exist after downgrade"

    def test_full_downgrade_drops_all(self, alembic_config, engine):
        """Downgrading to base (empty) should remove all tables."""
        _upgrade(alembic_config)
        _downgrade(alembic_config, "base")

        inspector = inspect(engine)
        tables = inspector.get_table_names()
        non_alembic = [t for t in tables if not t.startswith("alembic_")]
        assert len(non_alembic) == 0, f"Expected no tables after full downgrade, got: {non_alembic}"
