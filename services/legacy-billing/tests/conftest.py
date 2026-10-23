"""Shared fixtures for the legacy-billing QA tests.

Run with:
    uv run --with-requirements app/requirements.txt --with pytest pytest tests
from services/legacy-billing. Stored-procedure tests need the procs stack
(`make procs-up NS=dev`) and skip when its database is unreachable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

TENANT = {n: f"00000000-0000-0000-0000-00000000000{n}" for n in range(1, 10)}
STARTER = "10000000-0000-0000-0000-000000000001"
GROWTH = "10000000-0000-0000-0000-000000000002"
SCALE = "10000000-0000-0000-0000-000000000003"


def _dsn() -> dict:
    return {
        "host": os.getenv("LEGACY_BILLING_DB_HOST", "localhost"),
        "port": int(os.getenv("LEGACY_BILLING_DB_PORT", "55445")),
        "dbname": os.getenv("LEGACY_BILLING_DB_NAME", "billing_dev"),
        "user": os.getenv("LEGACY_BILLING_DB_USER", "billing"),
        "password": os.getenv("LEGACY_BILLING_DB_PASSWORD", os.getenv("DB_PASSWORD", "billing")),
        "connect_timeout": 3,
    }


@pytest.fixture
def db():
    """A connection whose work is always rolled back, so seed data stays pristine."""
    try:
        connection = psycopg.connect(**_dsn())
    except psycopg.OperationalError as error:
        pytest.skip(f"legacy billing database unavailable: {error}")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def query(connection, sql: str, params: tuple = ()) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        if cursor.description is None:
            return []
        names = [column.name for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]
