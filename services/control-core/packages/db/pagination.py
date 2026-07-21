"""Generic pagination utility for SQLAlchemy queries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

T = TypeVar("T")


@dataclass
class PaginatedResult(Generic[T]):
    """Container for a page of results plus pagination metadata."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool

    def to_dict(self, item_serializer: Callable[[Any], Any] | None = None) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        If *item_serializer* is provided it is called for every item;
        otherwise the raw items are included as-is.
        """
        items = [item_serializer(i) for i in self.items] if item_serializer else self.items
        return {
            "items": items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "has_next": self.has_next,
            "has_prev": self.has_prev,
        }


def paginate(
    db: Session,
    query: Select,
    page: int = 1,
    page_size: int = 20,
    max_page_size: int = 100,
) -> PaginatedResult[Any]:
    """Paginate a SQLAlchemy query."""
    page = max(1, page)
    page_size = min(max(1, page_size), max_page_size)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0

    # Calculate pages
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    # Apply pagination
    items = list(db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all())

    return PaginatedResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )
