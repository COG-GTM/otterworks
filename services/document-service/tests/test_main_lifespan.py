"""Tests for the FastAPI application lifespan."""

import sys
import types

import pytest
from fastapi import FastAPI

import app.main as main

OTEL_MODULE = "opentelemetry.instrumentation.fastapi"


@pytest.fixture
def lifespan_calls(monkeypatch):
    """Record lifespan side effects without touching the real engine."""
    calls: list[str] = []

    async def _init_db():
        calls.append("init_db")

    class _Engine:
        async def dispose(self):
            calls.append("dispose")

    monkeypatch.setattr(main, "init_db", _init_db)
    monkeypatch.setattr(main, "engine", _Engine())
    return calls


def _install_instrumentor(monkeypatch, instrument_app):
    """Register a stub ``FastAPIInstrumentor`` for the lifespan's lazy import."""
    module = types.ModuleType(OTEL_MODULE)
    module.FastAPIInstrumentor = type(
        "FastAPIInstrumentor", (), {"instrument_app": staticmethod(instrument_app)}
    )
    monkeypatch.setitem(sys.modules, OTEL_MODULE, module)


@pytest.mark.asyncio
async def test_lifespan_initialises_db_then_disposes_engine(lifespan_calls, monkeypatch):
    monkeypatch.setattr(main.settings, "otel_enabled", False)

    async with main.lifespan(FastAPI()):
        assert lifespan_calls == ["init_db"]

    assert lifespan_calls == ["init_db", "dispose"]


@pytest.mark.asyncio
async def test_lifespan_instruments_opentelemetry_when_enabled(lifespan_calls, monkeypatch):
    monkeypatch.setattr(main.settings, "otel_enabled", True)
    instrumented: list[FastAPI] = []
    _install_instrumentor(monkeypatch, instrumented.append)
    test_app = FastAPI()

    async with main.lifespan(test_app):
        pass

    assert instrumented == [test_app]
    assert lifespan_calls == ["init_db", "dispose"]


@pytest.mark.asyncio
async def test_lifespan_survives_opentelemetry_setup_failure(lifespan_calls, monkeypatch):
    monkeypatch.setattr(main.settings, "otel_enabled", True)

    def _boom(_app):
        raise RuntimeError("collector unreachable")

    _install_instrumentor(monkeypatch, _boom)

    async with main.lifespan(FastAPI()):
        pass

    assert lifespan_calls == ["init_db", "dispose"]


def test_app_exposes_every_router():
    paths = {route.path for route in main.app.routes}

    assert "/health" in paths
    assert "/metrics" in paths
    assert "/api/v1/documents/" in paths
    assert "/api/v1/documents/{document_id}/comments" in paths
    assert "/api/v1/templates/" in paths
