"""The perimeter probes read deployment config and then attack what it declares.

Both halves matter: reading the wrong origin out of the compose file or the
charts makes the probe attack nothing, and a verdict that cannot tell a refusal
from an unreachable backend is the false pass the whole suite is built against.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probes import perimeter  # noqa: E402
from probes.base import Severity, Verdict  # noqa: E402
from probes.perimeter import (  # noqa: E402
    Origin,
    compose_origins,
    gateway_bypass_identity,
    ingress_origins,
)
from route_inventory import Route  # noqa: E402

VICTIM = "6c9a79ac-7d4e-49b7-a5c6-7eb146cd122d"


@dataclass
class StubIdentity:
    user_id: str = VICTIM


class StubContext:
    """Only the surface the perimeter probes use: a base URL and gateway requests."""

    def __init__(
        self, gateway: dict[str, int] | int = 401, base_url: str = "http://localhost:8080"
    ):
        self.base_url = base_url
        self._gateway = gateway
        self.victim = StubIdentity()
        self.requests: list[tuple[str, str]] = []

    def request(self, method: str, path: str, **_: object) -> httpx.Response:
        self.requests.append((method, path))
        status = self._gateway if isinstance(self._gateway, int) else self._gateway.get(path, 401)
        return response(status, url=f"{self.base_url}{path}", method=method)


def response(status: int, url: str = "http://backend/api/v1/files", method: str = "GET"):
    return httpx.Response(status, request=httpx.Request(method, url), json={"files": []})


def stub_direct(monkeypatch, statuses: dict[tuple[str, bool], int]) -> list[httpx.Request]:
    """Answer direct backend calls by (host, whether X-User-ID was sent)."""
    sent: list[httpx.Request] = []

    def fake(method: str, url: str, **kwargs) -> httpx.Response:
        request = httpx.Request(method, url, headers=kwargs.get("headers") or {})
        sent.append(request)
        spoofed = "x-user-id" in request.headers
        return response(statuses[(request.url.host, spoofed)], url=str(request.url))

    monkeypatch.setattr(perimeter.httpx, "request", fake)
    return sent


# ── reading the deployment config ────────────────────────────────────────────


def test_compose_origins_come_from_published_ports(tmp_path: Path) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  file-service:\n"
        '    ports: ["8082:8082"]\n'
        "  postgres:\n"
        '    ports: ["5432:5432"]\n'
        "  search-service:\n"
        "    expose: [8087]\n"
    )
    # postgres is not a header-trusting API, and a service that only `expose`s a
    # port is not published on the host at all.
    assert compose_origins("http://localhost:8080", compose) == [
        Origin("file-service", "http://localhost:8082", "docker-compose.yml ports", Severity.LOW)
    ]


def test_compose_origins_are_irrelevant_to_a_deployed_target(tmp_path: Path) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text('services:\n  file-service:\n    ports: ["8082:8082"]\n')
    assert compose_origins("https://api-t-example.otterworks.app", compose) == []


def test_ingress_origins_come_from_a_chart_that_publishes_its_own_host(tmp_path: Path) -> None:
    (tmp_path / "file-service").mkdir()
    (tmp_path / "file-service" / "values.yaml").write_text(
        "ingress:\n  enabled: true\n  hosts:\n    - host: files.example.test\n"
    )
    (tmp_path / "search-service").mkdir()
    (tmp_path / "search-service" / "values.yaml").write_text(
        "ingress:\n  enabled: false\n  hosts:\n    - host: search.example.test\n"
    )
    origins = ingress_origins("https://example.test", tmp_path)
    assert [(o.service, o.url, o.severity) for o in origins] == [
        ("file-service", "https://files.example.test", Severity.CRITICAL)
    ]


def test_ingress_origins_outside_the_target_site_are_left_alone(tmp_path: Path) -> None:
    """Authorization to scan one target is not authorization to scan a chart's host."""
    (tmp_path / "file-service").mkdir()
    (tmp_path / "file-service" / "values.yaml").write_text(
        "ingress:\n  enabled: true\n  hosts:\n    - host: files.somewhere-else.test\n"
    )
    assert ingress_origins("https://api.example.test", tmp_path) == []
    assert ingress_origins("http://localhost:8080", tmp_path) == []


def test_scope_is_the_target_and_what_is_under_it(monkeypatch) -> None:
    """Counting labels to guess a site puts strangers under a shared suffix in scope."""
    assert perimeter.in_scope("api.example.test", "api.example.test")
    assert perimeter.in_scope("files.api.example.test", "api.example.test")
    assert not perimeter.in_scope("files.example.test", "api.example.test")
    assert not perimeter.in_scope(
        "someone-else.eu-west-1.amazonaws.com", "us.eu-west-1.amazonaws.com"
    )
    # A host the target does not cover is attacked only once an operator names it.
    monkeypatch.setenv("DAST_ALLOW_ORIGIN_HOSTS", "files.example.test")
    assert perimeter.in_scope("files.example.test", "api.example.test")


# ── the bypass verdict ───────────────────────────────────────────────────────


@pytest.fixture
def only_file_service(monkeypatch):
    monkeypatch.setattr(perimeter, "ingress_origins", lambda target: [])
    monkeypatch.setattr(
        perimeter,
        "compose_origins",
        lambda target: [
            Origin("file-service", "http://backend:8082", "docker-compose.yml ports", Severity.LOW)
        ],
    )
    monkeypatch.setattr(perimeter, "reachable", lambda origin, timeout=3.0: True)


def test_no_declared_origin_is_secure(monkeypatch) -> None:
    monkeypatch.setattr(perimeter, "compose_origins", lambda target: [])
    monkeypatch.setattr(perimeter, "ingress_origins", lambda target: [])
    assert gateway_bypass_identity(StubContext()).verdict is Verdict.SECURE


