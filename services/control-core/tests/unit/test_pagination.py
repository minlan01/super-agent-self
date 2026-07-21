"""Tests for packages.db.pagination — generic paginate() utility."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from packages.db.pagination import PaginatedResult, paginate

Base = declarative_base()


class _Item(Base):
    __tablename__ = "test_items"

    id = Column(Integer, primary_key=True)
    name = Column(String(50))


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Insert 25 test rows
    for i in range(1, 26):
        session.add(_Item(id=i, name=f"item-{i}"))
    session.commit()

    yield session
    session.close()


# ── Basic pagination ─────────────────────────────────────────────────────


class TestPaginate:
    def test_page_one_of_three(self, db_session: Session):
        from sqlalchemy import select

        stmt = select(_Item).order_by(_Item.id)
        result = paginate(db_session, stmt, page=1, page_size=10)

        assert isinstance(result, PaginatedResult)
        assert len(result.items) == 10
        assert result.total == 25
        assert result.page == 1
        assert result.page_size == 10
        assert result.total_pages == 3
        assert result.has_next is True
        assert result.has_prev is False

    def test_page_two(self, db_session: Session):
        from sqlalchemy import select

        stmt = select(_Item).order_by(_Item.id)
        result = paginate(db_session, stmt, page=2, page_size=10)

        assert len(result.items) == 10
        assert result.page == 2
        assert result.has_next is True
        assert result.has_prev is True

    def test_last_page_partial(self, db_session: Session):
        from sqlalchemy import select

        stmt = select(_Item).order_by(_Item.id)
        result = paginate(db_session, stmt, page=3, page_size=10)

        assert len(result.items) == 5
        assert result.total_pages == 3
        assert result.has_next is False
        assert result.has_prev is True

    def test_empty_results(self, db_session: Session):
        from sqlalchemy import select

        stmt = select(_Item).where(_Item.id > 999)
        result = paginate(db_session, stmt, page=1, page_size=10)

        assert result.items == []
        assert result.total == 0
        assert result.total_pages == 0
        assert result.has_next is False
        assert result.has_prev is False

    def test_max_page_size_clamping(self, db_session: Session):
        from sqlalchemy import select

        stmt = select(_Item).order_by(_Item.id)
        result = paginate(db_session, stmt, page=1, page_size=500, max_page_size=50)

        assert result.page_size == 50
        assert len(result.items) == 25  # only 25 rows exist

    def test_page_clamping_below_one(self, db_session: Session):
        from sqlalchemy import select

        stmt = select(_Item).order_by(_Item.id)
        result = paginate(db_session, stmt, page=-5, page_size=10)

        assert result.page == 1
        assert result.has_prev is False
        assert len(result.items) == 10


# ── to_dict ───────────────────────────────────────────────────────────────


class TestPaginatedResultToDict:
    def test_to_dict_without_serializer(self):
        result = PaginatedResult(
            items=[1, 2, 3],
            total=10,
            page=1,
            page_size=3,
            total_pages=4,
            has_next=True,
            has_prev=False,
        )
        d = result.to_dict()

        assert d == {
            "items": [1, 2, 3],
            "total": 10,
            "page": 1,
            "page_size": 3,
            "total_pages": 4,
            "has_next": True,
            "has_prev": False,
        }

    def test_to_dict_with_serializer(self):
        result = PaginatedResult(
            items=[1, 2, 3],
            total=3,
            page=1,
            page_size=10,
            total_pages=1,
            has_next=False,
            has_prev=False,
        )
        d = result.to_dict(item_serializer=lambda x: {"value": x})

        assert d["items"] == [{"value": 1}, {"value": 2}, {"value": 3}]
