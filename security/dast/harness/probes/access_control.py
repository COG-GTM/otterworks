"""Access-control attack cases (OWASP API1/API3/API5)."""

from __future__ import annotations

import base64
import json

from .base import Evidence, Result, Severity, Verdict, probe, redact, unavailable
from .context import ScanContext


def _hit_matches(hit: object, document_id: str) -> bool:
    """Whether a search hit is the given document.

    Matched on the structured id rather than the marker text: the service returns
    the snippet from MeiliSearch's *formatted* field, which wraps every matched
    token in <em>, and MeiliSearch tokenises on the hyphens in the marker — so the
    marker never appears verbatim in a hit that contains it.
    """
    return isinstance(hit, dict) and str(hit.get("id", "")) == document_id


def _b64url(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@probe(
    finding_id="DAST-BOLA-DOCUMENTS",
    title="Broken object-level authorization on GET /api/v1/documents/{id}",
    severity=Severity.CRITICAL,
    owasp="API1:2023 Broken Object Level Authorization",
    cwe="CWE-639",
    service="document-service",
    remediation=(
        "Compare the document's owner_id against the caller identity derived from the "
        "validated JWT on every read/update/delete path, and return 403 on mismatch."
    ),
)
def bola_documents(ctx: ScanContext) -> Result:
    """Attacker reads a document owned by the victim using the attacker's own token."""
    self = bola_documents.probe
    victim_doc = ctx.victim_document()
    if victim_doc is None:
        return self.result(Verdict.INCONCLUSIVE, "could not seed a victim-owned document")

    path = f"/api/v1/documents/{victim_doc['id']}"
    response = ctx.get(path, identity=ctx.attacker)
    if response.status_code == 200 and victim_doc["title"] in response.text:
        return self.result(
            Verdict.VULNERABLE,
            "the attacker's token returned the victim's document body",
            [Evidence.from_response(response, note=f"victim document {victim_doc['id']}")],
        )
    if response.status_code in (401, 403, 404):
        # Control request: a route that rejects the owner too is not evidence
        # that authorization works.
        if not ctx.owner_can_read(path, ctx.victim):
            return self.result(
                Verdict.INCONCLUSIVE,
                f"the owner is also refused (attacker got {response.status_code}); the read path "
                "rejects every caller, so cross-tenant access cannot be assessed",
                [Evidence.from_response(response)],
            )
        return self.result(
            Verdict.SECURE,
            f"the owner can read the document but the attacker got {response.status_code}",
            [Evidence.from_response(response)],
        )
    return self.result(
        Verdict.INCONCLUSIVE,
        f"unexpected status {response.status_code}",
        [Evidence.from_response(response)],
    )


@probe(
    finding_id="DAST-IDENTITY-HEADER-SPOOF",
    title="Client-supplied X-User-ID is trusted downstream of the gateway",
    severity=Severity.CRITICAL,
    owasp="API5:2023 Broken Function Level Authorization",
    cwe="CWE-290",
    service="api-gateway",
    remediation=(
        "Strip inbound identity headers (X-User-ID and friends) in the gateway director "
        "before setting them from validated JWT claims, so a client can never inject one."
    ),
)
def identity_header_spoof(ctx: ScanContext) -> Result:
    """Attacker asserts the victim's identity via a header the gateway is supposed to own."""
    self = identity_header_spoof.probe
    victim_doc = ctx.victim_document()
    if victim_doc is None:
        return self.result(Verdict.INCONCLUSIVE, "could not seed a victim-owned document")

    path = f"/api/v1/documents/{victim_doc['id']}"
    response = ctx.get(
        path,
        identity=ctx.attacker,
        headers={"X-User-ID": ctx.victim.user_id},
    )
    if response.status_code == 200 and victim_doc["title"] in response.text:
        # Negative control: the same read without the header. If that also succeeds
        # the document service simply is not checking ownership, which belongs to
        # DAST-BOLA-DOCUMENTS — blaming the gateway here would send the fix to the
        # wrong service.
        without_header = ctx.get(path, identity=ctx.attacker)
        if without_header.status_code == 200 and victim_doc["title"] in without_header.text:
            return self.result(
                Verdict.INCONCLUSIVE,
                "the attacker reads the victim's document without the header too, so this is "
                "object-level authorization (see DAST-BOLA-DOCUMENTS), not header trust",
                [
                    Evidence.from_response(response, note=f"X-User-ID: {ctx.victim.user_id}"),
                    Evidence.from_response(without_header, note="same read, no X-User-ID"),
                ],
            )
        return self.result(
            Verdict.VULNERABLE,
            "spoofed X-User-ID header granted access to the victim's document; the same read "
            f"without it returned {without_header.status_code}",
            [
                Evidence.from_response(response, note=f"X-User-ID: {ctx.victim.user_id}"),
                Evidence.from_response(without_header, note="same read, no X-User-ID"),
            ],
        )
    if response.status_code >= 500:
        return self.result(
            Verdict.INCONCLUSIVE,
            f"the read path returned {response.status_code}; the backend is failing, so the "
            "spoof attempt proves nothing",
            [Evidence.from_response(response)],
        )
    if response.status_code not in (401, 403, 404):
        # Only an explicit refusal shows the header was not honoured. A 2xx whose
        # body does not happen to echo the title, or a redirect, is a request that
        # was served — never a pass.
        return self.result(
            Verdict.INCONCLUSIVE,
            f"the spoofed request was not refused (status {response.status_code}) but the "
            "victim's document was not recognisable in the body, so the header cannot be "
            "assessed",
            [Evidence.from_response(response, note=f"X-User-ID: {ctx.victim.user_id}")],
        )
    # Control request: a route that refuses the owner too proves nothing about
    # whether the spoofed header would have been honoured.
    if not ctx.owner_can_read(path, ctx.victim):
        return self.result(
            Verdict.INCONCLUSIVE,
            f"the owner is also refused (spoof attempt got {response.status_code}); the read "
            "path rejects every caller, so the header cannot be assessed",
            [Evidence.from_response(response)],
        )
    return self.result(
        Verdict.SECURE,
        f"the owner can read the document but the spoofed identity header could not "
        f"(status {response.status_code})",
        [Evidence.from_response(response)],
    )


@probe(
    finding_id="DAST-MASS-ASSIGNMENT-OWNER",
    title="Client-supplied owner_id lets a caller create objects in another account",
    severity=Severity.CRITICAL,
    owasp="API3:2023 Broken Object Property Level Authorization",
    cwe="CWE-915",
    service="document-service",
    remediation=(
        "Drop owner_id from the create/update request schema and always set it from the "
        "authenticated caller; if it must be accepted, reject any value other than the "
        "caller's own id."
    ),
)
def mass_assignment_owner(ctx: ScanContext) -> Result:
    """Attacker POSTs a document naming the victim as owner, using its own token."""
    self = mass_assignment_owner.probe
    response = ctx.create_document_response(
        ctx.attacker,
        title=f"planted-by-attacker-{ctx.run_id}",
        # Deliberately not ctx.victim_marker: that string belongs to the victim's
        # own document and the search probe treats any sighting of it as a leak.
        content=f"planted {ctx.plant_marker}",
        owner_id=ctx.victim.user_id,
    )
    if response.status_code not in (200, 201):
        if response.status_code >= 500:
            return self.result(
                Verdict.INCONCLUSIVE,
                f"the create path returned {response.status_code}; the backend is failing, so "
                "the refusal is not evidence of an ownership check",
                [Evidence.from_response(response)],
            )
        # Control request: the attacker creating in its own account must work,
        # or the create path is refusing everyone and proves nothing.
        # No owner_id: the remediation this probe recommends is to drop the field
        # from the schema, so a control that still sends it would be refused too.
        control = ctx.create_document_response(
            ctx.attacker,
            title=f"control-{ctx.run_id}",
            content=f"control {ctx.plant_marker}",
            allow_owner_fallback=False,
        )
        if control.status_code not in (200, 201):
            return self.result(
                Verdict.INCONCLUSIVE,
                f"the attacker's own create is also refused ({control.status_code}); the create "
                "path rejects every caller, so ownership handling cannot be assessed",
                [Evidence.from_response(response), Evidence.from_response(control)],
            )
        return self.result(
            Verdict.SECURE,
            f"the attacker can create in its own account but naming another user as owner was "
            f"refused ({response.status_code})",
            [Evidence.from_response(response)],
        )
    try:
        planted = response.json()
    except ValueError:
        return self.result(
            Verdict.INCONCLUSIVE,
            f"the create returned {response.status_code} with an unparsable body, so the "
            "resulting owner cannot be read",
            [Evidence.from_response(response)],
        )
    if str(planted.get("owner_id")) == ctx.victim.user_id:
        return self.result(
            Verdict.VULNERABLE,
            f"attacker created document {planted['id']} owned by the victim "
            f"({ctx.victim.user_id}) using only the attacker's own token",
            [
                Evidence(
                    request=f"POST {ctx.base_url}/api/v1/documents/ "
                    f'{{"owner_id": "{ctx.victim.user_id}", ...}} as attacker',
                    response_status=201,
                    # json.dumps, not str(): the redaction patterns match double-quoted
                    # JSON keys, and a Python dict repr would slip a single-quoted
                    # credential field past them. Redact before truncating.
                    response_excerpt=redact(json.dumps(planted))[:300],
                    note="owner_id in the response echoes the victim, not the caller",
                )
            ],
        )
    return self.result(
        Verdict.SECURE,
        f"owner_id was overridden to {planted.get('owner_id')} (the caller), not the victim",
    )


@probe(
    finding_id="DAST-UNSIGNED-JWT",
    title="Forged JWT accepted on a protected route",
    severity=Severity.CRITICAL,
    owasp="API2:2023 Broken Authentication",
    cwe="CWE-347",
    service="api-gateway",
    remediation=(
        "Reject tokens whose alg is not the configured HMAC algorithm and verify the "
        "signature before reading any claim."
    ),
)
def unsigned_jwt(ctx: ScanContext) -> Result:
    """Mint alg=none and alg=HS256-with-empty-signature tokens for the victim."""
    self = unsigned_jwt.probe
    claims = {
        "sub": ctx.victim.user_id,
        "user_id": ctx.victim.user_id,
        "exp": ctx.far_future,
    }
    forged = {
        "alg=none": f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(claims)}.",
        "empty-signature": f"{_b64url({'alg': 'HS256', 'typ': 'JWT'})}.{_b64url(claims)}.",
    }

    evidence: list[Evidence] = []
    for label, token in forged.items():
        response = ctx.get("/api/v1/documents/", headers={"Authorization": f"Bearer {token}"})
        evidence.append(Evidence.from_response(response, note=label))
        if response.status_code < 400:
            return self.result(Verdict.VULNERABLE, f"forged token ({label}) was accepted", evidence)
        if response.status_code >= 500:
            # The gateway rejects an invalid token with 401 before proxying, so a 5xx
            # means the request reached the backend — i.e. the token got past the
            # very check under test.
            return self.result(
                Verdict.INCONCLUSIVE,
                f"forged token ({label}) reached a failing backend (status "
                f"{response.status_code}); the gateway did not reject it outright, so the "
                "attack cannot be assessed",
                evidence,
            )
    return self.result(Verdict.SECURE, "all forged tokens were rejected", evidence)


