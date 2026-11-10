"""OTW-31: folder share link + workspace share policy data model."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from alembic import config as alembic_config
from app.config import Settings
from app.models.share import FolderShareLink, WorkspaceSharePolicy
from app.services.share_audit import (
    SHARE_AUDIT_EVENT_TYPES,
    SHARE_AUDIT_RESOURCE_TYPES,
    ShareAuditPublisher,
    get_share_audit_publisher,
)
from app.services.share_policy_repository import SharePolicyRepository, current_workspace_id

SERVICE_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> alembic_config.Config:
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db_path}")
    cfg = alembic_config.Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.config_file_name = None  # keep the test run's logging config
    return cfg


def _tables(db_path: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_upgrade_creates_tables_and_downgrade_removes_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "migrations.db"
    cfg = _alembic_config(monkeypatch, db_path)

    command.upgrade(cfg, "head")
    assert {"folder_share_links", "workspace_share_policies", "documents"} <= _tables(db_path)

    engine = sa.create_engine(f"sqlite:///{db_path}")
    insp = sa.inspect(engine)
    link_cols = {c["name"]: c for c in insp.get_columns("folder_share_links")}
    assert set(link_cols) == {
        "id", "token_hash", "folder_id", "workspace_id", "created_by",
        "created_at", "expires_at", "revoked_at", "expired_audited_at",
    }
    assert link_cols["expires_at"]["nullable"] is True
    assert link_cols["folder_id"]["nullable"] is False
    assert any(
        ix["column_names"] == ["folder_id"] for ix in insp.get_indexes("folder_share_links")
    )
    assert any(
        uc["column_names"] == ["token_hash"]
        for uc in insp.get_unique_constraints("folder_share_links")
    )
    policy_cols = {c["name"] for c in insp.get_columns("workspace_share_policies")}
    assert policy_cols == {
        "workspace_id", "default_expiry_seconds", "min_expiry_seconds",
        "max_expiry_seconds", "allow_never", "updated_by", "updated_at",
    }
    assert insp.get_pk_constraint("workspace_share_policies")["constrained_columns"] == [
        "workspace_id"
    ]

    # Server defaults on a bare insert match the contract.
    doc_id = uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO workspace_share_policies (workspace_id) VALUES ('w1')"))
        row = conn.execute(
            sa.text(
                "SELECT default_expiry_seconds, min_expiry_seconds, max_expiry_seconds, "
                "allow_never FROM workspace_share_policies"
            )
        ).one()
        conn.execute(
            sa.text(
                "INSERT INTO documents (id, title, owner_id) VALUES (:id, 'keep me', :owner)"
            ),
            {"id": doc_id, "owner": uuid.uuid4().hex},
        )
    assert tuple(row) == (2592000, 3600, 31536000, 0)
    engine.dispose()

    command.downgrade(cfg, "001")
    tables = _tables(db_path)
    assert "folder_share_links" not in tables
    assert "workspace_share_policies" not in tables
    assert "documents" in tables

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        titles = conn.execute(sa.text("SELECT title FROM documents")).scalars().all()
    engine.dispose()
    assert titles == ["keep me"]

    command.upgrade(cfg, "head")
    assert "folder_share_links" in _tables(db_path)
    command.downgrade(cfg, "base")
    assert _tables(db_path) <= {"alembic_version"}


async def test_policy_defaults_when_no_row(db_session: AsyncSession) -> None:
    repo = SharePolicyRepository(db_session)

    assert await repo.get_saved() is None
    policy = await repo.get_effective()

    assert policy.workspace_id == current_workspace_id() == "default"
    assert policy.default_expiry_seconds == 30 * 24 * 3600
    assert policy.min_expiry_seconds == 3600
    assert policy.max_expiry_seconds == 365 * 24 * 3600
    assert policy.allow_never is False
    assert policy.updated_by is None
    # Reading the defaults must not persist a row.
    count = await db_session.scalar(sa.select(sa.func.count()).select_from(WorkspaceSharePolicy))
    assert count == 0


async def test_saved_policy_wins_over_defaults(db_session: AsyncSession) -> None:
    owner = uuid.uuid4()
    db_session.add(
        WorkspaceSharePolicy(
            workspace_id="default",
            default_expiry_seconds=7 * 86400,
            min_expiry_seconds=3600,
            max_expiry_seconds=90 * 86400,
            allow_never=False,
            updated_by=owner,
        )
    )
    await db_session.commit()

    policy = await SharePolicyRepository(db_session).get_effective()
    assert policy.default_expiry_seconds == 7 * 86400
    assert policy.max_expiry_seconds == 90 * 86400
    assert policy.updated_by == owner
    assert policy.updated_at is not None

    other = await SharePolicyRepository(db_session).get_effective("other-workspace")
    assert other.workspace_id == "other-workspace"
    assert other.default_expiry_seconds == 30 * 24 * 3600


def test_workspace_id_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORKSPACE_ID", "acme")
    assert Settings().workspace_id == "acme"
    monkeypatch.delenv("WORKSPACE_ID")
    assert Settings().workspace_id == "default"


async def test_folder_share_link_persists_and_token_hash_is_unique(
    db_session: AsyncSession, folder_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    link = FolderShareLink(
        token_hash="a" * 64, folder_id=folder_id, workspace_id="default", created_by=owner_id
    )
    db_session.add(link)
    await db_session.commit()

    saved = await db_session.get(FolderShareLink, link.id)
    assert saved is not None
    assert saved.created_at is not None
    assert saved.expires_at is None
    assert saved.revoked_at is None
    assert saved.expired_audited_at is None

    db_session.add(
        FolderShareLink(
            token_hash="a" * 64, folder_id=folder_id, workspace_id="default", created_by=owner_id
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


def test_folder_share_link_status() -> None:
    now = datetime.now(UTC)
    link = FolderShareLink(
        token_hash="b" * 64,
        folder_id=uuid.uuid4(),
        workspace_id="default",
        created_by=uuid.uuid4(),
    )
    assert link.status_at(now) == "active"  # NULL expires_at = never
    link.expires_at = now + timedelta(hours=1)
    assert link.status_at(now) == "active"
    link.expires_at = now
    assert link.status_at(now) == "expired"
    link.expires_at = (now - timedelta(seconds=1)).replace(tzinfo=None)  # SQLite returns naive
    assert link.status_at(now) == "expired"
    link.revoked_at = now
    assert link.status_at(now) == "revoked"


async def test_share_audit_publisher_is_a_logging_noop() -> None:
    publisher = get_share_audit_publisher()
    assert isinstance(publisher, ShareAuditPublisher)
    expected_events = {
        "share_link_created", "share_link_updated", "share_link_revoked",
        "share_link_expired", "share_policy_updated",
    }
    assert expected_events == SHARE_AUDIT_EVENT_TYPES
    assert {"share_link", "share_policy"} == SHARE_AUDIT_RESOURCE_TYPES

    with structlog.testing.capture_logs() as logs:
        result = await publisher.emit(
            "share_policy_updated",
            actor_id="u1",
            workspace_id="default",
            resource_type="share_policy",
            resource_id="default",
            old_value={"default_expiry_seconds": 2592000},
            new_value={"default_expiry_seconds": 604800},
        )
    assert result is None
    assert logs == [
        {
            "event": "share_audit_event",
            "log_level": "info",
            "event_type": "share_policy_updated",
            "actor_id": "u1",
            "workspace_id": "default",
            "resource_type": "share_policy",
            "resource_id": "default",
            "old_value": {"default_expiry_seconds": 2592000},
            "new_value": {"default_expiry_seconds": 604800},
        }
    ]
