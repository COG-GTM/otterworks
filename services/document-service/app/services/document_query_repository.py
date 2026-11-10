"""Metadata filtering for the document list endpoint.

The list endpoint supports ad-hoc metadata filters (title fragment, content
type) and caller-chosen ordering. The repository builds the predicate list for
those filters and reads the ``documents`` table directly. Every caller-supplied
value is a bound parameter; ORDER BY is resolved from an allow-list.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import String, Uuid, bindparam, text
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

# UUID columns are native ``uuid`` on PostgreSQL; SQLite stores them as text.
_UUID_PARAM = Uuid(as_uuid=False).with_variant(String(), "sqlite")


class InvalidSortError(ValueError):
    """The caller asked for an ORDER BY column or direction outside the allow-list."""


def resolve_order_by(sort: str, direction: str) -> str:
    """Map caller-chosen ordering onto a fixed column name and direction."""
    if sort not in SORTABLE_COLUMNS:
        raise InvalidSortError("unsupported sort column")
    normalized = direction.lower() if isinstance(direction, str) else direction
    if normalized not in SORT_DIRECTIONS:
        raise InvalidSortError("unsupported sort direction")
    return f"{sort} {normalized}"


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
    ) -> tuple[str, dict[str, Any], list]:
        clauses = ["is_deleted = false", "is_template = false"]
        params: dict[str, Any] = {}
        binds = []
        if owner_id:
            clauses.append("owner_id = :owner_id")
            params["owner_id"] = owner_id
            binds.append(bindparam("owner_id", type_=_UUID_PARAM))
        if folder_id:
            clauses.append("folder_id = :folder_id")
            params["folder_id"] = folder_id
            binds.append(bindparam("folder_id", type_=_UUID_PARAM))
        if title_contains:
            clauses.append("lower(title) LIKE lower(:title_pattern)")
            params["title_pattern"] = f"%{title_contains}%"
        if content_type:
            clauses.append("content_type = :content_type")
            params["content_type"] = content_type
        return " AND ".join(clauses), params, binds

    async def count_documents(
        self,
        *,
        owner_id: str | None = None,
        title_contains: str | None = None,
        content_type: str | None = None,
        folder_id: str | None = None,
    ) -> int:
        """Count documents matching the metadata filters."""
        where, params, binds = self._where(
            owner_id, title_contains, content_type, folder_id
        )
        stmt = text("SELECT count(*) FROM documents WHERE " + where).bindparams(*binds)
        result = await self.db.execute(stmt, params)
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
        where, params, binds = self._where(
            owner_id, title_contains, content_type, folder_id
        )
        params["limit"] = int(limit)
        params["offset"] = int(offset)
        stmt = text(
            f"SELECT {', '.join(COLUMNS)} FROM documents WHERE {where}"
            f" ORDER BY {order_by} LIMIT :limit OFFSET :offset"
        ).bindparams(*binds)
        logger.debug("document_filter_query", sort=sort, direction=direction)
        result = await self.db.execute(stmt, params)
        return [dict(row._mapping) for row in result]
