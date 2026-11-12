"""The database connection string must come from the environment, never from code."""

import configparser
import re
from pathlib import Path

import pytest
from pydantic import SecretStr

from alembic import command
from alembic import config as alembic_config
from app.config import DatabaseNotConfiguredError, Settings, settings
from app.db import session as db_session
from app.main import app, lifespan

REPO_SERVICE_DIR = Path(__file__).resolve().parents[1]
CREDENTIALED_URL = re.compile(r"\w+(\+\w+)?://[^/\s:@]+:[^/\s@]+@")


@pytest.fixture
def reset_engine():
    db_session.get_session_factory.cache_clear()
    db_session.get_engine.cache_clear()
    yield
    db_session.get_session_factory.cache_clear()
    db_session.get_engine.cache_clear()


def test_default_settings_carry_no_database_url(monkeypatch):
    monkeypatch.delenv("DOC_SVC_DATABASE_URL", raising=False)
    unconfigured = Settings(_env_file=None)

    assert unconfigured.database_url.get_secret_value() == ""
    with pytest.raises(DatabaseNotConfiguredError, match="DOC_SVC_DATABASE_URL"):
        unconfigured.require_database_url()


def test_database_url_is_read_from_environment(monkeypatch):
    url = "postgresql+asyncpg://svc:from-env@db.internal:5432/otterworks"
    monkeypatch.setenv("DOC_SVC_DATABASE_URL", url)
    configured = Settings(_env_file=None)

    assert configured.require_database_url() == url
    assert "from-env" not in repr(configured)
    assert "from-env" not in str(configured.model_dump())


def test_blank_database_url_is_rejected(monkeypatch):
    monkeypatch.setenv("DOC_SVC_DATABASE_URL", "   ")
    with pytest.raises(DatabaseNotConfiguredError):
        Settings(_env_file=None).require_database_url()


def test_source_tree_has_no_baked_in_database_password():
    for path in (REPO_SERVICE_DIR / "app" / "config.py", REPO_SERVICE_DIR / "alembic.ini"):
        assert not CREDENTIALED_URL.search(path.read_text(encoding="utf-8")), path

    ini = configparser.ConfigParser(interpolation=None)
    ini.read(REPO_SERVICE_DIR / "alembic.ini", encoding="utf-8")
    assert not ini.has_option("alembic", "sqlalchemy.url")


def test_alembic_env_preserves_percent_encoded_password(monkeypatch):
    url = "postgresql+asyncpg://otterworks:p%40ss%25word@db:5432/otterworks"
    monkeypatch.setattr(settings, "database_url", SecretStr(url))
    alembic_cfg = alembic_config.Config()
    alembic_cfg.set_main_option("script_location", str(REPO_SERVICE_DIR / "alembic"))

    command.upgrade(alembic_cfg, "head", sql=True)

    assert alembic_cfg.get_main_option("sqlalchemy.url") == url


def test_engine_is_not_created_without_database_url(monkeypatch, reset_engine):
    monkeypatch.setattr(settings, "database_url", SecretStr(""))
    with pytest.raises(DatabaseNotConfiguredError):
        db_session.get_engine()


async def test_startup_fails_closed_without_database_url(monkeypatch, reset_engine):
    monkeypatch.setattr(settings, "database_url", SecretStr(""))
    with pytest.raises(DatabaseNotConfiguredError):
        async with lifespan(app):
            pass


async def test_startup_uses_configured_database_url(monkeypatch, reset_engine, tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'doc.db'}"
    monkeypatch.setattr(settings, "database_url", SecretStr(url))
    seen: dict[str, object] = {}
    real_create = db_session.create_async_engine

    def create_without_pool_sizing(engine_url, **kwargs):
        # SQLite's pool does not accept the Postgres pool sizing; record it instead.
        seen["url"] = engine_url
        seen["pool_size"] = kwargs.pop("pool_size")
        kwargs.pop("max_overflow")
        return real_create(engine_url, **kwargs)

    monkeypatch.setattr(db_session, "create_async_engine", create_without_pool_sizing)
    async with lifespan(app):
        assert str(db_session.get_engine().url) == url
    assert seen == {"url": url, "pool_size": settings.db_pool_size}
    assert db_session.get_engine.cache_info().currsize == 0
