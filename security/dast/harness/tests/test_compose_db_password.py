"""The local compose stack must not ship a Postgres password in the repo.

docker-compose*.yml read POSTGRES_PASSWORD from the environment or the git-ignored
.env that scripts/ensure-local-env.sh generates; the old public `otterworks_dev`
default must not come back, and the generator must refuse it.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.infra.yml")
ENSURE = REPO / "scripts" / "ensure-local-env.sh"
DB_PASSWORD_KEYS = re.compile(r"^(POSTGRES|SPRING_DATASOURCE|DATABASE|DB)_PASSWORD$")
DSN = re.compile(r"^[a-z0-9+]+://[^:/@]+:([^@]+)@")
REQUIRED = re.compile(r"^\$\{POSTGRES_PASSWORD:\?[^}]*\}$")


def _db_secrets():
    for name in COMPOSE_FILES:
        services = yaml.safe_load((REPO / name).read_text())["services"]
        for svc, spec in services.items():
            for key, value in (spec.get("environment") or {}).items():
                value = str(value)
                if DB_PASSWORD_KEYS.match(key):
                    yield name, svc, key, value
                elif m := DSN.match(value):
                    yield name, svc, key, m.group(1)


def test_no_compose_file_contains_the_public_default() -> None:
    for name in COMPOSE_FILES:
        assert "otterworks_dev" not in (REPO / name).read_text(), name


def test_every_postgres_password_is_required_from_the_environment() -> None:
    secrets = list(_db_secrets())
    assert len(secrets) >= 15  # postgres itself plus every service that connects to it
    for name, svc, key, value in secrets:
        assert REQUIRED.match(value), f"{name}:{svc}.{key} = {value!r}"


def _ensure(tmp_path: Path, env_text: str | None = None, **env: str):
    env_file = tmp_path / ".env"
    if env_text is not None:
        env_file.write_text(env_text)
    run_env = {k: v for k, v in os.environ.items() if k != "POSTGRES_PASSWORD"}
    run_env.update(env, ENV_FILE=str(env_file))
    proc = subprocess.run(["bash", str(ENSURE)], env=run_env, capture_output=True, text=True)
    return proc, env_file


def test_ensure_generates_a_random_url_safe_password(tmp_path: Path) -> None:
    proc, env_file = _ensure(tmp_path, "JWT_SECRET=keep-me")
    assert proc.returncode == 0, proc.stderr
    lines = env_file.read_text().splitlines()
    assert lines[0] == "JWT_SECRET=keep-me"
    password = lines[1].removeprefix("POSTGRES_PASSWORD=")
    assert re.fullmatch(r"[0-9a-f]{48}", password)
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"

    again, _ = _ensure(tmp_path)
    assert again.returncode == 0
    assert env_file.read_text().splitlines()[1] == lines[1]


@pytest.mark.parametrize(
    ("env_text", "env"),
    [
        ("POSTGRES_PASSWORD=otterworks_dev\n", {}),
        (None, {"POSTGRES_PASSWORD": "otterworks_dev"}),
        ("POSTGRES_PASSWORD=short\n", {}),
        ("POSTGRES_PASSWORD=has@sign/and:colon-12345\n", {}),
    ],
)
def test_ensure_rejects_public_or_unsafe_passwords(tmp_path: Path, env_text, env) -> None:
    proc, _ = _ensure(tmp_path, env_text, **env)
    assert proc.returncode == 1
    assert "POSTGRES_PASSWORD" in proc.stderr


def test_existing_env_file_is_tightened_and_print_returns_the_password(tmp_path: Path) -> None:
    value = "a" * 32
    env_file = tmp_path / ".env"
    env_file.write_text(f"POSTGRES_PASSWORD={value}\n")
    env_file.chmod(0o644)
    proc, _ = _ensure(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"

    run_env = {k: v for k, v in os.environ.items() if k != "POSTGRES_PASSWORD"}
    run_env["ENV_FILE"] = str(env_file)
    printed = subprocess.run(
        ["bash", str(ENSURE), "--print"], env=run_env, capture_output=True, text=True
    )
    assert printed.stdout == f"{value}\n"
    exported = subprocess.run(
        ["bash", str(ENSURE), "--print"],
        env={**run_env, "POSTGRES_PASSWORD": "b" * 32},
        capture_output=True,
        text=True,
    )
    assert exported.stdout == "b" * 32 + "\n"


def test_make_never_echoes_the_password() -> None:
    proc = subprocess.run(
        ["make", "-n", "seed", "testdata-clean", "NS=t1"],
        cwd=REPO,
        env={**os.environ, "POSTGRES_PASSWORD": "c" * 32},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "c" * 32 not in proc.stdout
    assert "ensure-local-env.sh --print" in proc.stdout
