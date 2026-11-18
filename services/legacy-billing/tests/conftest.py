import os
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

import app as billing_app

DB_DIR = Path(__file__).resolve().parent.parent / "db"
SQL_FILES = [
    DB_DIR / "schema.sql",
    DB_DIR / "procs" / "plans.sql",
    DB_DIR / "procs" / "rating.sql",
    DB_DIR / "procs" / "invoicing.sql",
    DB_DIR / "procs" / "dunning.sql",
    DB_DIR / "seed.sql",
]
TEST_DSN = os.getenv("LEGACY_BILLING_TEST_DSN")


def pytest_collection_modifyitems(config, items):
    if TEST_DSN:
        return
    if os.getenv("LEGACY_BILLING_REQUIRE_DB") == "1":
        raise pytest.UsageError("LEGACY_BILLING_REQUIRE_DB=1 but LEGACY_BILLING_TEST_DSN is unset")
    skip = pytest.mark.skip(reason="LEGACY_BILLING_TEST_DSN not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def client():
    billing_app.app.config.update(TESTING=True)
    return billing_app.app.test_client()


@pytest.fixture(scope="session")
def billing_schema():
    with psycopg.connect(TEST_DSN, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS billing CASCADE")
        for path in SQL_FILES[:-1]:
            connection.execute(path.read_text())
        tables = [
            row[0] for row in connection.execute(
                "SELECT format('billing.%I', tablename) FROM pg_tables WHERE schemaname = 'billing'"
            )
        ]
    return tables


@pytest.fixture
def db(monkeypatch, billing_schema):
    with psycopg.connect(TEST_DSN, autocommit=True) as connection:
        connection.execute(f"TRUNCATE {', '.join(billing_schema)} CASCADE")
        connection.execute(SQL_FILES[-1].read_text())
    params = conninfo_to_dict(TEST_DSN)
    for env, key, default in (
        ("DB_HOST", "host", "localhost"),
        ("DB_PORT", "port", "5432"),
        ("DB_NAME", "dbname", "billing_dev"),
        ("DB_USER", "user", "billing"),
        ("DB_PASSWORD", "password", "billing"),
    ):
        monkeypatch.setenv(env, str(params.get(key, default)))

    def query(sql, params=()):
        with psycopg.connect(TEST_DSN, autocommit=True) as connection:
            cursor = connection.execute(sql, params)
            return cursor.fetchall() if cursor.description else None

    return query
