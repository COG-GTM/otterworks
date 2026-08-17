"""Tests for the FastAPI application wiring and lifespan."""

import sys
import types

import pytest
from fastapi import FastAPI

import app.main as main_mod
from app.main import app, lifespan

OTEL_MODULE = "opentelemetry.instrumentation.fastapi"


def _fake_otel_module(instrument_app) -> types.ModuleType:
    module = types.ModuleType(OTEL_MODULE)
    module.FastAPIInstrumentor = type(
        "FastAPIInstrumentor", (), {"instrument_app": staticmethod(instrument_app)}
    )
    return module


@pytest.mark.asyncio
async def test_lifespan_initialises_db_and_disposes_engine(monkeypatch):
    events = []

    async def _fake_init_db():
        events.append("init_db")

    class _FakeEngine:
        async def dispose(self):
            events.append("dispose")

    monkeypatch.setattr(main_mod, "init_db", _fake_init_db)
    monkeypatch.setattr(main_mod, "engine", _FakeEngine())
    monkeypatch.setattr(main_mod.settings, "otel_enabled", False)

    async with lifespan(FastAPI()):
        assert events == ["init_db"]

    assert events == ["init_db", "dispose"]


@pytest.mark.asyncio
async def test_lifespan_instruments_opentelemetry_when_enabled(monkeypatch):
    async def _fake_init_db():
        return None

    class _FakeEngine:
        async def dispose(self):
            return None

    instrumented = []
    monkeypatch.setattr(main_mod, "init_db", _fake_init_db)
    monkeypatch.setattr(main_mod, "engine", _FakeEngine())
    monkeypatch.setattr(main_mod.settings, "otel_enabled", True)
    monkeypatch.setitem(
        sys.modules,
        OTEL_MODULE,
        _fake_otel_module(lambda target, **kwargs: instrumented.append(target)),
    )

    target_app = FastAPI()
    async with lifespan(target_app):
        pass

    assert instrumented == [target_app]


@pytest.mark.asyncio
async def test_lifespan_survives_opentelemetry_failure(monkeypatch):
    async def _fake_init_db():
        return None

    disposed = []

    class _FakeEngine:
        async def dispose(self):
            disposed.append(True)

    def _boom(target, **kwargs):
        raise RuntimeError("otel exporter unreachable")

    monkeypatch.setattr(main_mod, "init_db", _fake_init_db)
    monkeypatch.setattr(main_mod, "engine", _FakeEngine())
    monkeypatch.setattr(main_mod.settings, "otel_enabled", True)
    monkeypatch.setitem(sys.modules, OTEL_MODULE, _fake_otel_module(_boom))

    async with lifespan(FastAPI()):
        pass

    assert disposed == [True]


def test_app_exposes_documents_comments_templates_and_health_routes():
    paths = {route.path for route in app.routes}

    assert {
        "/health",
        "/metrics",
        "/api/v1/documents/",
        "/api/v1/documents/{document_id}",
        "/api/v1/documents/{document_id}/comments",
        "/api/v1/templates/",
    } <= paths


def test_cors_middleware_uses_configured_origins():
    origins = [
        m.kwargs.get("allow_origins")
        for m in app.user_middleware
        if "allow_origins" in m.kwargs
    ]

    assert origins == [main_mod.settings.cors_origins]
