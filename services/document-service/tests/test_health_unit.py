"""Unit tests for the health/metrics handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import health as health_mod


@pytest.mark.asyncio
async def test_health_reports_healthy_when_the_database_answers():
    db = MagicMock()
    db.execute = AsyncMock()

    result = await health_mod.health(db)

    assert result == {
        "status": "healthy",
        "service": "document-service",
        "checks": {"database": "connected"},
    }
    assert str(db.execute.await_args.args[0]) == "SELECT 1"


@pytest.mark.asyncio
async def test_health_reports_degraded_when_the_database_is_unreachable():
    db = MagicMock()
    db.execute = AsyncMock(side_effect=OSError("connection refused"))

    result = await health_mod.health(db)

    assert result == {
        "status": "degraded",
        "service": "document-service",
        "checks": {"database": "disconnected"},
    }


@pytest.mark.asyncio
async def test_metrics_exposes_the_up_gauge():
    body = await health_mod.metrics()

    assert "# TYPE document_service_up gauge" in body
    assert body.endswith("document_service_up 1\n")
