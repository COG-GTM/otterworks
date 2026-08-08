"""Tests for the health endpoint's database failure branch."""

from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from app.db.session import get_db
from app.main import app


async def test_health_reports_degraded_when_the_database_is_unreachable():
    broken_session = AsyncMock()
    broken_session.execute.side_effect = OSError("connection refused")

    async def _override_get_db():
        yield broken_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "degraded",
        "service": "document-service",
        "checks": {"database": "disconnected"},
    }
