"""Database session management."""

from collections.abc import AsyncGenerator

from sqlalchemy import Connection, DateTime, inspect, text
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


def _sync_document_columns(conn: Connection) -> None:
    """Add columns introduced after the initial schema to an existing documents table."""
    inspector = inspect(conn)
    if "documents" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "deleted_at" not in columns:
        column_type = DateTime(timezone=True).compile(dialect=conn.dialect)
        conn.execute(text(f"ALTER TABLE documents ADD COLUMN deleted_at {column_type}"))
        conn.execute(
            text("UPDATE documents SET deleted_at = updated_at WHERE is_deleted = true")
        )


async def init_db() -> None:
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sync_document_columns)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection for database sessions."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
