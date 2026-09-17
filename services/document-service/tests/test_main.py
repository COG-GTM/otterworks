"""Tests for application startup/shutdown wiring."""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app import main as main_mod


@pytest.fixture
def lifespan_stubs(monkeypatch) -> tuple[AsyncMock, AsyncMock]:
    init_db = AsyncMock()
    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(main_mod, "init_db", init_db)
    monkeypatch.setattr(main_mod, "engine", engine)
    return init_db, engine.dispose


@pytest.mark.asyncio
async def test_lifespan_initialises_the_database_and_disposes_the_engine(
    monkeypatch, lifespan_stubs
):
    init_db, dispose = lifespan_stubs
    monkeypatch.setattr(main_mod.settings, "otel_enabled", False)

    async with main_mod.lifespan(FastAPI()):
        init_db.assert_awaited_once()
        dispose.assert_not_awaited()

    dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_instruments_the_app_when_otel_is_enabled(monkeypatch, lifespan_stubs):
    monkeypatch.setattr(main_mod.settings, "otel_enabled", True)
    instrumentor = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "opentelemetry.instrumentation.fastapi",
        MagicMock(FastAPIInstrumentor=instrumentor),
    )
    app = FastAPI()

    async with main_mod.lifespan(app):
        instrumentor.instrument_app.assert_called_once_with(app)


@pytest.mark.asyncio
async def test_lifespan_survives_a_broken_otel_setup(monkeypatch, lifespan_stubs):
    init_db, dispose = lifespan_stubs
    monkeypatch.setattr(main_mod.settings, "otel_enabled", True)
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.fastapi", None)

    async with main_mod.lifespan(FastAPI()):
        init_db.assert_awaited_once()

    dispose.assert_awaited_once()


def test_app_exposes_the_documented_routes():
    paths = {route.path for route in main_mod.app.routes}

    assert {
        "/health",
        "/metrics",
        "/api/v1/documents/",
        "/api/v1/documents/{document_id}",
        "/api/v1/documents/{document_id}/comments",
        "/api/v1/templates/",
    } <= paths
