"""Database session management."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
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


async def init_db() -> None:
    """Create all tables, and add columns missing from databases created earlier.

    ``create_all`` only creates missing tables, and no migration step runs before
    the service serves traffic, so additive columns are applied here as well.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            await conn.execute(
                text(
                    "ALTER TABLE documents "
                    "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
                )
            )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection for database sessions."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