@probe(
    finding_id="DAST-UNAUTHENTICATED-ADMIN",
    title="Administrative routes reachable without a token",
    severity=Severity.HIGH,
    owasp="API5:2023 Broken Function Level Authorization",
    cwe="CWE-306",
    service="api-gateway",
    remediation=(
        "Ensure every non-public prefix is listed as a protected route in the gateway JWT "
        "middleware, and enforce role checks in the admin service itself."
    ),
    requires_identity=False,  # the attack *is* the absence of a token
)
def unauthenticated_admin(ctx: ScanContext) -> Result:
    """Hit administrative surfaces with no Authorization header at all."""
    self = unauthenticated_admin.probe
    targets = [
        "/api/v1/admin/users",
        "/api/v1/admin/feature-flags",
        "/api/v1/audit/logs",
        "/api/v1/analytics/usage",
    ]
    evidence: list[Evidence] = []
    exposed: list[str] = []
    unreached: list[str] = []
    for path in targets:
        response = ctx.get(path)
        # A 5xx is the gateway failing to reach the backend (502/504) or an open
        # circuit breaker (503), and a 429 is the limiter — neither is the route
        # deciding to refuse an anonymous caller. admin-service crash-loops by
        # design here, so this matters.
        if unavailable(response):
            unreached.append(f"{path} -> {response.status_code}")
            continue
        evidence.append(Evidence.from_response(response, note=path))
        if response.status_code < 400:
            exposed.append(path)
    if exposed:
        return self.result(
            Verdict.VULNERABLE,
            f"reachable unauthenticated: {', '.join(exposed)}",
            evidence,
        )
    if not evidence:
        return self.result(
            Verdict.INCONCLUSIVE,
            "no administrative backend produced an auth verdict; every route was "
            f"unavailable or throttled: {', '.join(unreached)}",
        )
    return self.result(Verdict.SECURE, "all administrative routes required a token", evidence)


