"""App lifespan, DB session helpers, health degraded path and chaos latency hook."""

import sys
import types

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import main
from app.api import documents
from app.db import session as db_session_mod
from app.db.session import get_db


class _FakeEngine:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True


async def _run_lifespan(monkeypatch, app: FastAPI) -> _FakeEngine:
    calls = []

    async def _init_db():
        calls.append("init_db")

    engine = _FakeEngine()
    monkeypatch.setattr(main, "init_db", _init_db)
    monkeypatch.setattr(main, "engine", engine)
    async with main.lifespan(app):
        assert calls == ["init_db"]
        assert not engine.disposed
    return engine


@pytest.mark.asyncio
async def test_lifespan_without_otel(monkeypatch):
    monkeypatch.setattr(main.settings, "otel_enabled", False)
    engine = await _run_lifespan(monkeypatch, FastAPI())
    assert engine.disposed


def _fake_instrumentor(monkeypatch, instrument_app) -> None:
    module = types.ModuleType("opentelemetry.instrumentation.fastapi")
    module.FastAPIInstrumentor = type(
        "FastAPIInstrumentor", (), {"instrument_app": staticmethod(instrument_app)}
    )
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.fastapi", module)


@pytest.mark.asyncio
async def test_lifespan_instruments_app_when_otel_enabled(monkeypatch):
    instrumented = []
    monkeypatch.setattr(main.settings, "otel_enabled", True)
    _fake_instrumentor(monkeypatch, instrumented.append)
    target = FastAPI()
    engine = await _run_lifespan(monkeypatch, target)
    assert instrumented == [target]
    assert engine.disposed


@pytest.mark.asyncio
async def test_lifespan_survives_otel_failure(monkeypatch):
    def _boom(_app):
        raise RuntimeError("otel broken")

    monkeypatch.setattr(main.settings, "otel_enabled", True)
    _fake_instrumentor(monkeypatch, _boom)
    engine = await _run_lifespan(monkeypatch, FastAPI())
    assert engine.disposed


@pytest.mark.asyncio
async def test_init_db_and_get_db_use_module_engine(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(db_session_mod, "engine", engine)
    monkeypatch.setattr(
        db_session_mod,
        "async_session",
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )
    await db_session_mod.init_db()

    gen = db_session_mod.get_db()
    session = await gen.__anext__()
    tables = (
        await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    ).scalars().all()
    assert {"documents", "document_versions", "comments", "templates"} <= set(tables)
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    await engine.dispose()


@pytest.mark.asyncio
async def test_health_degraded_when_db_unreachable():
    class _BrokenSession:
        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("db down")

    async def _broken_db():
        yield _BrokenSession()

    main.app.dependency_overrides[get_db] = _broken_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/health")
    finally:
        main.app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "degraded",
        "service": "document-service",
        "checks": {"database": "disconnected"},
    }


class _FakeRedis:
    def __init__(self, keys=(), fail=False):
        self.keys = set(keys)
        self.fail = fail

    def exists(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return int(key in self.keys)


@pytest.mark.asyncio
async def test_latency_injected_when_chaos_flag_set(monkeypatch):
    sleeps = []

    async def _sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(
        documents,
        "_get_redis",
        lambda: _FakeRedis(keys={"chaos:document-service:slow_queries"}),
    )
    monkeypatch.setattr(documents.asyncio, "sleep", _sleep)
    await documents._maybe_inject_latency()
    assert len(sleeps) == 1
    assert 3.0 <= sleeps[0] <= 5.0


@pytest.mark.asyncio
async def test_no_latency_when_flag_absent_or_redis_down(monkeypatch):
    sleeps = []

    async def _sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(documents.asyncio, "sleep", _sleep)
    for fake in (_FakeRedis(), _FakeRedis(fail=True)):
        monkeypatch.setattr(documents, "_get_redis", lambda fake=fake: fake)
        await documents._maybe_inject_latency()
    assert sleeps == []


def test_get_redis_is_lazy_singleton(monkeypatch):
    monkeypatch.setattr(documents, "_redis_client", None)
    monkeypatch.setenv("REDIS_HOST", "redis.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")
    client = documents._get_redis()
    assert documents._get_redis() is client
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["host"] == "redis.internal"
    assert kwargs["port"] == 6380
