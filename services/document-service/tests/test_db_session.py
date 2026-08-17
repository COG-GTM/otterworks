"""Tests for the database session helpers."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session as session_mod
from app.db.base import Base
from app.db.session import get_db, init_db
from app.models.document import Document  # noqa: F401  (registers tables on Base)


@pytest.mark.asyncio
async def test_init_db_creates_all_tables(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(session_mod, "engine", engine)

    try:
        await init_db()

        async with engine.begin() as conn:
            tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        assert {"documents", "document_versions", "comments", "templates"} <= set(tables)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_db_yields_a_usable_session_and_closes_it(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(
        session_mod,
        "async_session",
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )

    try:
        generator = get_db()
        session = await anext(generator)
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1

        with pytest.raises(StopAsyncIteration):
            await anext(generator)
        assert session.sync_session.get_bind() is not None
        assert not session.in_transaction()
    finally:
        await engine.dispose()


def test_module_engine_is_configured_from_settings():
    assert session_mod.engine.pool.size() == 10
    assert session_mod.engine.pool._max_overflow == 20
    assert session_mod.settings.db_pool_size == 10
    assert session_mod.settings.db_max_overflow == 20
