"""Tests for TaskTemplate CRUD, API routes, and apply-template logic."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api_server.routes.templates import (
    ApplyTemplateRequest,
    TemplateCreate,
    TemplateUpdate,
    _extract_placeholders,
    _substitute_placeholders,
    apply_template,
    create_template,
    delete_template,
    get_template,
    list_templates,
    seed_builtin_templates,
    update_template,
)
from packages.db.models import Base, Edition, Task, TaskTemplate
from packages.db.repositories.template_repo import TemplateRepository

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


def _create_template(db: Session, name: str = "Test Template", goal: str = "Do {thing}") -> TaskTemplate:
    return TemplateRepository.create(
        db,
        name=name,
        goal_template=goal,
        edition=Edition.ENTERPRISE,
        description="A test template",
        parameters={"fields": [{"name": "thing", "label": "Thing", "required": True}]},
    )


def _create_builtin(db: Session, name: str = "Builtin") -> TaskTemplate:
    return TemplateRepository.create(
        db,
        name=name,
        goal_template="Built-in {action}",
        edition=Edition.ENTERPRISE,
        is_builtin=True,
        parameters={"fields": [{"name": "action", "label": "Action", "required": True}]},
    )


# ── TemplateRepository CRUD ───────────────────────────────────────────────


@pytest.mark.unit
class TestTemplateRepoCreate:
    def test_create_template(self, db):
        t = _create_template(db)
        assert t.id
        assert t.name == "Test Template"
        assert t.goal_template == "Do {thing}"
        assert t.is_builtin is False
        assert t.usage_count == 0

    def test_create_with_parameters(self, db):
        params = {"fields": [{"name": "q", "label": "Query", "required": True}]}
        t = TemplateRepository.create(db, name="Search", goal_template="Search {q}", parameters=params)
        assert t.parameters == params

    def test_create_builtin(self, db):
        t = TemplateRepository.create(db, name="Builtin", goal_template="Do stuff", is_builtin=True)
        assert t.is_builtin is True


@pytest.mark.unit
class TestTemplateRepoGetById:
    def test_get_existing(self, db):
        t = _create_template(db)
        found = TemplateRepository.get_by_id(db, t.id)
        assert found is not None
        assert found.name == "Test Template"

    def test_get_nonexistent(self, db):
        found = TemplateRepository.get_by_id(db, "nonexistent-id")
        assert found is None


@pytest.mark.unit
class TestTemplateRepoList:
    def test_list_empty(self, db):
        result = TemplateRepository.list_templates(db)
        assert result == []

    def test_list_with_data(self, db):
        _create_template(db, name="T1")
        _create_template(db, name="T2")
        result = TemplateRepository.list_templates(db)
        assert len(result) == 2

    def test_list_with_edition_filter(self, db):
        TemplateRepository.create(db, name="E", goal_template="G", edition=Edition.PERSONAL)
        _create_template(db)
        result = TemplateRepository.list_templates(db, edition=Edition.ENTERPRISE)
        assert len(result) == 1

    def test_list_pagination(self, db):
        for i in range(5):
            _create_template(db, name=f"T{i}")
        result = TemplateRepository.list_templates(db, skip=0, limit=3)
        assert len(result) == 3
        result2 = TemplateRepository.list_templates(db, skip=3, limit=3)
        assert len(result2) == 2


@pytest.mark.unit
class TestTemplateRepoCount:
    def test_count_empty(self, db):
        assert TemplateRepository.count(db) == 0

    def test_count_with_data(self, db):
        _create_template(db)
        _create_template(db)
        assert TemplateRepository.count(db) == 2

    def test_count_with_edition_filter(self, db):
        TemplateRepository.create(db, name="P", goal_template="G", edition=Edition.PERSONAL)
        _create_template(db)
        assert TemplateRepository.count(db, edition=Edition.ENTERPRISE) == 1


@pytest.mark.unit
class TestTemplateRepoUpdate:
    def test_update_name(self, db):
        t = _create_template(db)
        updated = TemplateRepository.update(db, t.id, name="New Name")
        assert updated.name == "New Name"

    def test_update_nonexistent(self, db):
        result = TemplateRepository.update(db, "nonexistent", name="X")
        assert result is None


@pytest.mark.unit
class TestTemplateRepoDelete:
    def test_delete_existing(self, db):
        t = _create_template(db)
        assert TemplateRepository.delete(db, t.id) is True
        assert TemplateRepository.get_by_id(db, t.id) is None

    def test_delete_nonexistent(self, db):
        assert TemplateRepository.delete(db, "nonexistent") is False


@pytest.mark.unit
class TestTemplateRepoIncrementUsage:
    def test_increment_usage(self, db):
        t = _create_template(db)
        assert t.usage_count == 0
        TemplateRepository.increment_usage(db, t.id)
        db.refresh(t)
        assert t.usage_count == 1

    def test_increment_multiple(self, db):
        t = _create_template(db)
        TemplateRepository.increment_usage(db, t.id)
        TemplateRepository.increment_usage(db, t.id)
        db.refresh(t)
        assert t.usage_count == 2

    def test_increment_nonexistent(self, db):
        # Should not raise
        TemplateRepository.increment_usage(db, "nonexistent")


# ── Placeholder substitution ──────────────────────────────────────────────


@pytest.mark.unit
class TestSubstitutePlaceholders:
    def test_single_placeholder(self):
        result = _substitute_placeholders("Search for {query}", {"query": "Python"})
        assert result == "Search for Python"

    def test_multiple_placeholders(self):
        result = _substitute_placeholders(
            "Extract {fields} from {url}",
            {"fields": "name,email", "url": "https://example.com"},
        )
        assert result == "Extract name,email from https://example.com"

    def test_missing_optional_param(self):
        result = _substitute_placeholders("Search for {query} in {scope}", {"query": "test"})
        assert result == "Search for test in {scope}"

    def test_no_placeholders(self):
        result = _substitute_placeholders("Just a goal", {"query": "test"})
        assert result == "Just a goal"

    def test_empty_params(self):
        result = _substitute_placeholders("Search for {query}", {})
        assert result == "Search for {query}"


@pytest.mark.unit
class TestExtractPlaceholders:
    def test_single(self):
        assert _extract_placeholders("Search {query}") == ["query"]

    def test_multiple(self):
        assert _extract_placeholders("{a} and {b}") == ["a", "b"]

    def test_none(self):
        assert _extract_placeholders("No placeholders") == []

    def test_duplicate(self):
        result = _extract_placeholders("{x} then {x}")
        assert result == ["x", "x"]


# ── Route: create_template ────────────────────────────────────────────────


@pytest.mark.unit
class TestCreateTemplateRoute:
    def test_create_template(self, db):
        body = TemplateCreate(
            name="My Template",
            goal_template="Search {query}",
            description="A search template",
        )
        result = create_template(body, db)
        assert result.success is True
        assert result.data.name == "My Template"
        assert result.data.goal_template == "Search {query}"


# ── Route: list_templates ─────────────────────────────────────────────────


@pytest.mark.unit
class TestListTemplatesRoute:
    def test_list_empty(self, db):
        from apps.api_server.dependencies import CommonQueryParams
        commons = CommonQueryParams(page=1, page_size=20)
        result = list_templates(commons=commons, db=db)
        assert result.data.total == 0
        assert result.data.items == []

    def test_list_with_data(self, db):
        _create_template(db)
        _create_template(db)
        from apps.api_server.dependencies import CommonQueryParams
        commons = CommonQueryParams(page=1, page_size=20)
        result = list_templates(commons=commons, db=db)
        assert result.data.total == 2


# ── Route: get_template ───────────────────────────────────────────────────


@pytest.mark.unit
class TestGetTemplateRoute:
    def test_get_existing(self, db):
        t = _create_template(db)
        result = get_template(t.id, db)
        assert result.data.name == "Test Template"

    def test_get_nonexistent(self, db):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            get_template("nonexistent", db)
        assert exc_info.value.status_code == 404


# ── Route: update_template ────────────────────────────────────────────────


@pytest.mark.unit
class TestUpdateTemplateRoute:
    def test_update_non_builtin(self, db):
        t = _create_template(db)
        body = TemplateUpdate(name="Updated Name")
        result = update_template(t.id, body, db)
        assert result.data.name == "Updated Name"

    def test_update_builtin_rejected(self, db):
        t = _create_builtin(db)
        body = TemplateUpdate(name="Hacked")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            update_template(t.id, body, db)
        assert exc_info.value.status_code == 400

    def test_update_nonexistent(self, db):
        body = TemplateUpdate(name="X")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            update_template("nonexistent", body, db)
        assert exc_info.value.status_code == 404


# ── Route: delete_template ────────────────────────────────────────────────


@pytest.mark.unit
class TestDeleteTemplateRoute:
    def test_delete_non_builtin(self, db):
        t = _create_template(db)
        result = delete_template(t.id, db)
        assert result["success"] is True

    def test_delete_builtin_rejected(self, db):
        t = _create_builtin(db)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            delete_template(t.id, db)
        assert exc_info.value.status_code == 400

    def test_delete_nonexistent(self, db):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            delete_template("nonexistent", db)
        assert exc_info.value.status_code == 404


# ── Route: apply_template ─────────────────────────────────────────────────


@pytest.mark.unit
class TestApplyTemplateRoute:
    def test_apply_with_params(self, db):
        t = _create_template(db, goal="Do {thing}")
        body = ApplyTemplateRequest(params={"thing": "coding"}, user_id="user-1")
        result = apply_template(t.id, body, db)
        assert result.success is True
        assert result.data["goal"] == "Do coding"
        assert result.data["task_id"]

        # Verify usage count incremented
        db.refresh(t)
        assert t.usage_count == 1

        # Verify task was created
        task = db.get(Task, result.data["task_id"])
        assert task is not None
        assert task.goal == "Do coding"

    def test_apply_missing_required_param(self, db):
        t = _create_template(db)
        body = ApplyTemplateRequest(params={}, user_id="default")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            apply_template(t.id, body, db)
        assert exc_info.value.status_code == 400
        assert "thing" in exc_info.value.detail

    def test_apply_nonexistent_template(self, db):
        body = ApplyTemplateRequest(params={"thing": "x"}, user_id="default")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            apply_template("nonexistent", body, db)
        assert exc_info.value.status_code == 404

    def test_apply_with_optional_param_missing(self, db):
        t = TemplateRepository.create(
            db,
            name="Optional",
            goal_template="Search {query} in {scope}",
            parameters={
                "fields": [
                    {"name": "query", "label": "Query", "required": True},
                    {"name": "scope", "label": "Scope", "required": False},
                ],
            },
        )
        body = ApplyTemplateRequest(params={"query": "test"}, user_id="default")
        result = apply_template(t.id, body, db)
        assert result.success is True
        assert result.data["goal"] == "Search test in {scope}"

    def test_apply_multiple_placeholders(self, db):
        t = TemplateRepository.create(
            db,
            name="Multi",
            goal_template="Extract {fields} from {url}",
            parameters={
                "fields": [
                    {"name": "fields", "label": "Fields", "required": True},
                    {"name": "url", "label": "URL", "required": True},
                ],
            },
        )
        body = ApplyTemplateRequest(
            params={"fields": "name,email", "url": "https://example.com"},
            user_id="default",
        )
        result = apply_template(t.id, body, db)
        assert result.data["goal"] == "Extract name,email from https://example.com"

    def test_apply_increments_usage_each_time(self, db):
        t = _create_template(db, goal="Do {thing}")
        body1 = ApplyTemplateRequest(params={"thing": "a"}, user_id="default")
        body2 = ApplyTemplateRequest(params={"thing": "b"}, user_id="default")
        apply_template(t.id, body1, db)
        apply_template(t.id, body2, db)
        db.refresh(t)
        assert t.usage_count == 2

    def test_apply_empty_required_field(self, db):
        t = _create_template(db)
        body = ApplyTemplateRequest(params={"thing": ""}, user_id="default")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            apply_template(t.id, body, db)
        assert exc_info.value.status_code == 400


# ── seed_builtin_templates ────────────────────────────────────────────────


@pytest.mark.unit
class TestSeedBuiltinTemplates:
    def test_seed_creates_builtins(self, db):
        seed_builtin_templates(db)
        templates = TemplateRepository.list_templates(db, limit=100)
        builtin_names = {t.name for t in templates if t.is_builtin}
        assert "Web Search" in builtin_names
        assert "Document Summary" in builtin_names
        assert "Data Extraction" in builtin_names
        assert "Code Review" in builtin_names

    def test_seed_idempotent(self, db):
        seed_builtin_templates(db)
        count_after_first = TemplateRepository.count(db)
        seed_builtin_templates(db)
        count_after_second = TemplateRepository.count(db)
        assert count_after_first == count_after_second

    def test_seed_builtins_are_builtin(self, db):
        seed_builtin_templates(db)
        templates = TemplateRepository.list_templates(db, limit=100)
        builtins = [t for t in templates if t.is_builtin]
        assert all(t.is_builtin for t in builtins)
