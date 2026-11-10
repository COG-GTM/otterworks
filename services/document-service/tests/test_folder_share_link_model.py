"""OTW-66 FolderShareLink model and schema tests (scenarios from OTW-63)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.folder_share_link import (
    DEFAULT_WORKSPACE_ID,
    FolderShareLink,
    FolderShareLinkStatus,
)
from app.schemas.folder_share_link import (
    POLICY_DEFAULT_EXPIRY_DAYS,
    FolderShareLinkCreate,
    FolderShareLinkCreated,
    FolderShareLinkGone,
    FolderShareLinkResponse,
    FolderShareLinkUpdate,
)
from app.services.folder_share_token import hash_token, new_token
from app.services.share_link import ShareLinkService

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def share_link_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARE_LINK_SECRET", "test-share-link-secret")


def _link(folder_id: uuid.UUID, owner_id: uuid.UUID, **overrides) -> FolderShareLink:
    fields = {
        "folder_id": folder_id,
        "token_hash": new_token()[1],
        "created_by": owner_id,
        "expires_at": NOW + timedelta(days=POLICY_DEFAULT_EXPIRY_DAYS),
    }
    fields.update(overrides)
    return FolderShareLink(**fields)


# US1 / Given I own folder F, When I create a share link without picking an expiry,
# Then a link record is saved with token, folder_id, workspace, created_by,
# created_at and expires_at = created_at + workspace default (30 days).
async def test_us1_create_saves_full_link_record(
    db_session: AsyncSession, folder_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    token, token_hash = new_token()
    link = FolderShareLink(
        folder_id=folder_id,
        token_hash=token_hash,
        created_by=owner_id,
        created_at=NOW,
        expires_at=NOW + timedelta(days=POLICY_DEFAULT_EXPIRY_DAYS),
    )
    db_session.add(link)
    await db_session.commit()
    db_session.expunge_all()

    saved = (await db_session.execute(select(FolderShareLink))).scalar_one()
    assert isinstance(saved.id, uuid.UUID)
    assert saved.folder_id == folder_id
    assert saved.workspace_id == DEFAULT_WORKSPACE_ID == "default"
    assert saved.token_hash == hash_token(token)
    assert saved.created_by == owner_id
    assert saved.created_at.replace(tzinfo=UTC) == NOW
    assert saved.expires_at.replace(tzinfo=UTC) - saved.created_at.replace(tzinfo=UTC) == (
        timedelta(days=30)
    )
    assert saved.revoked_at is None
    assert saved.expiry_audited_at is None


async def test_us1_created_at_defaults_to_now(
    db_session: AsyncSession, folder_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    before = datetime.now(UTC)
    link = _link(folder_id, owner_id)
    db_session.add(link)
    await db_session.commit()

    assert before <= link.created_at.replace(tzinfo=UTC) <= datetime.now(UTC)


# US1 / Then only a keyed hash of the token is stored
async def test_us1_raw_token_is_never_stored(
    db_session: AsyncSession, folder_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    token, token_hash = new_token()
    db_session.add(_link(folder_id, owner_id, token_hash=token_hash))
    await db_session.commit()

    assert "token" not in FolderShareLink.__table__.columns
    row = (await db_session.execute(select(FolderShareLink.__table__))).one()
    assert token not in [str(value) for value in row]


async def test_us1_token_hash_is_unique(
    db_session: AsyncSession, folder_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    token_hash = new_token()[1]
    db_session.add(_link(folder_id, owner_id, token_hash=token_hash))
    await db_session.commit()

    db_session.add(_link(uuid.uuid4(), owner_id, token_hash=token_hash))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_us1_links_are_listed_by_folder(
    db_session: AsyncSession, folder_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    db_session.add_all(
        [_link(folder_id, owner_id), _link(folder_id, owner_id), _link(uuid.uuid4(), owner_id)]
    )
    await db_session.commit()

    rows = (
        await db_session.execute(
            select(FolderShareLink).where(FolderShareLink.folder_id == folder_id)
        )
    ).scalars()
    assert len(list(rows)) == 2
    assert any(ix.columns.keys() == ["folder_id"] for ix in FolderShareLink.__table__.indexes)


# US3 / Given I revoke a link, Then it stops working at once and its record is kept
async def test_us3_revoked_link_keeps_its_record(
    db_session: AsyncSession, folder_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    link = _link(folder_id, owner_id, expires_at=datetime.now(UTC) + timedelta(days=5))
    db_session.add(link)
    await db_session.commit()
    assert link.status is FolderShareLinkStatus.ACTIVE

    link.revoked_at = datetime.now(UTC)
    await db_session.commit()
    db_session.expunge_all()

    kept = (await db_session.execute(select(FolderShareLink))).scalar_one()
    assert kept.id == link.id
    assert kept.revoked_at is not None
    assert kept.status is FolderShareLinkStatus.REVOKED


# US4 / Given a link's expires_at is in the past, Then it is expired (API returns 410)
def test_us4_status_reflects_expiry_and_revocation() -> None:
    folder_id, owner_id = uuid.uuid4(), uuid.uuid4()
    active = _link(folder_id, owner_id, expires_at=NOW + timedelta(seconds=1))
    expired = _link(folder_id, owner_id, expires_at=NOW - timedelta(seconds=1))
    at_boundary = _link(folder_id, owner_id, expires_at=NOW)
    revoked = _link(folder_id, owner_id, revoked_at=NOW - timedelta(days=1))
    revoked_and_expired = _link(
        folder_id, owner_id, expires_at=NOW - timedelta(days=1), revoked_at=NOW
    )

    assert active.status_at(NOW) is FolderShareLinkStatus.ACTIVE
    assert expired.status_at(NOW) is FolderShareLinkStatus.EXPIRED
    assert at_boundary.status_at(NOW) is FolderShareLinkStatus.EXPIRED
    assert revoked.status_at(NOW) is FolderShareLinkStatus.REVOKED
    assert revoked_and_expired.status_at(NOW) is FolderShareLinkStatus.REVOKED
    assert revoked.status_at(NOW - timedelta(days=2)) is FolderShareLinkStatus.ACTIVE


def test_us4_status_treats_naive_timestamps_as_utc() -> None:
    link = _link(uuid.uuid4(), uuid.uuid4(), expires_at=NOW.replace(tzinfo=None))
    assert link.status_at(NOW - timedelta(minutes=1)) is FolderShareLinkStatus.ACTIVE
    assert link.status_at((NOW + timedelta(minutes=1)).replace(tzinfo=None)) is (
        FolderShareLinkStatus.EXPIRED
    )


def test_us4_gone_detail_values() -> None:
    assert FolderShareLinkGone(detail="link_expired").detail == "link_expired"
    assert FolderShareLinkGone(detail="link_revoked").detail == "link_revoked"
    with pytest.raises(ValidationError):
        FolderShareLinkGone(detail="gone")


# US1 / When I create a share link without picking an expiry -> workspace default applies
def test_us1_create_schema_expiry_is_optional() -> None:
    body = FolderShareLinkCreate(folder_id=uuid.uuid4())
    assert body.expires_in_days is None
    assert POLICY_DEFAULT_EXPIRY_DAYS == 30


# US3 / When I choose an expiry between 1 and 90 days, Then it is accepted
@pytest.mark.parametrize("days", [1, 30, 90])
def test_us3_expiry_within_bounds_is_accepted(days: int) -> None:
    assert FolderShareLinkCreate(folder_id=uuid.uuid4(), expires_in_days=days).expires_in_days == (
        days
    )
    assert FolderShareLinkUpdate(expires_in_days=days).expires_in_days == days


# US3 / Given I choose a value outside the bounds, or "never", Then it is rejected (422)
@pytest.mark.parametrize("days", [0, -1, 91, 365, "never", None])
def test_us3_expiry_outside_bounds_or_never_is_rejected(days: object) -> None:
    with pytest.raises(ValidationError):
        FolderShareLinkUpdate(expires_in_days=days)
    if days is not None:
        with pytest.raises(ValidationError):
            FolderShareLinkCreate(folder_id=uuid.uuid4(), expires_in_days=days)


# US1 / the raw token is returned once: only the create payload carries it
def test_us1_only_create_response_carries_token() -> None:
    link = _link(uuid.uuid4(), uuid.uuid4(), id=uuid.uuid4(), created_at=NOW)

    listed = FolderShareLinkResponse.model_validate(link).model_dump()
    assert "token" not in listed
    assert "token_hash" not in listed
    assert listed["status"] == link.status.value
    assert set(listed) == {
        "id", "folder_id", "created_by", "created_at", "expires_at", "revoked_at", "status"
    }

    created = FolderShareLinkCreated(
        id=link.id, folder_id=link.folder_id, token="raw", expires_at=link.expires_at,
        created_at=link.created_at,
    )
    assert set(created.model_dump()) == {"id", "folder_id", "token", "expires_at", "created_at"}


# Existing links: Given a document share link created before release, Then it keeps
# working exactly as today, with no expiry.
async def test_existing_document_share_links_are_unchanged(db_session: AsyncSession) -> None:
    service = ShareLinkService(salt="otterworks-share")
    document_id = str(uuid.uuid4())

    token = service.mint_token(document_id)

    assert service.verify_token(document_id, token)
    assert (await db_session.execute(select(FolderShareLink))).first() is None
