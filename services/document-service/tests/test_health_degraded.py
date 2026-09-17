"""Health endpoint behaviour when the database is unreachable."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_db
from app.main import app


class _UnreachableSession:
    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("connection refused")


@pytest.mark.asyncio
async def test_health_reports_degraded_when_the_database_is_down():
    async def _override_get_db():
        yield _UnreachableSession()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "degraded",
        "service": "document-service",
        "checks": {"database": "disconnected"},
    }
