"""Injection and information-disclosure attack cases (OWASP API3/API8)."""

from __future__ import annotations

import re

from .base import Evidence, Result, Severity, Verdict, probe
from .context import ScanContext

SQL_ERROR_SIGNATURES = (
    "syntax error at or near",
    "unterminated quoted string",
    "psycopg2",
    "sqlalchemy.exc",
    "org.postgresql.util.psqlexception",
    "sqlstate",
)

LEAK_SIGNATURES = (
    "traceback (most recent call last)",
    "at org.springframework",
    "goroutine 1 [running]",
    "panic: runtime error",
    "jdbc:postgresql://",
    "otterworks_dev",
)

SQLI_PAYLOADS = ("'", "1' OR '1'='1", "') OR ('a'='a", "'; SELECT pg_sleep(0) --")


@probe(
    finding_id="DAST-SQLI-ERROR-BASED",
    title="SQL error surfaced from an injected query parameter",
    severity=Severity.CRITICAL,
    owasp="API3:2023 Broken Object Property Level Authorization",
    cwe="CWE-89",
    service="search-service, document-service",
    remediation=(
        "Bind every user-supplied value as a query parameter instead of interpolating it "
        "into SQL, and return a generic 400 for malformed input."
    ),
)
def sqli_error_based(ctx: ScanContext) -> Result:
    self = sqli_error_based.probe
    targets = [
        ("/api/v1/search/", "q"),
        ("/api/v1/documents/", "title"),
        ("/api/v1/files/", "folder_id"),
    ]
    evidence: list[Evidence] = []
    for path, param in targets:
        for payload in SQLI_PAYLOADS:
            response = ctx.get(path, params={param: payload}, identity=ctx.attacker)
            body = response.text.lower()
            hit = next((sig for sig in SQL_ERROR_SIGNATURES if sig in body), None)
            if hit:
                evidence.append(
                    Evidence.from_response(response, note=f"{param}={payload!r} leaked {hit!r}")
                )
                return self.result(
                    Verdict.VULNERABLE,
                    f"{path} leaked a SQL error for {param}={payload!r}",
                    evidence,
                )
    return self.result(Verdict.SECURE, "no SQL errors surfaced from injected parameters")


@probe(
    finding_id="DAST-VERBOSE-ERRORS",
    title="Unhandled input returns a stack trace or internal connection detail",
    severity=Severity.MEDIUM,
    owasp="API8:2023 Security Misconfiguration",
    cwe="CWE-209",
    service="all",
    remediation=(
        "Return a generic JSON error envelope on unhandled exceptions and log the detail "
        "server-side; disable debug/development error pages in every deployed profile."
    ),
)
def verbose_errors(ctx: ScanContext) -> Result:
    self = verbose_errors.probe
    cases = [
        ("GET", "/api/v1/documents/not-a-uuid", None),
        ("GET", "/api/v1/files/%00", None),
        ("POST", "/api/v1/documents/", {"title": {"nested": [1, 2]}, "content": None}),
        ("GET", "/api/v1/search/?page=notanumber", None),
    ]
    evidence: list[Evidence] = []
    for method, path, body in cases:
        response = ctx.request(method, path, identity=ctx.attacker, json=body)
        lowered = response.text.lower()
        hit = next((sig for sig in LEAK_SIGNATURES if sig in lowered), None)
        if hit:
            evidence.append(Evidence.from_response(response, note=f"leaked {hit!r}"))
            return self.result(
                Verdict.VULNERABLE,
                f"{method} {path} leaked internal detail ({hit!r})",
                evidence,
            )
    return self.result(Verdict.SECURE, "malformed input produced no internal detail")


