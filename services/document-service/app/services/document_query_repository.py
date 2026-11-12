"""Metadata filtering for the document list endpoint.

The list endpoint supports ad-hoc metadata filters (title fragment, content
type) and caller-chosen ordering. The repository builds the predicate list for
those filters and reads the ``documents`` table directly. Every caller-supplied
value is bound as a query parameter, and ORDER BY is resolved from an
allow-list of columns and directions.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import ColumnElement, column, false, func, literal, select, table
from sqlalchemy.types import NullType
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

COLUMNS = (
    "id",
    "title",
    "content",
    "content_type",
    "owner_id",
    "folder_id",
    "is_deleted",
    "is_template",
    "word_count",
    "version",
    "created_at",
    "updated_at",
)

SORTABLE_COLUMNS = frozenset(COLUMNS)
SORT_DIRECTIONS = frozenset({"asc", "desc"})

_documents = table("documents", *(column(name) for name in COLUMNS))


def _untyped(value: str) -> ColumnElement[Any]:
    """Bind ``value`` without a client-side type so the server infers it.

    The id columns are ``uuid`` on PostgreSQL; a string-typed bind would be cast
    to VARCHAR by asyncpg and fail to compare against them.
    """
    return literal(value, type_=NullType())


class InvalidSortError(ValueError):
    """Raised when the caller asks for an ordering outside the allow-list."""


class DocumentQueryRepository:
    """Reads the document table for the list endpoint's metadata filters."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _where(
        self,
        owner_id: str | None,
        title_contains: str | None,
        content_type: str | None,
        folder_id: str | None = None,
    ) -> list[ColumnElement[bool]]:
        c = _documents.c
        clauses: list[ColumnElement[bool]] = [
            c.is_deleted == false(),
            c.is_template == false(),
        ]
        if owner_id:
            clauses.append(c.owner_id == _untyped(owner_id))
        if folder_id:
            clauses.append(c.folder_id == _untyped(folder_id))
        if title_contains:
            clauses.append(func.lower(c.title).like(func.lower(f"%{title_contains}%")))
        if content_type:
            clauses.append(c.content_type == content_type)
        return clauses

    @staticmethod
    def _order_by(sort: str, direction: str) -> ColumnElement[Any]:
        if sort not in SORTABLE_COLUMNS:
            raise InvalidSortError(f"unsupported sort column: {sort!r}")
        normalized = direction.lower()
        if normalized not in SORT_DIRECTIONS:
            raise InvalidSortError(f"unsupported sort direction: {direction!r}")
        col = _documents.c[sort]
        return col.asc() if normalized == "asc" else col.desc()

    async def count_documents(
        self,
        *,
        owner_id: str | None = None,
        title_contains: str | None = None,
        content_type: str | None = None,
        folder_id: str | None = None,
    ) -> int:
        """Count documents matching the metadata filters."""
        stmt = (
            select(func.count())
            .select_from(_documents)
            .where(*self._where(owner_id, title_contains, content_type, folder_id))
        )
        result = await self.db.execute(stmt)
        return int(result.scalar_one())

    async def search_documents(
        self,
        *,
        owner_id: str | None = None,
        title_contains: str | None = None,
        content_type: str | None = None,
        folder_id: str | None = None,
        sort: str = "updated_at",
        direction: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return document rows matching the metadata filters, newest first."""
        order = self._order_by(sort, direction)
        stmt = (
            select(*(_documents.c[name] for name in COLUMNS))
            .where(*self._where(owner_id, title_contains, content_type, folder_id))
            .order_by(order)
            .limit(int(limit))
            .offset(int(offset))
        )
        logger.debug("document_filter_query", sort=sort, direction=direction)
        result = await self.db.execute(stmt)
        return [dict(row._mapping) for row in result]
