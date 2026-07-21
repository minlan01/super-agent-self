"""Unit tests for approval API routes — list, get, resolve."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api_server.dependencies import CommonQueryParams
from apps.api_server.routes.approvals import (
    get_approval,
    list_approvals,
    resolve_approval,
)
from packages.agent_core.schemas import ApprovalCreate, ApprovalResolve
from packages.db.models import Approval, ApprovalStatus, ApprovalType, Base, Edition
from packages.db.repositories.approval_repo import ApprovalRepository

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


def _create_approval(db, **overrides) -> Approval:
    """Helper to create an approval with sensible defaults."""
    defaults = dict(
        approval_type=ApprovalType.HIGH_RISK_STEP,
        target_id="step-001",
        edition=Edition.ENTERPRISE,
        requested_by="tester",
        reason="test reason",
    )
    defaults.update(overrides)
    return ApprovalRepository.create(db, ApprovalCreate(**defaults))


# ── list_approvals ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestListApprovals:
    def test_empty_list(self, db):
        """No approvals returns an empty data list."""
        commons = CommonQueryParams(page=1, page_size=20)
        result = list_approvals(commons=commons, approval_type=None, db=db)
        assert result.data == []

    def test_list_with_data(self, db):
        """Created approvals appear in the list."""
        _create_approval(db)
        commons = CommonQueryParams(page=1, page_size=20)
        result = list_approvals(commons=commons, approval_type=None, db=db)
        assert len(result.data) == 1
        assert result.data[0].status == ApprovalStatus.PENDING

    def test_list_filters_by_pending_status(self, db):
        """status=pending uses the list_pending path."""
        a1 = _create_approval(db, target_id="s1")
        # Resolve one so it's no longer pending
        ApprovalRepository.resolve(db, a1.id, ApprovalResolve(approved=True, approved_by="admin"))
        _create_approval(db, target_id="s2")

        commons = CommonQueryParams(page=1, page_size=20)
        result = list_approvals(commons=commons, status="pending", approval_type=None, db=db)
        assert len(result.data) == 1
        assert result.data[0].target_id == "s2"

    def test_list_filters_by_non_pending_status(self, db):
        """status=approved uses the general query path."""
        a1 = _create_approval(db, target_id="s1")
        ApprovalRepository.resolve(db, a1.id, ApprovalResolve(approved=True, approved_by="admin"))
        _create_approval(db, target_id="s2")

        commons = CommonQueryParams(page=1, page_size=20)
        result = list_approvals(commons=commons, status="approved", approval_type=None, db=db)
        assert len(result.data) == 1
        assert result.data[0].status == ApprovalStatus.APPROVED

    def test_list_filters_by_edition(self, db):
        """edition filter narrows results."""
        _create_approval(db, edition=Edition.ENTERPRISE)
        _create_approval(db, edition=Edition.PERSONAL)

        commons = CommonQueryParams(page=1, page_size=20)
        result = list_approvals(commons=commons, edition="enterprise", approval_type=None, db=db)
        assert len(result.data) == 1
        assert result.data[0].edition == Edition.ENTERPRISE

    def test_list_pagination(self, db):
        """Pagination (page_size) limits returned items."""
        for i in range(5):
            _create_approval(db, target_id=f"s{i}")

        commons = CommonQueryParams(page=1, page_size=2)
        result = list_approvals(commons=commons, approval_type=None, db=db)
        assert len(result.data) == 2


# ── get_approval ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGetApproval:
    def test_get_found(self, db):
        """Existing approval returns data."""
        approval = _create_approval(db)
        result = get_approval(approval_id=approval.id, db=db)
        assert result["success"] is True
        assert result["data"]["id"] == approval.id
        assert result["data"]["status"] == "pending"

    def test_get_not_found(self, db):
        """Non-existent approval raises 404."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            get_approval(approval_id="nonexistent", db=db)
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()


# ── resolve_approval ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestResolveApproval:
    def test_approve(self, db):
        """Approving a pending approval succeeds."""
        approval = _create_approval(db)
        body = ApprovalResolve(approved=True, approved_by="admin", reason="LGTM")
        result = resolve_approval(approval_id=approval.id, body=body, db=db)
        assert result.success is True
        assert "approved" in result.message.lower()

        # Verify DB state
        refreshed = db.get(Approval, approval.id)
        assert refreshed.status == ApprovalStatus.APPROVED
        assert refreshed.approved_by == "admin"

    def test_reject(self, db):
        """Rejecting a pending approval succeeds."""
        approval = _create_approval(db)
        body = ApprovalResolve(approved=False, approved_by="admin", reason="bad")
        result = resolve_approval(approval_id=approval.id, body=body, db=db)
        assert result.success is True
        assert "rejected" in result.message.lower()

        refreshed = db.get(Approval, approval.id)
        assert refreshed.status == ApprovalStatus.REJECTED

    def test_resolve_not_found(self, db):
        """Resolving a non-existent approval raises 404."""
        from fastapi import HTTPException

        body = ApprovalResolve(approved=True, approved_by="admin")
        with pytest.raises(HTTPException) as exc_info:
            resolve_approval(approval_id="nonexistent", body=body, db=db)
        assert exc_info.value.status_code == 404

    def test_resolve_already_resolved(self, db):
        """Resolving an already-resolved approval raises 400."""
        from fastapi import HTTPException

        approval = _create_approval(db)
        body = ApprovalResolve(approved=True, approved_by="admin")
        resolve_approval(approval_id=approval.id, body=body, db=db)

        # Try to resolve again
        body2 = ApprovalResolve(approved=False, approved_by="admin")
        with pytest.raises(HTTPException) as exc_info:
            resolve_approval(approval_id=approval.id, body=body2, db=db)
        assert exc_info.value.status_code == 400
        assert "already" in exc_info.value.detail.lower()
