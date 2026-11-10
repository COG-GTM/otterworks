"""OTW-66 Alembic migration tests for ``folder_share_links``.

Runs revision 002 up and down against SQLite on every run. Set
``DOC_SVC_TEST_POSTGRES_URL`` (an empty scratch database, asyncpg URL) to also run
it against Postgres and check the exact column types of the contract.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from alembic.config import Config
from app.config import settings

SERVICE_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_URL = os.environ.get("DOC_SVC_TEST_POSTGRES_URL")

EXPECTED_COLUMNS = {
    "id": False,
    "folder_id": False,
    "workspace_id": False,
    "token_hash": False,
    "created_by": False,
    "created_at": False,
    "expires_at": False,
    "revoked_at": True,
    "expiry_audited_at": True,
}


def _alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    return config


async def _alembic(action: str, revision: str) -> None:
    # env.py drives its own event loop, so run it off the test loop.
    await asyncio.to_thread(getattr(command, action), _alembic_config(), revision)


def _describe(sync_conn) -> dict:  # noqa: ANN001
    insp = inspect(sync_conn)
    tables = set(insp.get_table_names())
    if "folder_share_links" not in tables:
        return {"tables": tables}
    return {
        "tables": tables,
        "columns": {c["name"]: c for c in insp.get_columns("folder_share_links")},
        "pk": insp.get_pk_constraint("folder_share_links")["constrained_columns"],
        "indexes": insp.get_indexes("folder_share_links"),
        "uniques": insp.get_unique_constraints("folder_share_links"),
    }


@pytest.fixture(params=["sqlite", "postgres"])
def database_url(request, tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    if request.param == "sqlite":
        url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    elif POSTGRES_URL:
        url = POSTGRES_URL
    else:
        pytest.skip("DOC_SVC_TEST_POSTGRES_URL not set")
    monkeypatch.setattr(settings, "database_url", url)
    return url


async def test_002_upgrade_creates_folder_share_links_and_downgrade_drops_it(
    database_url: str,
) -> None:
    engine = create_async_engine(database_url)
    try:
        await _alembic("upgrade", "head")
        async with engine.connect() as conn:
            schema = await conn.run_sync(_describe)
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()

        assert version == "002"
        assert {"documents", "folder_share_links"} <= schema["tables"]
        columns = schema["columns"]
        assert {name: col["nullable"] for name, col in columns.items()} == EXPECTED_COLUMNS
        assert schema["pk"] == ["id"]
        assert "default" in str(columns["workspace_id"]["default"])
        assert columns["token_hash"]["type"].length == 64
        assert any(
            ix["column_names"] == ["folder_id"] and ix["name"] == "ix_folder_share_links_folder_id"
            for ix in schema["indexes"]
        )
        assert any(uq["column_names"] == ["token_hash"] for uq in schema["uniques"])

        if engine.dialect.name == "postgresql":
            types = {name: str(col["type"]) for name, col in columns.items()}
            assert types["id"] == types["folder_id"] == types["created_by"] == "UUID"
            assert types["workspace_id"] == "TEXT"
            assert types["token_hash"] == "VARCHAR(64)"
            for name in ("created_at", "expires_at", "revoked_at", "expiry_audited_at"):
                assert columns[name]["type"].timezone is True, name

        # US1: workspace defaults to "default"; US1: token_hash is unique.
        token_hash = "a" * 64
        insert = text(
            "INSERT INTO folder_share_links (id, folder_id, token_hash, created_by, expires_at) "
            "VALUES (:id, :folder_id, :token_hash, :created_by, :expires_at)"
        )
        row = {
            "folder_id": str(uuid.uuid4()),
            "token_hash": token_hash,
            "created_by": str(uuid.uuid4()),
            "expires_at": datetime.now(UTC) + timedelta(days=30),
        }
        if engine.dialect.name == "sqlite":
            row["folder_id"] = row["folder_id"].replace("-", "")
            row["created_by"] = row["created_by"].replace("-", "")
        async with engine.begin() as conn:
            await conn.execute(insert, {"id": _uuid_param(engine), **row})
            stored = (
                await conn.execute(text("SELECT workspace_id, created_at FROM folder_share_links"))
            ).one()
        assert stored.workspace_id == "default"
        assert stored.created_at is not None

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(insert, {"id": _uuid_param(engine), **row})

        await _alembic("downgrade", "001")
        async with engine.connect() as conn:
            schema = await conn.run_sync(_describe)
            version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        assert version == "001"
        assert "folder_share_links" not in schema["tables"]
        assert "documents" in schema["tables"]

        await _alembic("upgrade", "head")
        async with engine.connect() as conn:
            schema = await conn.run_sync(_describe)
        assert "folder_share_links" in schema["tables"]
    finally:
        await _alembic("downgrade", "base")
        await engine.dispose()


def _uuid_param(engine) -> str:  # noqa: ANN001
    value = uuid.uuid4()
    return value.hex if engine.dialect.name == "sqlite" else str(value)
