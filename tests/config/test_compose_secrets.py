"""The local compose stack must not ship working credentials or listen on every interface.

A committed default for a signing key or webhook secret is a credential every reader of
the repo holds, so each secret must come from the environment (scripts/ensure-local-env.sh
generates them into the gitignored .env), and published ports bind to loopback only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ["docker-compose.yml", "docker-compose.infra.yml"]
SECRET_KEYS = re.compile(r"(SECRET|PASSWORD|TOKEN|API_KEY)", re.IGNORECASE)
# Throwaway credentials for containers that are only reachable on the compose network
# or loopback (LocalStack's fixed test keys and the local Postgres password).
ALLOWED_LITERALS = {"test", "otterworks_dev"}
REQUIRED = re.compile(r"^\$\{(?P<name>[A-Z0-9_]+):\?[^}]*\}$")
OPTIONAL_EMPTY = re.compile(r"^\$\{[A-Z0-9_]+:-\}$")
REQUIRED_SECRETS = {
    "JWT_SECRET",
    "SECRET_KEY_BASE",
    "ALERT_WEBHOOK_SECRET",
    "CHAOS_SECRET",
    "GF_SECURITY_ADMIN_PASSWORD",
}


def services(name: str) -> dict:
    return (yaml.safe_load((REPO_ROOT / name).read_text()) or {}).get("services") or {}


def environment(definition: dict) -> dict[str, str]:
    env = definition.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) for item in env)
    return {k: str(v) for k, v in env.items()}


SECRET_SETTINGS = [
    pytest.param(service, key, value, id=f"{name}:{service}:{key}")
    for name in COMPOSE_FILES
    for service, definition in services(name).items()
    for key, value in environment(definition).items()
    if SECRET_KEYS.search(key)
]


@pytest.mark.parametrize(("service", "key", "value"), SECRET_SETTINGS)
def test_secrets_have_no_committed_value(service: str, key: str, value: str) -> None:
    if key in REQUIRED_SECRETS:
        assert REQUIRED.match(value), f"{service} {key} must be required from the env: {value!r}"
        return
    assert (
        REQUIRED.match(value) or OPTIONAL_EMPTY.match(value) or value in ALLOWED_LITERALS
    ), f"{service} {key} has a committed value"


def test_every_required_secret_is_wired() -> None:
    seen = {key for _, key, _ in (p.values for p in SECRET_SETTINGS)}
    assert REQUIRED_SECRETS <= seen


def test_ensure_local_env_generates_every_required_variable() -> None:
    script = (REPO_ROOT / "scripts/ensure-local-env.sh").read_text()
    referenced = {
        REQUIRED.match(value).group("name")
        for _, key, value in (p.values for p in SECRET_SETTINGS)
        if key in REQUIRED_SECRETS
    }
    for name in referenced:
        assert f"{name}:" in script, f"ensure-local-env.sh does not generate {name}"


PORTS = [
    pytest.param(service, str(mapping), id=f"{name}:{service}:{mapping}")
    for name in COMPOSE_FILES
    for service, definition in services(name).items()
    for mapping in definition.get("ports") or []
]


@pytest.mark.parametrize(("service", "mapping"), PORTS)
def test_published_ports_bind_to_loopback(service: str, mapping: str) -> None:
    assert mapping.startswith("127.0.0.1:"), f"{service} publishes {mapping} on all interfaces"


def test_prometheus_admin_and_lifecycle_apis_are_off() -> None:
    command = services("docker-compose.infra.yml")["prometheus"].get("command") or []
    assert "--web.enable-admin-api" not in command
    assert "--web.enable-lifecycle" not in command


def test_grafana_resets_the_admin_password_on_start() -> None:
    entrypoint = " ".join(services("docker-compose.infra.yml")["grafana"].get("entrypoint") or [])
    assert "reset-admin-password" in entrypoint and "GF_SECURITY_ADMIN_PASSWORD" in entrypoint
