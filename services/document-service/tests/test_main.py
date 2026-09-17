"""Tests for the FastAPI application lifespan and wiring."""

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

import app.main as main_mod


@pytest.fixture
def stub_engine(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(main_mod, "engine", engine)
    monkeypatch.setattr(main_mod, "init_db", AsyncMock())
    return engine


async def test_lifespan_initialises_the_database_and_disposes_the_engine(
    monkeypatch, stub_engine
):
    monkeypatch.setattr(main_mod.settings, "otel_enabled", False)

    async with main_mod.lifespan(FastAPI()):
        main_mod.init_db.assert_awaited_once()
        stub_engine.dispose.assert_not_awaited()

    stub_engine.dispose.assert_awaited_once()


async def test_lifespan_instruments_opentelemetry_when_enabled(monkeypatch, stub_engine):
    monkeypatch.setattr(main_mod.settings, "otel_enabled", True)
    instrumentor = MagicMock()
    fake_module = types.ModuleType("opentelemetry.instrumentation.fastapi")
    fake_module.FastAPIInstrumentor = instrumentor
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.fastapi", fake_module)
    instrumented_app = FastAPI()

    async with main_mod.lifespan(instrumented_app):
        pass

    instrumentor.instrument_app.assert_called_once_with(instrumented_app)


async def test_lifespan_survives_a_failing_opentelemetry_setup(monkeypatch, stub_engine):
    monkeypatch.setattr(main_mod.settings, "otel_enabled", True)
    broken = types.ModuleType("opentelemetry.instrumentation.fastapi")
    broken.FastAPIInstrumentor = MagicMock(
        instrument_app=MagicMock(side_effect=RuntimeError("no collector"))
    )
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.fastapi", broken)

    async with main_mod.lifespan(FastAPI()):
        pass

    stub_engine.dispose.assert_awaited_once()


def test_routers_are_mounted_under_their_prefixes():
    paths = {route.path for route in main_mod.app.routes}

    assert {"/health", "/metrics", "/api/v1/documents/", "/api/v1/templates/"} <= paths
    assert "/api/v1/documents/{document_id}/comments" in paths
