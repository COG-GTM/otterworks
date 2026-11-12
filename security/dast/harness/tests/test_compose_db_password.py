"""The compose files must not commit a Postgres password (Sonar secrets:S6698).

Every database password in ``docker-compose*.yml`` is interpolated from the
required ``OTTERWORKS_DB_PASSWORD`` that ``scripts/ensure-local-env.sh`` writes
to the gitignored ``.env``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_FILES = (REPO_ROOT / "docker-compose.infra.yml", REPO_ROOT / "docker-compose.yml")
ENSURE_ENV = REPO_ROOT / "scripts" / "ensure-local-env.sh"
REQUIRED_REF = re.compile(r"^\$\{OTTERWORKS_DB_PASSWORD:\?[^}]+\}$")
URL_PASSWORD = re.compile(r"^[a-z0-9+]+://[^:/@]+:(?P<pw>[^@]*)@")
PASSWORD_KEYS = re.compile(r"(^|_)PASSWORD$")


def _db_secrets() -> list[tuple[str, str, str]]:
    found = []
    for path in COMPOSE_FILES:
        spec = yaml.safe_load(path.read_text()) or {}
        for name, service in (spec.get("services") or {}).items():
            env = service.get("environment") or {}
            for key, value in env.items():
                value = str(value)
                if PASSWORD_KEYS.search(key) and key.startswith(("POSTGRES", "DATABASE", "SPRING_DATASOURCE", "DB_")):
                    found.append((f"{path.name}:{name}:{key}", key, value))
                elif (m := URL_PASSWORD.match(value)) and not key.startswith("AWS"):
                    found.append((f"{path.name}:{name}:{key}", key, m.group("pw")))
    return found


def test_compose_files_reference_the_required_db_password() -> None:
    secrets = _db_secrets()
    assert len(secrets) >= 17
    bad = [where for where, _, value in secrets if not REQUIRED_REF.match(value)]
    assert bad == []


def test_old_public_password_is_gone() -> None:
    for path in COMPOSE_FILES:
        assert "otterworks_dev" not in path.read_text(), path.name


def _run(env_file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(ENSURE_ENV), str(env_file)], capture_output=True, text=True)


def test_ensure_env_generates_a_random_hex_password_once(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("JWT_SECRET=keep-me")
    assert _run(env_file).returncode == 0
    first = env_file.read_text()
    assert "JWT_SECRET=keep-me\n" in first
    (password,) = re.findall(r"^OTTERWORKS_DB_PASSWORD=([0-9a-f]{48})$", first, re.M)
    assert _run(env_file).returncode == 0
    assert env_file.read_text() == first
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"

    other = tmp_path / "other.env"
    _run(other)
    assert password not in other.read_text()


def test_ensure_env_rejects_the_old_public_password(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OTTERWORKS_DB_PASSWORD=otterworks_dev\n")
    result = _run(env_file)
    assert result.returncode == 1
    assert "old public default" in result.stderr


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
def test_compose_refuses_to_render_without_the_password(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "OTTERWORKS_DB_PASSWORD"}
    args = ["docker", "compose", "--project-directory", str(tmp_path)]
    for path in COMPOSE_FILES:
        args += ["-f", str(path)]
    missing = subprocess.run([*args, "config", "-q"], capture_output=True, text=True, env=env)
    if "is not a docker command" in missing.stderr:
        pytest.skip("docker compose plugin not installed")
    assert missing.returncode != 0
    assert "OTTERWORKS_DB_PASSWORD is not set" in missing.stderr

    env["OTTERWORKS_DB_PASSWORD"] = "f00d" * 12
    rendered = subprocess.run([*args, "config"], capture_output=True, text=True, env=env)
    assert rendered.returncode == 0, rendered.stderr
    assert "postgres://otterworks:" + "f00d" * 12 + "@postgres:5432/otterworks" in rendered.stdout
