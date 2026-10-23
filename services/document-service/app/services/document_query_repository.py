"""Metadata filtering for the document list endpoint.

The list endpoint supports ad-hoc metadata filters (title fragment, content
type) and caller-chosen ordering. The repository builds the predicate list for
those filters and reads the ``documents`` table directly. Caller-supplied values
are always bound as query parameters, and ``ORDER BY`` is resolved from an
allow-list of columns and directions.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import ColumnElement, Uuid, bindparam, column, false, func, select, table
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

# Untyped columns return rows exactly as the driver reads them.
_documents = table("documents", *(column(name) for name in COLUMNS))


class InvalidSortError(ValueError):
    """``sort`` or ``direction`` is not in the allow-list."""


def _order_by(sort: str, direction: str) -> ColumnElement[Any]:
    if sort not in SORTABLE_COLUMNS:
        raise InvalidSortError(f"sort must be one of: {', '.join(sorted(SORTABLE_COLUMNS))}")
    normalized = direction.lower()
    if normalized not in SORT_DIRECTIONS:
        raise InvalidSortError("direction must be one of: asc, desc")
    col = _documents.c[sort]
    return col.asc() if normalized == "asc" else col.desc()


def _uuid_param(name: str, value: Any) -> Any:
    return bindparam(name, uuid.UUID(str(value)), type_=Uuid())


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
        clauses: list[ColumnElement[bool]] = [c.is_deleted == false(), c.is_template == false()]
        if owner_id:
            clauses.append(c.owner_id == _uuid_param("owner_id", owner_id))
        if folder_id:
            clauses.append(c.folder_id == _uuid_param("folder_id", folder_id))
        if title_contains:
            pattern = bindparam("title_pattern", f"%{title_contains}%")
            clauses.append(func.lower(c.title).like(func.lower(pattern)))
        if content_type:
            clauses.append(c.content_type == bindparam("content_type", content_type))
        return clauses

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
        stmt = (
            select(*_documents.c)
            .where(*self._where(owner_id, title_contains, content_type, folder_id))
            .order_by(_order_by(sort, direction))
            .limit(int(limit))
            .offset(int(offset))
        )
        logger.debug("document_filter_query", sort=sort, direction=direction)
        result = await self.db.execute(stmt)
        return [dict(row._mapping) for row in result]
