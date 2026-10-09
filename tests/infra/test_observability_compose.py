"""Static checks on the local observability stack in docker-compose.infra.yml.

Grafana and Prometheus are published on the developer's host, so they must not
ship committed credentials, unauthenticated admin APIs, or all-interface binds.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
INFRA_COMPOSE = REPO_ROOT / "docker-compose.infra.yml"
GUARD = REPO_ROOT / "observability" / "grafana" / "require-secrets.sh"
CONTACT_POINTS = (
    REPO_ROOT / "observability" / "grafana" / "provisioning" / "alerting" / "contact-points.yml"
)

STRONG_PASSWORD = "grafana-test-password-0123"
STRONG_SECRET = "alert-test-secret-0123456789"


@pytest.fixture(scope="module")
def services() -> dict:
    return yaml.safe_load(INFRA_COMPOSE.read_text())["services"]


def _host_bind(port: str) -> str:
    parts = str(port).split(":")
    return parts[0] if len(parts) == 3 else "0.0.0.0"


@pytest.mark.parametrize("service", ["prometheus", "grafana"])
def test_observability_ports_bind_to_loopback(services: dict, service: str) -> None:
    ports = services[service]["ports"]
    assert ports
    assert all(_host_bind(p) == "127.0.0.1" for p in ports), ports


def test_prometheus_admin_and_lifecycle_apis_disabled(services: dict) -> None:
    command = services["prometheus"]["command"]
    assert "--web.enable-admin-api" not in command
    assert "--web.enable-lifecycle" not in command


def test_grafana_secrets_come_from_env_without_default(services: dict) -> None:
    env = services["grafana"]["environment"]
    assert env["GF_SECURITY_ADMIN_PASSWORD"] == "${GRAFANA_ADMIN_PASSWORD:-}"
    assert env["ALERT_WEBHOOK_SECRET"] == "${ALERT_WEBHOOK_SECRET:-}"


def test_no_committed_grafana_credentials_in_infra_compose() -> None:
    text = INFRA_COMPOSE.read_text()
    assert "demo-alert-secret" not in text
    assert not re.search(r"GF_SECURITY_ADMIN_PASSWORD:\s*['\"]?otterworks", text)


def test_grafana_starts_through_secret_guard(services: dict) -> None:
    grafana = services["grafana"]
    entrypoint = grafana["entrypoint"]
    assert entrypoint[-1] == "/run.sh"
    mounted = {v.split(":")[1]: v.split(":")[0] for v in grafana["volumes"] if v.startswith("./")}
    assert entrypoint[1] in mounted
    assert (REPO_ROOT / mounted[entrypoint[1]]).resolve() == GUARD.resolve()


def test_contact_point_still_sends_secret_from_env() -> None:
    text = CONTACT_POINTS.read_text()
    assert "authorization_credentials: $ALERT_WEBHOOK_SECRET" in text


def _run_guard(env: dict[str, str], path: str = "/usr/bin:/bin") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(GUARD), "sh", "-c", "echo started"],
        env={"PATH": path, "GF_PATHS_DATA": "/nonexistent-grafana-data", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_guard_starts_grafana_with_strong_secrets() -> None:
    result = _run_guard(
        {"GF_SECURITY_ADMIN_PASSWORD": STRONG_PASSWORD, "ALERT_WEBHOOK_SECRET": STRONG_SECRET}
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "started"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"ALERT_WEBHOOK_SECRET": STRONG_SECRET}, "GRAFANA_ADMIN_PASSWORD is required"),
        (
            {"GF_SECURITY_ADMIN_PASSWORD": "", "ALERT_WEBHOOK_SECRET": STRONG_SECRET},
            "GRAFANA_ADMIN_PASSWORD is required",
        ),
        ({"GF_SECURITY_ADMIN_PASSWORD": STRONG_PASSWORD}, "ALERT_WEBHOOK_SECRET is required"),
        (
            {"GF_SECURITY_ADMIN_PASSWORD": "otterworks", "ALERT_WEBHOOK_SECRET": STRONG_SECRET},
            "GRAFANA_ADMIN_PASSWORD must not be a well-known default",
        ),
        (
            {
                "GF_SECURITY_ADMIN_PASSWORD": STRONG_PASSWORD,
                "ALERT_WEBHOOK_SECRET": "demo-alert-secret",
            },
            "ALERT_WEBHOOK_SECRET must not be a well-known default",
        ),
        (
            {"GF_SECURITY_ADMIN_PASSWORD": "short", "ALERT_WEBHOOK_SECRET": STRONG_SECRET},
            "GRAFANA_ADMIN_PASSWORD must be at least 12 characters",
        ),
    ],
)
def test_guard_refuses_missing_or_weak_secrets(env: dict[str, str], message: str) -> None:
    result = _run_guard(env)
    assert result.returncode == 64
    assert "started" not in result.stdout
    assert message in result.stderr
    for value in env.values():
        if value and value not in {"otterworks", "demo-alert-secret", "short"}:
            assert value not in result.stderr


def _fake_grafana_cli(tmp_path: Path, exit_code: int) -> tuple[str, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    cli = bin_dir / "grafana"
    cli.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{calls}"\nexit {exit_code}\n')
    cli.chmod(0o755)
    return f"{bin_dir}:/usr/bin:/bin", calls


def _existing_data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "grafana.db").write_bytes(b"")
    return data


STRONG_ENV = {"GF_SECURITY_ADMIN_PASSWORD": STRONG_PASSWORD, "ALERT_WEBHOOK_SECRET": STRONG_SECRET}


def test_guard_reapplies_password_to_existing_grafana_database(tmp_path: Path) -> None:
    path, calls = _fake_grafana_cli(tmp_path, exit_code=0)
    data = _existing_data_dir(tmp_path)
    result = _run_guard({**STRONG_ENV, "GF_PATHS_DATA": str(data)}, path=path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "started"
    assert (
        calls.read_text().split("\n")[0].endswith(f"admin reset-admin-password {STRONG_PASSWORD}")
    )


def test_guard_refuses_to_start_when_password_reset_fails(tmp_path: Path) -> None:
    path, _ = _fake_grafana_cli(tmp_path, exit_code=1)
    data = _existing_data_dir(tmp_path)
    result = _run_guard({**STRONG_ENV, "GF_PATHS_DATA": str(data)}, path=path)
    assert result.returncode == 64
    assert "started" not in result.stdout
    assert "could not apply GRAFANA_ADMIN_PASSWORD" in result.stderr
    assert STRONG_PASSWORD not in result.stderr


def test_guard_skips_reset_on_fresh_grafana_volume(tmp_path: Path) -> None:
    path, calls = _fake_grafana_cli(tmp_path, exit_code=1)
    data = tmp_path / "data"
    data.mkdir()
    result = _run_guard({**STRONG_ENV, "GF_PATHS_DATA": str(data)}, path=path)
    assert result.returncode == 0, result.stderr
    assert not calls.exists()


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
def test_compose_file_still_renders_without_observability_secrets() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(INFRA_COMPOSE), "config", "--quiet"],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    if "docker: 'compose' is not a docker command" in result.stderr:
        pytest.skip("docker compose plugin not installed")
    assert result.returncode == 0, result.stderr
