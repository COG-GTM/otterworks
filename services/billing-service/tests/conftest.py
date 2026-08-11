from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]))


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("BILLING_SVC_DATABASE_PATH", str(tmp_path / "billing.sqlite3"))
    from app import config

    config.settings.database_path = str(tmp_path / "billing.sqlite3")
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
