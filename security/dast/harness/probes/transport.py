"""Configuration and transport-level attack cases (OWASP API7/API8)."""

from __future__ import annotations

from .base import Evidence, Result, Severity, Verdict, probe
from .context import ScanContext

REQUIRED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": None,
    "content-security-policy": None,
    "referrer-policy": None,
}

# HSTS is only meaningful, and only expected, on a TLS listener.
TLS_ONLY_HEADERS = {"strict-transport-security": None}


@probe(
    finding_id="DAST-MISSING-SECURITY-HEADERS",
    title="API responses omit baseline browser security headers",
    severity=Severity.MEDIUM,
    owasp="API8:2023 Security Misconfiguration",
    cwe="CWE-693",
    service="api-gateway",
    remediation=(
        "Add a security-headers middleware to the gateway stack that sets "
        "X-Content-Type-Options, X-Frame-Options, Content-Security-Policy, "
        "Referrer-Policy, and Strict-Transport-Security on every response."
    ),
    requires_identity=False,  # the headers are expected on the rejection too
)
def missing_security_headers(ctx: ScanContext) -> Result:
    self = missing_security_headers.probe
    response = ctx.get("/api/v1/documents/", identity=ctx.attacker)
    expectations = dict(REQUIRED_HEADERS)
    if ctx.base_url.startswith("https://"):
        expectations.update(TLS_ONLY_HEADERS)
    missing = []
    for header, expected in expectations.items():
        value = response.headers.get(header)
        if value is None or (expected is not None and expected not in value.lower()):
            missing.append(header)
    if missing:
        return self.result(
            Verdict.VULNERABLE,
            f"missing or weak headers: {', '.join(sorted(missing))}",
            [Evidence.from_response(response, note=f"headers seen: {sorted(response.headers)}")],
        )
    return self.result(
        Verdict.SECURE,
        "all baseline security headers present",
        [Evidence.from_response(response)],
    )


@probe(
    finding_id="DAST-CORS-ORIGIN-REFLECTION",
    title="CORS policy reflects an arbitrary origin with credentials",
    severity=Severity.HIGH,
    owasp="API8:2023 Security Misconfiguration",
    cwe="CWE-942",
    service="api-gateway",
    remediation=(
        "Only echo Access-Control-Allow-Origin for origins on the configured allowlist, and "
        "never combine a wildcard origin with Access-Control-Allow-Credentials: true."
    ),
    requires_identity=False,  # the CORS headers are on the rejection too
)
def cors_origin_reflection(ctx: ScanContext) -> Result:
    self = cors_origin_reflection.probe
    evil = "https://otterworks-attacker.example"
    response = ctx.get("/api/v1/documents/", identity=ctx.attacker, headers={"Origin": evil})
    allow_origin = response.headers.get("access-control-allow-origin", "")
    allow_creds = response.headers.get("access-control-allow-credentials", "").lower() == "true"
    evidence = [
        Evidence.from_response(
            response,
            note=f"Origin: {evil} -> Allow-Origin: {allow_origin or '(none)'}, "
            f"Allow-Credentials: {allow_creds}",
        )
    ]
    if allow_origin in (evil, "*") and allow_creds:
        return self.result(
            Verdict.VULNERABLE,
            "untrusted origin reflected alongside credentials",
            evidence,
        )
    return self.result(Verdict.SECURE, "untrusted origin was not granted access", evidence)


@probe(
    finding_id="DAST-RATE-LIMIT-BYPASS",
    title="Per-IP rate limiting is bypassable with a spoofed forwarding header",
    severity=Severity.HIGH,
    owasp="API4:2023 Unrestricted Resource Consumption",
    cwe="CWE-770",
    service="api-gateway",
    remediation=(
        "Only honour X-Forwarded-For / X-Real-IP from trusted proxy hops, and key the rate "
        "limiter on an identity the client cannot choose (authenticated subject or peer IP)."
    ),
    requires_identity=False,
)
def rate_limit_bypass(ctx: ScanContext) -> Result:
    """Burst past the limiter, then repeat the burst rotating X-Forwarded-For."""
    self = rate_limit_bypass.probe
    burst = ctx.rate_limit_burst

    limited = False
    for _ in range(burst):
        response = ctx.get("/health")
        if response.status_code == 429:
            limited = True
            break
    if not limited:
        return self.result(
            Verdict.INCONCLUSIVE,
            f"the limiter never engaged within {burst} requests; cannot test the bypass",
        )

    bypassed = 0
    last = None
    for i in range(burst):
        last = ctx.get("/health", headers={"X-Forwarded-For": f"10.9.{i // 256}.{i % 256}"})
        if last.status_code == 429:
            break
        bypassed += 1

    evidence = [Evidence.from_response(last, note=f"{bypassed} requests served after spoofing")]
    if bypassed >= burst:
        return self.result(
            Verdict.VULNERABLE,
            f"rotating X-Forwarded-For served {bypassed} requests after the limiter engaged",
            evidence,
        )
    return self.result(
        Verdict.SECURE,
        "the limiter still engaged with a spoofed forwarding header",
        evidence,
    )


@probe(
    finding_id="DAST-EXPOSED-TELEMETRY",
    title="Operational endpoints are exposed unauthenticated at the edge",
    severity=Severity.MEDIUM,
    owasp="API8:2023 Security Misconfiguration",
    cwe="CWE-497",
    service="api-gateway",
    remediation=(
        "Serve /metrics and other operational endpoints on an internal listener or behind "
        "an authenticated ingress rule rather than the public gateway."
    ),
    requires_identity=False,
)
def exposed_telemetry(ctx: ScanContext) -> Result:
    self = exposed_telemetry.probe
    evidence: list[Evidence] = []
    exposed: list[str] = []
    unavailable: list[str] = []
    for index, (path, marker) in enumerate(
        (
            ("/metrics", "go_goroutines"),
            ("/actuator/env", "propertySources"),
        )
    ):
        # A fresh forwarding address per request: the rate-limit probe runs just
        # before this one and leaves the scanner's own bucket drained.
        response = ctx.get(path, headers={"X-Forwarded-For": f"198.51.100.{index + 1}"})
        if response.status_code == 200 and marker in response.text:
            exposed.append(path)
            evidence.append(Evidence.from_response(response, note=path))
        elif response.status_code == 429 or response.status_code >= 500:
            unavailable.append(f"{path} -> {response.status_code}")
            evidence.append(Evidence.from_response(response, note=path))
    if exposed:
        return self.result(
            Verdict.VULNERABLE,
            f"unauthenticated telemetry at {', '.join(exposed)}",
            evidence,
        )
    if unavailable:
        return self.result(
            Verdict.INCONCLUSIVE,
            f"throttled or erroring, so exposure cannot be assessed: {', '.join(unavailable)}",
            evidence,
        )
    return self.result(Verdict.SECURE, "no unauthenticated telemetry endpoints found")
