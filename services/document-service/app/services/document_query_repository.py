"""Metadata filtering for the document list endpoint.

The list endpoint supports ad-hoc metadata filters (title fragment, content
type) and caller-chosen ordering. The repository builds the predicate list for
those filters and reads the ``documents`` table directly.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text
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


SORTABLE_COLUMNS = frozenset(
    {"title", "content_type", "word_count", "version", "created_at", "updated_at"}
)
SORT_DIRECTIONS = frozenset({"asc", "desc"})


class InvalidSortError(ValueError):
    """Raised when the caller asks for an ordering outside the allow-list."""


def resolve_order_by(sort: str, direction: str) -> str:
    """Map a caller-chosen sort to a fixed ``ORDER BY`` fragment from the allow-list."""
    column = sort.strip().lower() if isinstance(sort, str) else ""
    order = direction.strip().lower() if isinstance(direction, str) else ""
    if column not in SORTABLE_COLUMNS:
        raise InvalidSortError("unsupported sort column")
    if order not in SORT_DIRECTIONS:
        raise InvalidSortError("unsupported sort direction")
    return f"{column} {order.upper()}"


def _like_pattern(fragment: str) -> str:
    escaped = fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class DocumentQueryRepository:
    """Reads the document table for the list endpoint's metadata filters.

    Every caller-supplied value is bound as a query parameter; ordering is
    resolved from a fixed allow-list.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    def _where(
        self,
        owner_id: str | None,
        title_contains: str | None,
        content_type: str | None,
        folder_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["is_deleted = false", "is_template = false"]
        params: dict[str, Any] = {}
        if owner_id:
            clauses.append("owner_id = :owner_id")
            params["owner_id"] = str(owner_id)
        if folder_id:
            clauses.append("folder_id = :folder_id")
            params["folder_id"] = str(folder_id)
        if title_contains:
            clauses.append("lower(title) LIKE lower(:title_pattern) ESCAPE '\\'")
            params["title_pattern"] = _like_pattern(title_contains)
        if content_type:
            clauses.append("content_type = :content_type")
            params["content_type"] = content_type
        return " AND ".join(clauses), params

    async def count_documents(
        self,
        *,
        owner_id: str | None = None,
        title_contains: str | None = None,
        content_type: str | None = None,
        folder_id: str | None = None,
    ) -> int:
        """Count documents matching the metadata filters."""
        where, params = self._where(owner_id, title_contains, content_type, folder_id)
        result = await self.db.execute(
            text(f"SELECT count(*) FROM documents WHERE {where}"), params
        )
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
        where, params = self._where(owner_id, title_contains, content_type, folder_id)
        params["limit"] = int(limit)
        params["offset"] = int(offset)
        sql = (
            f"SELECT {', '.join(COLUMNS)} FROM documents WHERE {where}"
            f" ORDER BY {order_by} LIMIT :limit OFFSET :offset"
        )
        logger.debug("document_filter_query", sort=sort, direction=direction)
        result = await self.db.execute(text(sql), params)
        return [dict(row._mapping) for row in result]