@probe(
    finding_id="DAST-SEARCH-TENANT-LEAK",
    title="Search results leak documents owned by another tenant",
    severity=Severity.HIGH,
    owasp="API1:2023 Broken Object Level Authorization",
    cwe="CWE-200",
    service="search-service",
    remediation=(
        "Scope every search query by the caller's owner_id derived from validated claims, "
        "never from a request-controlled parameter."
    ),
)
def search_tenant_leak(ctx: ScanContext) -> Result:
    """Attacker searches for a marker string that only exists in the victim's document."""
    self = search_tenant_leak.probe
    victim_doc = ctx.victim_document()
    if victim_doc is None:
        return self.result(Verdict.INCONCLUSIVE, "could not seed a victim-owned document")

    marker = ctx.victim_marker
    response = ctx.get("/api/v1/search/", params={"q": marker}, identity=ctx.attacker)
    if response.status_code >= 500:
        return self.result(
            Verdict.INCONCLUSIVE,
            f"search backend unavailable (status {response.status_code})",
            [Evidence.from_response(response)],
        )
    # The service echoes the query back in every response, so the verdict has to
    # come from the hits themselves rather than a substring match on the body.
    try:
        payload = response.json()
    except ValueError:
        payload = None
    hits = payload.get("results") if isinstance(payload, dict) else None
    if hits is None:
        return self.result(
            Verdict.INCONCLUSIVE,
            f"the search response (status {response.status_code}) was not a parsable result set",
            [Evidence.from_response(response)],
        )
    if any(_hit_matches(hit, victim_doc["id"]) for hit in hits):
        return self.result(
            Verdict.VULNERABLE,
            f"attacker's search returned the victim's document {victim_doc['id']}",
            [Evidence.from_response(response, note=f"marker {marker}")],
        )
    # Control request: documents are indexed asynchronously, so an empty result
    # set for the attacker means nothing until the owner can find it.
    control = ctx.search_as(ctx.victim, marker)
    if control is None or not any(_hit_matches(hit, victim_doc["id"]) for hit in control):
        return self.result(
            Verdict.INCONCLUSIVE,
            "the owner cannot find the marker either, so the index is empty or still "
            "catching up and scoping cannot be assessed",
            [Evidence.from_response(response)],
        )
    return self.result(
        Verdict.SECURE,
        "the owner finds the document but the attacker's search does not",
        [Evidence.from_response(response)],
    )
