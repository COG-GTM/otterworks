"""Database session management."""

from collections.abc import AsyncGenerator

from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _add_missing_document_columns(conn: Connection) -> None:
    """Add additive columns that ``create_all`` cannot apply to existing tables."""
    columns = {column["name"] for column in inspect(conn).get_columns("documents")}
    if "deleted_at" not in columns:
        conn.exec_driver_sql(
            "ALTER TABLE documents ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE"
        )
        conn.exec_driver_sql(
            "UPDATE documents SET deleted_at = updated_at WHERE is_deleted = true"
        )


async def init_db() -> None:
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_document_columns)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection for database sessions."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
