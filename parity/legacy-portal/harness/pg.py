"""Local PostgreSQL helpers for the postgres stage.

Talks to the database from docker-compose.postgres.yml through the ``psql``
client, and builds the Spring datasource overrides each JVM is booted with.
Connection settings come from PARITY_PG_* so CI can point at a service
container instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .scenario import ROOT

SQL_DIR = ROOT / "postgres"
LEGACY_LAYOUT = SQL_DIR / "00-legacy-layout.sql"
HANDOVER = SQL_DIR / "10-handover.sql"


def host() -> str:
    return os.environ.get("PARITY_PG_HOST", "127.0.0.1")


def port() -> str:
    return os.environ.get("PARITY_PG_PORT", "15432")


def database() -> str:
    return os.environ.get("PARITY_PG_DB", "legacyportal")


def jdbc_url() -> str:
    return f"jdbc:postgresql://{host()}:{port()}/{database()}"


def spring_args(role: str) -> list[str]:
    """Boot a service/monolith against the local database as ``role`` (password == role)."""
    return [
        "--spring.profiles.active=postgres",
        f"--spring.datasource.url={jdbc_url()}",
        f"--spring.datasource.username={role}",
        f"--spring.datasource.password={role}",
    ]


def psql(
    sql: str | None = None,
    file: Path | None = None,
    role: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    binary = shutil.which("psql")
    if not binary:
        raise RuntimeError("psql client not found; install postgresql-client")
    user = role or os.environ.get("PARITY_PG_SUPERUSER", "postgres")
    password = role or os.environ.get("PARITY_PG_SUPERPASSWORD", "postgres")
    cmd = [binary, "-h", host(), "-p", port(), "-U", user, "-d", database(), "-v", "ON_ERROR_STOP=1", "-qAt"]
    cmd += ["-f", str(file)] if file else ["-c", sql or ""]
    env = {**os.environ, "PGPASSWORD": password}
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise RuntimeError(f"psql failed ({user}): {result.stderr.strip()}")
    return result


def wait_ready(timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        if psql("SELECT 1", check=False).returncode == 0:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(f"postgres at {host()}:{port()} not reachable")
        time.sleep(1)


def reset(layout: str) -> None:
    """Recreate empty schemas in ``legacy`` (monolith-owned) or ``split`` (service-owned) layout."""
    if layout not in ("legacy", "split"):
        raise ValueError(layout)
    wait_ready()
    psql(file=LEGACY_LAYOUT)
    if layout == "split":
        psql(file=HANDOVER)