@probe(
    finding_id="DAST-STORED-XSS-DOCUMENTS",
    title="Document content is served back as renderable HTML",
    severity=Severity.HIGH,
    owasp="API8:2023 Security Misconfiguration",
    cwe="CWE-79",
    service="document-service",
    remediation=(
        "Always serve API payloads as application/json with X-Content-Type-Options: nosniff "
        "and escape user content wherever it is rendered."
    ),
)
def stored_xss_documents(ctx: ScanContext) -> Result:
    self = stored_xss_documents.probe
    payload = f"<script>alert('{ctx.run_id}')</script>"
    created = ctx.create_document(ctx.attacker, title=f"xss-{ctx.run_id}", content=payload)
    if created is None:
        return self.result(Verdict.INCONCLUSIVE, "could not create a document to test")

    response = ctx.get(f"/api/v1/documents/{created['id']}", identity=ctx.attacker)
    content_type = response.headers.get("content-type", "")
    reflected = payload in response.text
    evidence = [Evidence.from_response(response, note=f"content-type: {content_type}")]
    if reflected and "text/html" in content_type:
        return self.result(
            Verdict.VULNERABLE, "payload reflected in an HTML-typed response", evidence
        )
    return self.result(
        Verdict.SECURE, "payload only returned inside a JSON-typed response", evidence
    )


@probe(
    finding_id="DAST-CREDENTIAL-BRUTE-FORCE",
    title="Login accepts unlimited failed attempts against one account",
    severity=Severity.HIGH,
    owasp="API2:2023 Broken Authentication",
    cwe="CWE-307",
    service="auth-service",
    remediation=(
        "Track failed attempts per account and per source, and apply exponential backoff or "
        "temporary lockout after a small threshold."
    ),
)
def credential_brute_force(ctx: ScanContext) -> Result:
    self = credential_brute_force.probe
    attempts = ctx.brute_force_attempts
    statuses = []
    last = None
    # Aimed at the burner, not the victim: a target that correctly locks the
    # account must not strand the later probes that log in as the victim.
    target = ctx.burner
    for i in range(attempts):
        last = ctx.request(
            "POST",
            "/api/v1/auth/login",
            json={"email": target.email, "password": f"wrong-password-{i}"},
            headers={"X-Forwarded-For": "203.0.113.7"},
        )
        statuses.append(last.status_code)
        if last.status_code in (423, 429):
            return self.result(
                Verdict.SECURE,
                f"throttled after {i + 1} failed attempts (status {last.status_code})",
                [Evidence.from_response(last)],
            )

    still_valid = ctx.login(target.email, target.password)
    evidence = [
        Evidence.from_response(
            last,
            note=f"{attempts} failed attempts, statuses seen: {sorted(set(statuses))}",
        )
    ]
    if not still_valid:
        return self.result(
            Verdict.INCONCLUSIVE,
            "account state changed unexpectedly during the probe",
            evidence,
        )
    return self.result(
        Verdict.VULNERABLE,
        f"{attempts} consecutive failed logins were accepted without throttling or lockout",
        evidence,
    )


@probe(
    finding_id="DAST-SENSITIVE-DATA-IN-RESPONSE",
    title="Authentication responses expose sensitive user fields",
    severity=Severity.MEDIUM,
    owasp="API3:2023 Broken Object Property Level Authorization",
    cwe="CWE-213",
    service="auth-service",
    remediation=(
        "Serialize responses from an explicit allowlist DTO so credential material and "
        "internal columns can never be returned."
    ),
)
def sensitive_data_in_response(ctx: ScanContext) -> Result:
    self = sensitive_data_in_response.probe
    response = ctx.request(
        "POST",
        "/api/v1/auth/login",
        json={"email": ctx.victim.email, "password": ctx.victim.password},
    )
    if response.status_code != 200:
        return self.result(
            Verdict.INCONCLUSIVE,
            f"login returned {response.status_code}",
            [Evidence.from_response(response)],
        )
    leaked = [
        field
        for field in ("passwordHash", "password_hash", "password", "salt", "mfaSecret")
        if re.search(rf'"{field}"\s*:', response.text)
    ]
    if leaked:
        return self.result(
            Verdict.VULNERABLE,
            f"login response contained {', '.join(leaked)}",
            [Evidence.from_response(response)],
        )
    return self.result(Verdict.SECURE, "login response exposed no credential material")
