"""Tests for database engine/session wiring."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import session as session_mod
from app.db.base import Base


class _AsyncContext:
    """Minimal async context manager yielding ``value``."""

    def __init__(self, value: object) -> None:
        self.value = value
        self.exited = False

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *_exc: object) -> bool:
        self.exited = True
        return False


@pytest.mark.asyncio
async def test_init_db_creates_the_metadata_tables(monkeypatch):
    conn = MagicMock()
    conn.run_sync = AsyncMock()
    begin = _AsyncContext(conn)
    engine = MagicMock()
    engine.begin.return_value = begin
    monkeypatch.setattr(session_mod, "engine", engine)

    await session_mod.init_db()

    conn.run_sync.assert_awaited_once_with(Base.metadata.create_all)
    assert begin.exited is True


@pytest.mark.asyncio
async def test_get_db_yields_a_session_and_closes_it(monkeypatch):
    db_session = MagicMock()
    db_session.close = AsyncMock()
    monkeypatch.setattr(
        session_mod, "async_session", MagicMock(return_value=_AsyncContext(db_session))
    )

    generator = session_mod.get_db()
    yielded = await anext(generator)
    assert yielded is db_session
    db_session.close.assert_not_awaited()

    await generator.aclose()
    db_session.close.assert_awaited_once()


def test_engine_is_configured_from_settings():
    url = session_mod.engine.url.render_as_string(hide_password=False)
    assert url == session_mod.settings.database_url
