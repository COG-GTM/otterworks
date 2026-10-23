"""The compose stack must not ship a signing key or shared secret anyone can read.

docker-compose.yml used to fall back to committed values for JWT_SECRET,
SECRET_KEY_BASE and ALERT_WEBHOOK_SECRET (and an empty CHAOS_SECRET), so any
deployment that forgot to override them accepted admin tokens minted by anyone
who had read the repo. These tests pin the fail-closed form and the generator
that `make env` uses to keep local bring-up working.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "ensure-local-env.sh"
COMPOSE_FILES = sorted(REPO.glob("docker-compose*.yml"))

REQUIRED = {"JWT_SECRET": 64, "SECRET_KEY_BASE": 128, "ALERT_WEBHOOK_SECRET": 64, "CHAOS_SECRET": 64}
PUBLIC_DEFAULTS = [
    "otterworks-local-dev-jwt-secret-change-me-in-production",
    "dev-jwt-secret-otterworks-2024-change-in-production",
    "otterworks-dev-secret",
    "dev-secret-key-base-otterworks-change-in-production",
    "demo-alert-secret",
]


def service_environments():
    for path in COMPOSE_FILES:
        services = (yaml.safe_load(path.read_text()) or {}).get("services") or {}
        for name, service in services.items():
            env = service.get("environment") or {}
            if isinstance(env, list):
                env = dict(item.split("=", 1) if "=" in item else (item, None) for item in env)
            yield path.name, name, env


def test_compose_files_are_found() -> None:
    assert {p.name for p in COMPOSE_FILES} >= {"docker-compose.yml", "docker-compose.infra.yml"}


@pytest.mark.parametrize("default", PUBLIC_DEFAULTS)
def test_no_compose_file_contains_a_public_default(default: str) -> None:
    offenders = [p.name for p in COMPOSE_FILES if default in p.read_text()]
    assert offenders == []


def test_every_secret_is_required_with_no_fallback() -> None:
    checked = []
    for file, service, env in service_environments():
        for name in REQUIRED:
            if name not in env:
                continue
            value = str(env[name])
            assert re.fullmatch(rf"\$\{{{name}:\?[^}}]+\}}", value), (
                f"{file} {service}: {name}={value!r} must be ${{{name}:?...}} "
                "so compose refuses to start without a real secret"
            )
            checked.append((service, name))
    services = {service for service, name in checked if name == "JWT_SECRET"}
    assert "api-gateway" in services and "admin-service" in services
    assert ("admin-service", "SECRET_KEY_BASE") in checked
    assert ("admin-service", "CHAOS_SECRET") in checked
    assert ("admin-service", "ALERT_WEBHOOK_SECRET") in checked


def run_script(env_file: Path, **env: str) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if k not in REQUIRED}
    return subprocess.run(
        [str(SCRIPT), str(env_file)], env={**base, **env}, capture_output=True, text=True
    )


def parse(env_file: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line
    )


def test_generates_every_missing_secret_into_a_private_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    result = run_script(env_file)
    assert result.returncode == 0, result.stderr
    values = parse(env_file)
    for name, length in REQUIRED.items():
        assert re.fullmatch(rf"[0-9a-f]{{{length}}}", values[name]), name
    assert len(set(values.values())) == len(REQUIRED)
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_is_idempotent_and_keeps_existing_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("COMPOSE_PROJECT_NAME=ow\nJWT_SECRET='kept-jwt'")
    assert run_script(env_file).returncode == 0
    first = env_file.read_text()
    assert run_script(env_file).returncode == 0
    assert env_file.read_text() == first
    values = parse(env_file)
    assert values["JWT_SECRET"] == "'kept-jwt'"
    assert values["COMPOSE_PROJECT_NAME"] == "ow"
    assert set(REQUIRED) <= set(values)


def test_a_value_exported_in_the_shell_is_not_written(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    assert run_script(env_file, JWT_SECRET="from-shell").returncode == 0
    assert "JWT_SECRET" not in parse(env_file)


@pytest.mark.parametrize("default", PUBLIC_DEFAULTS)
def test_refuses_a_public_default_in_the_env_file(tmp_path: Path, default: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"JWT_SECRET={default}\n")
    result = run_script(env_file)
    assert result.returncode == 1
    assert "public default" in result.stderr
    assert env_file.read_text() == f"JWT_SECRET={default}\n"


def test_refuses_a_public_default_exported_in_the_shell(tmp_path: Path) -> None:
    result = run_script(tmp_path / ".env", ALERT_WEBHOOK_SECRET="demo-alert-secret")
    assert result.returncode == 1
    assert "ALERT_WEBHOOK_SECRET" in result.stderr


def test_refuses_a_public_default_in_the_env_file_even_when_the_shell_overrides_it(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("JWT_SECRET=otterworks-local-dev-jwt-secret-change-me-in-production\n")
    result = run_script(env_file, JWT_SECRET="a-real-secret-from-the-shell")
    assert result.returncode == 1
    assert str(env_file) in result.stderr


@pytest.mark.parametrize(
    "line",
    [
        "JWT_SECRET=otterworks-local-dev-jwt-secret-change-me-in-production # local",
        "JWT_SECRET='otterworks-local-dev-jwt-secret-change-me-in-production' # local",
        'export JWT_SECRET="otterworks-local-dev-jwt-secret-change-me-in-production"',
    ],
)
def test_refuses_a_quoted_or_commented_public_default(tmp_path: Path, line: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(line + "\n")
    assert run_script(env_file).returncode == 1


def test_refuses_an_exported_but_empty_secret(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("JWT_SECRET=abc\n")
    result = run_script(env_file, JWT_SECRET="")
    assert result.returncode == 1
    assert "unset JWT_SECRET" in result.stderr


def test_an_unquoted_value_with_a_comment_counts_as_set(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("JWT_SECRET=abc123 # mine\nSECRET_KEY_BASE=  # todo\n")
    assert run_script(env_file).returncode == 0
    lines = env_file.read_text().splitlines()
    assert [line for line in lines if line.startswith("JWT_SECRET=")] == ["JWT_SECRET=abc123 # mine"]
    key_base = [line for line in lines if line.startswith("SECRET_KEY_BASE=")]
    assert re.fullmatch(r"SECRET_KEY_BASE=[0-9a-f]{128}", key_base[-1])