def test_a_declared_origin_that_never_answers_is_inconclusive(monkeypatch) -> None:
    """Unroutable from here is not the same as not exposed."""
    monkeypatch.setattr(
        perimeter,
        "compose_origins",
        lambda target: [
            Origin("file-service", "http://backend:8082", "docker-compose.yml ports", Severity.LOW)
        ],
    )
    monkeypatch.setattr(perimeter, "ingress_origins", lambda target: [])
    monkeypatch.setattr(perimeter, "reachable", lambda origin, timeout=3.0: False)
    assert gateway_bypass_identity(StubContext()).verdict is Verdict.INCONCLUSIVE


def test_a_chosen_identity_that_is_served_is_the_finding(only_file_service, monkeypatch) -> None:
    stub_direct(monkeypatch, {("backend", True): 200, ("backend", False): 401})
    result = gateway_bypass_identity(StubContext())
    assert result.verdict is Verdict.VULNERABLE
    assert "caller picks who they are" in result.detail
    assert result.severity is Severity.LOW  # a compose port, not a public ingress


def test_a_backend_that_needs_no_identity_is_still_the_finding(
    only_file_service, monkeypatch
) -> None:
    stub_direct(monkeypatch, {("backend", True): 200, ("backend", False): 200})
    result = gateway_bypass_identity(StubContext())
    assert result.verdict is Verdict.VULNERABLE
    assert "requires no identity at all" in result.detail


def test_a_backend_that_refuses_the_header_is_secure(only_file_service, monkeypatch) -> None:
    stub_direct(monkeypatch, {("backend", True): 401, ("backend", False): 401})
    assert gateway_bypass_identity(StubContext()).verdict is Verdict.SECURE


def test_a_route_the_gateway_serves_publicly_proves_nothing(only_file_service, monkeypatch) -> None:
    sent = stub_direct(monkeypatch, {("backend", True): 200, ("backend", False): 200})
    result = gateway_bypass_identity(StubContext(gateway=200))
    # Reaching a public route directly is not a bypass, so the backend is never
    # even attacked.
    assert result.verdict is Verdict.SECURE
    assert sent == []


def test_an_unavailable_backend_is_inconclusive(only_file_service, monkeypatch) -> None:
    stub_direct(monkeypatch, {("backend", True): 503, ("backend", False): 503})
    result = gateway_bypass_identity(StubContext())
    assert result.verdict is Verdict.INCONCLUSIVE
    assert "503" in result.detail


def test_a_throttled_gateway_control_is_inconclusive(only_file_service, monkeypatch) -> None:
    stub_direct(monkeypatch, {("backend", True): 200, ("backend", False): 401})
    result = gateway_bypass_identity(StubContext(gateway=429))
    assert result.verdict is Verdict.INCONCLUSIVE


def test_a_public_ingress_outranks_a_local_port(monkeypatch) -> None:
    monkeypatch.setattr(
        perimeter,
        "compose_origins",
        lambda target: [
            Origin("file-service", "http://local:8082", "docker-compose.yml ports", Severity.LOW)
        ],
    )
    monkeypatch.setattr(
        perimeter,
        "ingress_origins",
        lambda target: [Origin("file-service", "https://public", "values.yaml", Severity.CRITICAL)],
    )
    monkeypatch.setattr(perimeter, "reachable", lambda origin, timeout=3.0: True)
    stub_direct(
        monkeypatch,
        {
            ("local", True): 200,
            ("local", False): 401,
            ("public", True): 200,
            ("public", False): 401,
        },
    )
    result = gateway_bypass_identity(StubContext())
    assert result.severity is Severity.CRITICAL
    assert "https://public" in result.detail


def test_the_probe_evidence_carries_no_credential(only_file_service, monkeypatch) -> None:
    stub_direct(monkeypatch, {("backend", True): 200, ("backend", False): 401})
    result = gateway_bypass_identity(StubContext())
    rendered = " ".join(f"{e.request} {e.response_excerpt} {e.note}" for e in result.evidence)
    assert "Bearer" not in rendered and "eyJ" not in rendered


# ── the anonymous sweep ──────────────────────────────────────────────────────


@pytest.fixture
def two_routes(monkeypatch):
    monkeypatch.setattr(
        perimeter,
        "edge_routes",
        lambda: (
            [
                Route("POST", "/api/v1/auth/login", "auth-service", "AuthController.java"),
                Route("GET", "/api/v1/documents/{}", "document-service", "documents.py"),
            ],
            {},
        ),
    )


def test_the_sweep_requests_every_route_with_a_placeholder_id(two_routes) -> None:
    ctx = StubContext()
    assert gateway_bypass_identity  # the module registers both probes
    result = perimeter.anonymous_route_sweep(ctx)
    assert result.verdict is Verdict.SECURE
    assert ctx.requests == [
        ("POST", "/api/v1/auth/login"),
        ("GET", f"/api/v1/documents/{perimeter.SWEEP_ID}"),
    ]


def test_a_protected_route_served_without_a_token_is_the_finding(two_routes) -> None:
    result = perimeter.anonymous_route_sweep(StubContext(gateway=200))
    assert result.verdict is Verdict.VULNERABLE
    # login is declared public, so only the document route counts.
    assert "1 of 2 route(s)" in result.detail


def test_every_route_unavailable_is_inconclusive(two_routes) -> None:
    assert perimeter.anonymous_route_sweep(StubContext(gateway=503)).verdict is Verdict.INCONCLUSIVE


def test_an_empty_inventory_is_inconclusive(monkeypatch) -> None:
    monkeypatch.setattr(perimeter, "edge_routes", lambda: ([], {}))
    assert perimeter.anonymous_route_sweep(StubContext()).verdict is Verdict.INCONCLUSIVE
