"""The local compose stack must not run on signing secrets committed to the repo.

A shared JWT_SECRET fallback lets anyone who reads docker-compose.yml mint an
OWNER token for every service, and publishing the backends on every interface
lets that token skip the gateway entirely.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE = REPO_ROOT / "docker-compose.yml"
LOCAL_ENV = REPO_ROOT / "scripts" / "local-env.sh"

SIGNING_SECRETS = ("JWT_SECRET", "SECRET_KEY_BASE")
#: The edge a developer is meant to reach from another machine.
PUBLIC_SERVICES = {"api-gateway", "web-app", "admin-dashboard"}
REQUIRED_VAR = re.compile(r"^\$\{(?P<name>[A-Z_]+):\?[^}]+\}$")


def services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE.read_text())["services"]


def test_signing_secrets_have_no_committed_value() -> None:
    seen = 0
    for name, definition in services().items():
        env = definition.get("environment") or {}
        for key in SIGNING_SECRETS:
            if key not in env:
                continue
            seen += 1
            match = REQUIRED_VAR.match(str(env[key]))
            assert match and match["name"] == key, (
                f"{name}.{key} must be ${{{key}:?...}} with no fallback, got {env[key]!r}"
            )
    assert seen >= 2, "expected JWT_SECRET/SECRET_KEY_BASE in docker-compose.yml"


def test_backend_ports_are_bound_to_loopback() -> None:
    for name, definition in services().items():
        if name in PUBLIC_SERVICES:
            continue
        for mapping in definition.get("ports") or []:
            if isinstance(mapping, dict):
                address = mapping.get("host_ip")
            else:
                fields = str(mapping).split(":")
                address = fields[0] if len(fields) == 3 else None
            assert address == "127.0.0.1", f"{name} publishes {mapping!r} on every interface"


def run_local_env(env_file: Path) -> None:
    subprocess.run(["bash", str(LOCAL_ENV), str(env_file)], check=True, capture_output=True)


def read_env(env_file: Path) -> dict[str, str]:
    lines = env_file.read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def test_local_env_generates_random_secrets_once(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DEVIN_API_KEY=keep-me\nSECRET_KEY_BASE=")

    run_local_env(env_file)
    first = read_env(env_file)
    assert first["DEVIN_API_KEY"] == "keep-me"
    for key in SIGNING_SECRETS:
        assert re.fullmatch(r"[0-9a-f]{128}", first[key]), key
    assert first["JWT_SECRET"] != first["SECRET_KEY_BASE"]
    assert env_file.read_text().count("SECRET_KEY_BASE=") == 1
    assert env_file.stat().st_mode & 0o077 == 0

    run_local_env(env_file)
    assert read_env(env_file) == first

    other = tmp_path / "other.env"
    run_local_env(other)
    assert read_env(other)["JWT_SECRET"] != first["JWT_SECRET"]
