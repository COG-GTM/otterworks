from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "migrations" / "001_initial.sql"
SEED = ROOT / "db" / "seed.sql"


def connect() -> sqlite3.Connection:
    path = Path(settings.database_path)
    if path.parent != Path("."):
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def reset() -> None:
    with connect() as connection:
        connection.executescript(MIGRATION.read_text())
        connection.executescript(SEED.read_text())
