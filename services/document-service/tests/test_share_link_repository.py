"""Repository layer for share_links and workspace_share_policy (OTW-43)."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.share_link import DEFAULT_SHARE_DAYS, MAX_SHARE_DAYS
from app.services.share_link import ShareLinkService
from app.services.share_link_repository import (
    EffectiveSharePolicy,
    InvalidSharePolicyError,
    ShareLinkRepository,
    WorkspaceSharePolicyRepository,
    generate_share_token,
    validate_share_policy,
)


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


@pytest.fixture
def links(db_session: AsyncSession) -> ShareLinkRepository:
    return ShareLinkRepository(db_session)


@pytest.fixture
def policies(db_session: AsyncSession) -> WorkspaceSharePolicyRepository:
    return WorkspaceSharePolicyRepository(db_session)


async def _create(links: ShareLinkRepository, **overrides):
    values = {
        "resource_id": uuid.uuid4(),
        "workspace_id": "ws-1",
        "created_by": uuid.uuid4(),
        "expires_at": datetime.now(UTC) + timedelta(days=30),
    }
    values.update(overrides)
    return await links.create(**values)


def test_generate_share_token_is_csprng_urlsafe():
    """Tokens come from secrets.token_urlsafe(32): 43 URL-safe chars and never repeat."""
    tokens = {generate_share_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{43}", t) for t in tokens)


async def test_create_and_get_link(links: ShareLinkRepository):
    """When a folder link is created, Then it is stored with a fresh token and no expired_at."""
    resource_id, creator = uuid.uuid4(), uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(days=7)

    link = await _create(
        links, resource_id=resource_id, created_by=creator, expires_at=expires_at
    )

    assert link.id is not None
    assert link.resource_type == "folder"
    assert link.expired_at is None
    assert len(link.token) == 43

    fetched = await links.get(link.id)
    assert fetched is not None
    assert fetched.resource_id == resource_id
    assert fetched.created_by == creator
    assert fetched.workspace_id == "ws-1"
    assert _naive(fetched.expires_at) == _naive(expires_at)
    assert (await links.get_by_token(link.token)).id == link.id


async def test_get_unknown_link_returns_none(links: ShareLinkRepository):
    assert await links.get(uuid.uuid4()) is None
    assert await links.get_by_token("does-not-exist") is None


async def test_list_for_resource_filters_by_creator(links: ShareLinkRepository):
    """When links are listed for a resource, Then only that caller's links are returned."""
    resource_id, alice, bob = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    a1 = await _create(links, resource_id=resource_id, created_by=alice)
    a2 = await _create(links, resource_id=resource_id, created_by=alice)
    await _create(links, resource_id=resource_id, created_by=bob)
    await _create(links, resource_id=uuid.uuid4(), created_by=alice)

    alice_links = await links.list_for_resource(resource_id, created_by=alice)
    assert {link.id for link in alice_links} == {a1.id, a2.id}
    assert len(await links.list_for_resource(resource_id)) == 3


async def test_update_expiry(links: ShareLinkRepository):
    """When the owner changes the expiry, Then expires_at is updated."""
    link = await _create(links)
    new_expiry = datetime.now(UTC) + timedelta(days=60)

    updated = await links.update_expiry(link, new_expiry)

    assert _naive(updated.expires_at) == _naive(new_expiry)
    assert _naive((await links.get(link.id)).expires_at) == _naive(new_expiry)


async def test_mark_expired_is_set_once(links: ShareLinkRepository):
    """When expiry is detected, Then expired_at is set once and never overwritten."""
    link = await _create(links, expires_at=datetime.now(UTC) - timedelta(days=1))
    first = datetime.now(UTC)

    assert await links.mark_expired(link, first) is True
    assert await links.mark_expired(link, first + timedelta(hours=1)) is False
    assert _naive((await links.get(link.id)).expired_at) == _naive(first)


async def test_mark_expired_keeps_first_detection_across_sessions(links: ShareLinkRepository):
    """Given two workers loaded the same link before either marked it, When both detect
    expiry, Then only the first records expired_at and the second reports False."""
    from tests.conftest import TestingSessionLocal

    link = await _create(links, expires_at=datetime.now(UTC) - timedelta(days=1))
    first = datetime.now(UTC)
    async with TestingSessionLocal() as s1, TestingSessionLocal() as s2:
        worker_a, worker_b = ShareLinkRepository(s1), ShareLinkRepository(s2)
        stale_a, stale_b = await worker_a.get(link.id), await worker_b.get(link.id)

        assert await worker_a.mark_expired(stale_a, first) is True
        assert await worker_b.mark_expired(stale_b, first + timedelta(hours=1)) is False
        assert _naive(stale_b.expired_at) == _naive(first)


async def test_new_workspace_policy_defaults_to_30_and_90(policies):
    """Given a new workspace, When its policy is read, Then default is 30 and max is 90."""
    policy = await policies.get("brand-new-workspace")

    assert policy == EffectiveSharePolicy(
        workspace_id="brand-new-workspace", default_days=30, max_days=90
    )
    assert (DEFAULT_SHARE_DAYS, MAX_SHARE_DAYS) == (30, 90)


async def test_upsert_policy_inserts_then_updates(policies):
    """When a workspace owner saves the policy, Then it is stored and later reads return it."""
    owner = uuid.uuid4()

    created = await policies.upsert("ws-1", default_days=14, max_days=60, updated_by=owner)
    assert (created.default_days, created.max_days, created.updated_by) == (14, 60, owner)
    assert created.updated_at is not None

    other = uuid.uuid4()
    updated = await policies.upsert("ws-1", default_days=7, max_days=7, updated_by=other)
    assert (updated.default_days, updated.max_days, updated.updated_by) == (7, 7, other)

    read = await policies.get("ws-1")
    assert (read.default_days, read.max_days, read.updated_by) == (7, 7, other)
    assert await policies.get("ws-2") == EffectiveSharePolicy.builtin("ws-2")


@pytest.mark.parametrize(
    ("default_days", "max_days"), [(0, 90), (31, 30), (30, 91), (91, 91), (-5, -1)]
)
async def test_upsert_policy_rejects_invalid_range(policies, default_days, max_days):
    """When the policy is outside 1 <= default <= max <= 90, Then it is rejected and not saved."""
    with pytest.raises(InvalidSharePolicyError):
        await policies.upsert(
            "ws-1", default_days=default_days, max_days=max_days, updated_by=uuid.uuid4()
        )
    assert await policies.get("ws-1") == EffectiveSharePolicy.builtin("ws-1")


@pytest.mark.parametrize(("default_days", "max_days"), [(1, 1), (1, 90), (90, 90)])
def test_validate_share_policy_accepts_boundaries(default_days, max_days):
    validate_share_policy(default_days, max_days)


def test_existing_document_share_tokens_unchanged():
    """Existing stateless document share tokens keep working unchanged, with no expiry."""
    service = ShareLinkService(salt="otterworks-share")
    doc_id = "00000000-0000-0000-0000-000000000001"
    token = service.mint_token(doc_id)

    assert len(token) == 16
    assert service.verify_token(doc_id, token)
