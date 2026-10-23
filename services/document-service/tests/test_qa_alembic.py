"""QA audit: alembic migrations apply cleanly and match the ORM models.

The offline test renders the migration SQL with the PostgreSQL dialect (no DB needed).
The live tests run only when ``QA_ALEMBIC_DATABASE_URL`` points at a scratch
PostgreSQL database (``postgresql+asyncpg://...``); they upgrade, diff against the
models and downgrade it.
"""

import asyncio  # noqa: I001
import io
import os
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from alembic import command
from app.db.base import Base

SERVICE_DIR = Path(__file__).resolve().parents[1]
LIVE_URL = os.getenv("QA_ALEMBIC_DATABASE_URL")


def _config(url: str | None = None) -> Config:
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "alembic"))
    if url:
        cfg.attributes["qa_url"] = url
    return cfg


def test_single_head_and_linear_history():
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["001"]
    revisions = list(script.walk_revisions())
    assert [r.revision for r in revisions] == ["001"]
    assert revisions[0].down_revision is None


def test_offline_upgrade_renders_all_tables():
    out = io.StringIO()
    with redirect_stdout(out):
        command.upgrade(_config(), "head", sql=True)
    sql = out.getvalue()
    for table in ("documents", "document_versions", "comments", "templates"):
        assert f"CREATE TABLE {table}" in sql
    assert "REFERENCES documents (id) ON DELETE CASCADE" in sql
    assert "CREATE INDEX ix_documents_owner_id" in sql


def test_migration_tables_match_models():
    out = io.StringIO()
    with redirect_stdout(out):
        command.upgrade(_config(), "head", sql=True)
    sql = out.getvalue()
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            assert column.name in sql, f"{table.name}.{column.name} missing from migration"


def test_offline_downgrade_drops_all_tables():
    out = io.StringIO()
    with redirect_stdout(out):
        command.downgrade(_config(), "001:base", sql=True)
    sql = out.getvalue()
    for table in ("documents", "document_versions", "comments", "templates"):
        assert f"DROP TABLE {table}" in sql


live = pytest.mark.skipif(not LIVE_URL, reason="QA_ALEMBIC_DATABASE_URL not set")


def _run_live(url: str, *steps: str) -> None:
    import app.config

    original = app.config.settings.database_url
    app.config.settings.database_url = url
    try:
        for step in steps:
            if step == "upgrade":
                command.upgrade(_config(), "head")
            else:
                command.downgrade(_config(), "base")
    finally:
        app.config.settings.database_url = original


async def _diff(url: str) -> list:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata)
            )
    finally:
        await engine.dispose()


@live
def test_live_upgrade_matches_models_and_downgrades():
    _run_live(LIVE_URL, "downgrade", "upgrade")
    diff = asyncio.run(_diff(LIVE_URL))
    # server_default differences are not reported by compare_metadata; anything else is drift.
    assert diff == [], diff
    _run_live(LIVE_URL, "downgrade", "upgrade")
