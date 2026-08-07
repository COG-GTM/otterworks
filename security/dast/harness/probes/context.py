"""Shared scan context: target, seeded identities, and HTTP helpers.

Every probe attacks the *running* application through the API gateway, using two
real accounts registered at scan time: an ``attacker`` and a ``victim``. Both are
namespaced by ``run_id`` so concurrent scans (CI, several sessions, several
tenants) never collide.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

DEFAULT_PASSWORD = "OtterworksDast123!"


@dataclass
class Identity:
    email: str
    password: str
    user_id: str = ""
    access_token: str = ""

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}


class SeedError(RuntimeError):
    """Raised when the scan cannot establish the identities it needs."""


@dataclass
class ScanContext:
    base_url: str
    client: httpx.Client
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    rate_limit_burst: int = 200
    brute_force_attempts: int = 12
    attacker: Identity = field(init=False)
    victim: Identity = field(init=False)
    #: True when the API accepted a client-supplied owner_id on create. Probes
    #: use this to tell "authorization works" apart from "the create path needs
    #: the caller to name its own owner".
    accepts_client_owner_id: bool = field(default=False, init=False)
    _victim_document: dict[str, Any] | None = field(default=None, init=False)
    _victim_document_attempted: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.attacker = Identity(
            email=f"dast-attacker-{self.run_id}@example.test", password=DEFAULT_PASSWORD
        )
        self.victim = Identity(
            email=f"dast-victim-{self.run_id}@example.test", password=DEFAULT_PASSWORD
        )

    # ── lifecycle ────────────────────────────────────────────────────────────

    @property
    def far_future(self) -> int:
        return int(time.time()) + 3600

    @property
    def victim_marker(self) -> str:
        return f"otterworks-dast-marker-{self.run_id}"

    def wait_for_target(self, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                if self.client.get("/health").status_code < 500:
                    return
            except httpx.HTTPError as exc:
                last = exc
            time.sleep(1.0)
        raise SeedError(f"target {self.base_url} did not become reachable: {last}")

    def seed_identities(self) -> None:
        for identity in (self.attacker, self.victim):
            self._register(identity)

    def _register(self, identity: Identity) -> None:
        response = self.client.post(
            "/api/v1/auth/register",
            json={
                "email": identity.email,
                "password": identity.password,
                "displayName": f"DAST {identity.email.split('@')[0]}",
            },
        )
        if response.status_code not in (200, 201):
            raise SeedError(
                f"could not register {identity.email}: {response.status_code} {response.text[:200]}"
            )
        body = response.json()
        identity.access_token = body.get("accessToken", "")
        identity.user_id = str(body.get("user", {}).get("id", ""))
        if not identity.access_token or not identity.user_id:
            raise SeedError(f"registration for {identity.email} returned no usable identity")

    def login(self, email: str, password: str) -> bool:
        response = self.client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        return response.status_code == 200

    # ── seeded fixtures ──────────────────────────────────────────────────────

    def create_document(
        self,
        identity: Identity,
        title: str,
        content: str,
        *,
        owner_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Create a document, falling back to naming the owner explicitly.

        Some deployments reject a create whose owner cannot be derived from the
        token and ask the caller to supply owner_id instead. The fallback keeps
        the suite usable there, and records the fact for the mass-assignment
        probe to assert on.
        """
        body: dict[str, Any] = {"title": title, "content": content}
        if owner_id:
            body["owner_id"] = owner_id
        response = self.request("POST", "/api/v1/documents/", identity=identity, json=body)
        if response.status_code in (401, 403) and not owner_id:
            body["owner_id"] = identity.user_id
            response = self.request("POST", "/api/v1/documents/", identity=identity, json=body)
            if response.status_code in (200, 201):
                self.accepts_client_owner_id = True
        if response.status_code not in (200, 201):
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def victim_document(self) -> dict[str, Any] | None:
        """A document owned solely by the victim, created once per scan."""
        if not self._victim_document_attempted:
            self._victim_document_attempted = True
            self._victim_document = self.create_document(
                self.victim,
                title=f"victim-private-{self.run_id}",
                content=f"confidential {self.victim_marker}",
            )
        return self._victim_document

    # ── HTTP helpers ─────────────────────────────────────────────────────────

    def request(
        self,
        method: str,
        path: str,
        *,
        identity: Identity | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        merged = dict(identity.headers) if identity else {}
        merged.update(headers or {})
        return self.client.request(method, path, headers=merged, params=params, json=json)

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def owner_can_read(self, path: str, identity: Identity) -> bool:
        """Control request: can the legitimate owner read this object at all?

        Without this, a route that rejects *everyone* looks identical to a route
        that correctly rejects only the attacker.
        """
        return self.get(path, identity=identity).status_code == 200
