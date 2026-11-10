"""Alembic migration 002: share_links and workspace_share_policy (OTW-43).

Runs the real migrations in a subprocess against a throwaway SQLite file. Set
MIGRATION_TEST_DATABASE_URL to an empty PostgreSQL database
(postgresql+asyncpg://...) to run the same checks against Postgres too.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

SERVICE_ROOT = Path(__file__).resolve().parent.parent

SHARE_LINK_COLUMNS = {
    "id",
    "token",
    "resource_type",
    "resource_id",
    "workspace_id",
    "created_by",
    "created_at",
    "expires_at",
    "expired_at",
}
POLICY_COLUMNS = {"workspace_id", "default_days", "max_days", "updated_by", "updated_at"}
EXISTING_TABLES = {"documents", "document_versions", "comments", "templates"}


def _database_urls() -> list[pytest.param]:
    params = [pytest.param("sqlite", id="sqlite")]
    pg_url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    params.append(
        pytest.param(
            pg_url or "",
            id="postgres",
            marks=pytest.mark.skipif(not pg_url, reason="MIGRATION_TEST_DATABASE_URL not set"),
        )
    )
    return params


@pytest.fixture(params=_database_urls())
def database_url(request, tmp_path: Path) -> Iterator[str]:
    if request.param == "sqlite":
        yield f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
        return
    url = request.param
    _alembic(url, "downgrade", "base")
    yield url
    _alembic(url, "downgrade", "base")


def _alembic(database_url: str, *args: str) -> None:
    env = {**os.environ, "DOC_SVC_DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=SERVICE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def _schema(database_url: str) -> dict[str, dict]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:

            def _inspect(sync_conn):
                insp = inspect(sync_conn)
                tables = {}
                for table in insp.get_table_names():
                    tables[table] = {
                        "columns": {
                            c["name"]: {
                                "type": str(c["type"]),
                                "nullable": c["nullable"],
                                "default": c.get("default"),
                            }
                            for c in insp.get_columns(table)
                        },
                        "indexes": sorted(
                            (i["name"], tuple(i["column_names"]))
                            for i in insp.get_indexes(table)
                        ),
                        "pk": set(insp.get_pk_constraint(table)["constrained_columns"]),
                    }
                return tables

            return await conn.run_sync(_inspect)
    finally:
        await engine.dispose()


async def _execute(database_url: str, sql: str, params: dict | None = None):
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            return result.fetchall() if result.returns_rows else []
    finally:
        await engine.dispose()


async def test_upgrade_creates_share_links_table(database_url: str):
    """Given the migration runs, Then a share_links table exists with the contract columns."""
    _alembic(database_url, "upgrade", "head")

    schema = await _schema(database_url)

    assert "share_links" in schema
    columns = schema["share_links"]["columns"]
    assert set(columns) == SHARE_LINK_COLUMNS
    assert schema["share_links"]["pk"] == {"id"}
    for not_null in ("token", "expires_at"):
        assert columns[not_null]["nullable"] is False
    assert columns["expired_at"]["nullable"] is True


async def test_share_links_token_is_unique(database_url: str):
    """Given the migration runs, Then share_links.token rejects duplicates."""
    _alembic(database_url, "upgrade", "head")
    insert = (
        "INSERT INTO share_links (id, token, resource_type, resource_id, workspace_id, "
        "created_by, expires_at) VALUES (:id, 'dup-token', 'folder', :rid, 'ws', :uid, "
        "CURRENT_TIMESTAMP)"
    )

    def _params() -> dict:
        is_pg = database_url.startswith("postgresql")
        new = (lambda: uuid.uuid4()) if is_pg else (lambda: uuid.uuid4().hex)
        return {"id": new(), "rid": new(), "uid": new()}

    await _execute(database_url, insert, _params())
    with pytest.raises(IntegrityError):
        await _execute(database_url, insert, _params())


async def test_upgrade_creates_workspace_share_policy_with_defaults(database_url: str):
    """Given the migration runs, Then workspace_share_policy exists and defaults to 30/90."""
    _alembic(database_url, "upgrade", "head")

    schema = await _schema(database_url)
    assert set(schema["workspace_share_policy"]["columns"]) == POLICY_COLUMNS
    assert schema["workspace_share_policy"]["pk"] == {"workspace_id"}

    await _execute(
        database_url, "INSERT INTO workspace_share_policy (workspace_id) VALUES ('ws-new')"
    )
    rows = await _execute(
        database_url,
        "SELECT default_days, max_days FROM workspace_share_policy WHERE workspace_id='ws-new'",
    )
    assert [tuple(r) for r in rows] == [(30, 90)]


@pytest.mark.parametrize(
    ("default_days", "max_days"),
    [(0, 90), (31, 30), (30, 91), (-1, 10), (91, 91)],
)
async def test_workspace_share_policy_check_rejects_out_of_range(
    database_url: str, default_days: int, max_days: int
):
    """Given the migration runs, Then CHECK 1 <= default_days <= max_days <= 90 is enforced."""
    _alembic(database_url, "upgrade", "head")

    with pytest.raises(IntegrityError):
        await _execute(
            database_url,
            "INSERT INTO workspace_share_policy (workspace_id, default_days, max_days) "
            "VALUES ('ws', :d, :m)",
            {"d": default_days, "m": max_days},
        )


@pytest.mark.parametrize(("default_days", "max_days"), [(1, 1), (1, 90), (90, 90), (7, 14)])
async def test_workspace_share_policy_check_accepts_boundaries(
    database_url: str, default_days: int, max_days: int
):
    """Given the migration runs, Then boundary values inside 1..90 with default <= max succeed."""
    _alembic(database_url, "upgrade", "head")

    await _execute(
        database_url,
        "INSERT INTO workspace_share_policy (workspace_id, default_days, max_days) "
        "VALUES ('ws', :d, :m)",
        {"d": default_days, "m": max_days},
    )


async def test_upgrade_and_downgrade_leave_existing_tables_untouched(database_url: str):
    """The migration upgrades and downgrades cleanly and does not change existing tables."""
    _alembic(database_url, "upgrade", "001")
    before = await _schema(database_url)
    doc_id = uuid.uuid4() if database_url.startswith("postgresql") else uuid.uuid4().hex
    owner = uuid.uuid4() if database_url.startswith("postgresql") else uuid.uuid4().hex
    await _execute(
        database_url,
        "INSERT INTO documents (id, title, owner_id) VALUES (:id, 'Keep me', :owner)",
        {"id": doc_id, "owner": owner},
    )

    _alembic(database_url, "upgrade", "head")
    upgraded = await _schema(database_url)
    for table in EXISTING_TABLES:
        assert upgraded[table] == before[table]

    _alembic(database_url, "downgrade", "001")
    downgraded = await _schema(database_url)
    assert "share_links" not in downgraded
    assert "workspace_share_policy" not in downgraded
    for table in EXISTING_TABLES:
        assert downgraded[table] == before[table]
    rows = await _execute(database_url, "SELECT title FROM documents")
    assert [r[0] for r in rows] == ["Keep me"]

    _alembic(database_url, "upgrade", "head")
    assert {"share_links", "workspace_share_policy"} <= set(await _schema(database_url))


async def test_upgrade_succeeds_when_startup_already_created_tables(database_url: str):
    """Given the service started at revision 001 (init_db ran create_all), When the
    migration runs, Then it upgrades cleanly and keeps the existing tables."""
    from app.models.share_link import ShareLink, WorkspaceSharePolicy

    _alembic(database_url, "upgrade", "001")
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: ShareLink.metadata.create_all(
                    c, tables=[ShareLink.__table__, WorkspaceSharePolicy.__table__]
                )
            )
    finally:
        await engine.dispose()

    _alembic(database_url, "upgrade", "head")
    schema = await _schema(database_url)
    assert set(schema["share_links"]["columns"]) == SHARE_LINK_COLUMNS
    assert set(schema["workspace_share_policy"]["columns"]) == POLICY_COLUMNS

    is_pg = database_url.startswith("postgresql")
    ids = {k: uuid.uuid4() if is_pg else uuid.uuid4().hex for k in ("id", "rid", "uid")}
    await _execute(
        database_url,
        "INSERT INTO share_links (id, token, resource_id, workspace_id, created_by, "
        "expires_at) VALUES (:id, 'startup-token', :rid, 'ws', :uid, CURRENT_TIMESTAMP)",
        ids,
    )
    await _execute(database_url, "INSERT INTO workspace_share_policy (workspace_id) VALUES ('ws')")
    assert await _execute(
        database_url, "SELECT default_days, max_days FROM workspace_share_policy"
    ) == [(30, 90)]

    _alembic(database_url, "downgrade", "001")
    schema = await _schema(database_url)
    assert "share_links" not in schema
    assert "workspace_share_policy" not in schema


def test_offline_sql_generation_includes_new_tables():
    """Given operators render the migration with `alembic upgrade --sql`, Then the SQL
    for revision 002 is generated and creates both tables."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "001:002", "--sql"],
        cwd=SERVICE_ROOT,
        env={**os.environ, "DOC_SVC_DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE share_links" in result.stdout
    assert "CREATE TABLE workspace_share_policy" in result.stdout
