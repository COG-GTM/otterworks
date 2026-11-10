"""Shared test fixtures."""

import json
import os
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.document import Comment, Document, DocumentVersion, Template  # noqa: F401
from app.services.audit_client import AuditClient, set_audit_client

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# app.api.documents._get_jwt_secret() reads this at request time. Set it here, before any
# test module is imported, so token signing does not depend on collection order.
TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests-pad32"  # noqa: S105
os.environ.setdefault("JWT_SECRET", TEST_JWT_SECRET)

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session


def bearer_auth(user_id: uuid.UUID) -> Callable[[Request], Request]:
    """httpx auth flow signing every request as ``user_id``.

    A request that sets its own ``Authorization`` header keeps it; one passing
    ``auth=None`` is sent unauthenticated.
    """
    token = jwt.encode({"user_id": str(user_id)}, TEST_JWT_SECRET, algorithm="HS256")

    def _apply(request: Request) -> Request:
        request.headers.setdefault("Authorization", f"Bearer {token}")
        return request

    return _apply


@pytest.fixture
async def client(
    db_session: AsyncSession, owner_id: uuid.UUID
) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", auth=bearer_auth(owner_id)
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def owner_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def folder_id() -> uuid.UUID:
    return uuid.uuid4()


AUDIT_TEST_URL = "http://audit-service:8090"
AUDIT_TEST_TOKEN = "test-audit-ingest-token"  # noqa: S105

# Request headers the api-gateway forwards; the audit context reads them once per request.
CLIENT_IP = "203.0.113.7"
REQUEST_ID = "req-lbg6-0001"
GATEWAY_HEADERS = {
    "X-Forwarded-For": f"{CLIENT_IP}, 10.0.0.5",
    "X-Request-ID": REQUEST_ID,
    "User-Agent": "pytest-audit/1.0",
}


@pytest.fixture(autouse=True)
def _audit_disabled_by_default(monkeypatch):
    """Keep tests that don't ask for an audit sink from emitting anywhere."""
    monkeypatch.delenv("AUDIT_SERVICE_URL", raising=False)
    monkeypatch.delenv("AUDIT_SERVICE_TOKEN", raising=False)


@dataclass
class AuditSink:
    """A stubbed audit-service: records what the client POSTs and replies with ``respond``."""

    requests: list[httpx.Request] = field(default_factory=list)
    respond: Callable[[httpx.Request], httpx.Response] | None = None
    client: AuditClient | None = None

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.respond is not None:
            return self.respond(request)
        return httpx.Response(201, json={"id": str(uuid.uuid4())})

    async def events(self) -> list[dict]:
        await self.client.drain()
        return [json.loads(r.content) for r in self.requests]

    def assert_request(
        self, event: dict, *, user_id: str, outcome: str, ip: str, request_id: str
    ) -> None:
        """Who / when / from where, and the headers the contract requires."""
        assert event["userId"] == user_id
        assert event["actorType"] == ("anonymous" if user_id == "anonymous" else "user")
        assert event["outcome"] == outcome
        assert event["ipAddress"] == ip
        assert event["requestId"] == request_id
        assert event["serviceName"] == "document-service"
        assert event["timestamp"].endswith("Z")
        assert all(isinstance(v, str) for v in event["details"].values())
        sent = next(r for r in self.requests if json.loads(r.content) == event)
        assert str(sent.url) == f"{AUDIT_TEST_URL}/api/v1/audit/events"
        assert sent.headers["X-Audit-Token"] == AUDIT_TEST_TOKEN
        assert sent.headers["X-Request-ID"] == request_id
        assert sent.headers["Content-Type"] == "application/json"

    async def only(self, action: str) -> dict:
        matching = [e for e in await self.events() if e["action"] == action]
        assert len(matching) == 1, f"expected one {action} event, got {matching}"
        return matching[0]


@pytest.fixture
async def audit_sink(monkeypatch) -> AsyncGenerator[AuditSink, None]:
    monkeypatch.setenv("AUDIT_SERVICE_URL", AUDIT_TEST_URL)
    monkeypatch.setenv("AUDIT_SERVICE_TOKEN", AUDIT_TEST_TOKEN)
    sink = AuditSink()
    sink.client = AuditClient(transport=httpx.MockTransport(sink._handle))
    previous = set_audit_client(sink.client)
    yield sink
    await sink.client.aclose()
    set_audit_client(previous)
