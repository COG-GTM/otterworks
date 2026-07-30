"""Shared test fixtures."""

import os
import uuid
from collections.abc import AsyncGenerator, Callable

import jwt
import pytest
from httpx import ASGITransport, AsyncClient, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.document import Comment, Document, DocumentVersion, Template  # noqa: F401

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
