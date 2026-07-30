"""Tests for database session wiring."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session as session_mod


@pytest.fixture
async def sqlite_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_creates_every_table(monkeypatch, sqlite_engine):
    monkeypatch.setattr(session_mod, "engine", sqlite_engine)

    await session_mod.init_db()

    async with sqlite_engine.connect() as conn:
        tables = await conn.run_sync(lambda sync: inspect(sync).get_table_names())
    assert {"documents", "document_versions", "comments", "templates"} <= set(tables)


@pytest.mark.asyncio
async def test_get_db_yields_a_usable_session_and_closes_it(monkeypatch, sqlite_engine):
    monkeypatch.setattr(
        session_mod,
        "async_session",
        async_sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False),
    )

    generator = session_mod.get_db()
    session = await anext(generator)
    assert isinstance(session, AsyncSession)
    assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    assert session.in_transaction()

    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    assert not session.in_transaction()
