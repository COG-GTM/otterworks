"""Tests for database session wiring."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session as session_mod


async def test_init_db_creates_the_schema(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(session_mod, "engine", engine)

    await session_mod.init_db()

    async with engine.connect() as conn:
        tables = (
            await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        ).scalars().all()
    await engine.dispose()

    assert "documents" in tables


async def test_get_db_yields_a_session_and_closes_it(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(
        session_mod,
        "async_session",
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )

    generator = session_mod.get_db()
    session = await anext(generator)
    assert isinstance(session, AsyncSession)
    assert (await session.execute(text("SELECT 1"))).scalar_one() == 1

    with pytest.raises(StopAsyncIteration):
        await anext(generator)
    await engine.dispose()

    assert session.sync_session.get_transaction() is None
