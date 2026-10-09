"""Metadata filtering for the document list endpoint.

The list endpoint supports ad-hoc metadata filters (title fragment, content
type) and caller-chosen ordering. The repository builds the predicate list for
those filters and reads the ``documents`` table directly.

Every caller-supplied value is sent as a bound parameter, and ``ORDER BY`` is
resolved from a fixed allow-list of columns and directions.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import ColumnElement, Select, bindparam, column, false, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import NullType

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

SORTABLE_COLUMNS = frozenset(
    {"title", "content_type", "word_count", "version", "created_at", "updated_at"}
)
SORT_DIRECTIONS = frozenset({"asc", "desc"})

LIKE_ESCAPE = "!"

# Untyped columns keep rows exactly as the driver returns them.
_documents = table("documents", *(column(name) for name in COLUMNS))


class InvalidSortError(ValueError):
    """Raised when ``sort`` or ``direction`` is not in the allow-list."""


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so a title fragment only ever matches literally."""
    return (
        value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def resolve_order_by(sort: str, direction: str) -> ColumnElement[Any]:
    """Map caller-chosen ordering onto an allow-listed column and direction."""
    if sort not in SORTABLE_COLUMNS:
        raise InvalidSortError(
            f"sort must be one of: {', '.join(sorted(SORTABLE_COLUMNS))}"
        )
    normalized = direction.lower() if isinstance(direction, str) else direction
    if normalized not in SORT_DIRECTIONS:
        raise InvalidSortError("direction must be one of: asc, desc")
    col = _documents.c[sort]
    return col.asc() if normalized == "asc" else col.desc()


def _uuid_param(name: str, value: str) -> ColumnElement[Any]:
    # Untyped so the driver infers ``uuid`` from the column it is compared to.
    return bindparam(name, value, type_=NullType())


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
            clauses.append(c.owner_id == _uuid_param("owner_id", str(owner_id)))
        if folder_id:
            clauses.append(c.folder_id == _uuid_param("folder_id", str(folder_id)))
        if title_contains:
            pattern = bindparam("title_pattern", f"%{escape_like(title_contains)}%")
            clauses.append(
                func.lower(c.title).like(func.lower(pattern), escape=LIKE_ESCAPE)
            )
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
        order_by = resolve_order_by(sort, direction)
        stmt: Select[Any] = (
            select(*_documents.c)
            .where(*self._where(owner_id, title_contains, content_type, folder_id))
            .order_by(order_by)
            .limit(int(limit))
            .offset(int(offset))
        )
        logger.debug("document_filter_query", sort=sort, direction=direction)
        result = await self.db.execute(stmt)
        return [dict(row._mapping) for row in result]
