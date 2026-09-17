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

#: A column name cannot be bound as a query parameter, so the caller's choice is
#: resolved through an allow-list instead. Unquoted identifiers fold to lower
#: case in PostgreSQL, so the lookup does too.
SORTABLE_COLUMNS = frozenset(COLUMNS)
SORT_DIRECTIONS = frozenset(("asc", "desc"))


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
    ) -> tuple[str, dict[str, Any]]:
        clauses = ["is_deleted = false", "is_template = false"]
        params: dict[str, Any] = {}
        if owner_id:
            clauses.append("owner_id = :owner_id")
            params["owner_id"] = owner_id
        if folder_id:
            clauses.append("folder_id = :folder_id")
            params["folder_id"] = folder_id
        if title_contains:
            # The wildcards belong to the pattern, not to the statement: bound as
            # a bare value the LIKE would become an exact match.
            clauses.append("lower(title) LIKE lower(:title_contains)")
            params["title_contains"] = f"%{title_contains}%"
        if content_type:
            clauses.append("content_type = :content_type")
            params["content_type"] = content_type
        return " AND ".join(clauses), params

    @staticmethod
    def _order_by(sort: str, direction: str) -> str:
        column = sort.lower()
        if column not in SORTABLE_COLUMNS:
            raise ValueError("unsupported sort column")
        order = direction.lower()
        if order not in SORT_DIRECTIONS:
            raise ValueError("unsupported sort direction")
        return f"{column} {order}"

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
        order_by = self._order_by(sort, direction)
        where, params = self._where(owner_id, title_contains, content_type, folder_id)
        sql = (
            f"SELECT {', '.join(COLUMNS)} FROM documents WHERE {where}"
            f" ORDER BY {order_by} LIMIT :limit OFFSET :offset"
        )
        logger.debug("document_filter_query", sort=sort, direction=direction)
        result = await self.db.execute(text(sql), params | {"limit": limit, "offset": offset})
        return [dict(row._mapping) for row in result]
