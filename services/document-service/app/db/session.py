"""Database session management."""

from collections.abc import AsyncGenerator
from functools import cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.db.base import Base


@cache
def get_engine() -> AsyncEngine:
    """Create the engine on first use so importing the app never needs credentials."""
    return create_async_engine(
        settings.require_database_url(),
        echo=False,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


@cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()


async def init_db() -> None:
    """Create all tables."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection for database sessions."""
    async with get_session_factory()() as session:
        try:
            yield session
        finally:
            await session.close()
