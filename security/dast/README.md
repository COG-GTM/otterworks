# DAST — dynamic application security testing

Static analysis reads the code. **DAST attacks the running application.** This
directory holds the runtime security controls for OtterWorks: a suite of
authenticated attack probes plus an OWASP ZAP sweep, both aimed at a deployed
API gateway, and a gate that turns their output into a pass/fail signal.

```
security/dast/
├── attack-surface.yaml     the target spec: routes, who may call them, what must never leak
├── baseline.json           accepted findings — an entry here suppresses the gate
├── harness/
│   ├── dast_scan.py        orchestrator: seed identities, run probes, merge ZAP, gate, report
│   └── probes/             one module per attack category; each probe is one abuse case
├── zap/zap-baseline.conf   ZAP passive-rule tuning for the broad sweep
└── reports/                generated dast-report.{json,md} (gitignored)
```

## Why probes and not only a scanner

A crawler such as ZAP is excellent at the unauthenticated surface — headers,
cookies, information leakage — and terrible at "user A must not read user B's
document", because it does not know who A and B are or which object belongs to
whom. The probe suite fills that gap: each probe registers two real accounts at
scan time, seeds an object owned by the *victim*, and then attacks it as the
*attacker*. Both layers feed the same report and the same gate.

## The verification loop

Each probe returns one of `vulnerable` / `secure` / `inconclusive`.

- `vulnerable` is a **reproduction** — the harness performed the attack and
  captured the request and response that prove it worked.
- `secure` after a code change is **proof the finding is closed**, produced by
  the same attack that reproduced it.
- `inconclusive` means the probe could not reach a verdict (backend down,
  precondition unmet). It never silently passes.

```
make dast-scan                                  # reproduce: which attacks work today?
   ... fix the service code ...
make dast-verify FINDING=DAST-RATE-LIMIT-BYPASS # prove that one finding is closed
make dast-scan                                  # prove nothing else regressed
make test-api-flows                             # prove the fix did not break behavior
```

`dast-verify` deliberately ignores `baseline.json`, so an accepted finding
cannot mask its own remediation check.

## Running it

```bash
# against the local docker-compose stack
make up
make dast-scan

# against a tenant or preview environment
make dast-scan DAST_TARGET=https://api-t-<id>.demo.otterworks.app

# list the attack cases
make dast-list

# one probe only, with baseline suppression off
make dast-verify FINDING=DAST-MISSING-SECURITY-HEADERS DAST_TARGET=...

# add the ZAP passive sweep and merge it into the same report
make dast-zap DAST_TARGET=...
```

Exit codes: `0` clean, `1` findings at or above `--fail-on` (default `medium`),
`2` target unreachable or misconfigured.

## Scanning safely

- Always scan **through the gateway**. Hitting a backend port directly bypasses
  the very controls under test and produces findings that do not exist at the
  deployed edge.
- Scan a **tenant namespace or the local stack**, never a namespace someone else
  is presenting from. Every scan registers accounts and writes documents; those
  live in the target's database until the tenant is reaped.
- Identities and seeded objects are namespaced by a per-run id, so concurrent
  scans (CI, several sessions, several tenants) do not collide.

## The baseline

`baseline.json` lists findings that are knowingly accepted. An entry suppresses
the gate for that finding ID and needs a `reason`; it is expected to be
temporary. CI uses it to gate on *newly introduced* findings without turning
red on known ones.

```bash
make dast-baseline REASON="tracked in the runtime hardening epic"
```

## Adding a probe

Add a function to a module in `harness/probes/`, decorated with `@probe(...)`:

```python
@probe(
    finding_id="DAST-MY-ATTACK",
    title="...", severity=Severity.HIGH,
    owasp="API5:2023 Broken Function Level Authorization",
    cwe="CWE-306", service="api-gateway",
    remediation="what the fix must do",
)
def my_attack(ctx: ScanContext) -> Result:
    response = ctx.get("/api/v1/thing", identity=ctx.attacker)
    ...
    return my_attack.probe.result(Verdict.VULNERABLE, "why", [Evidence.from_response(response)])
```

Rules of thumb: one abuse case per probe; a stable `finding_id` (it is the gate
key and the `dast-verify` handle); always attach the request/response evidence;
return `INCONCLUSIVE` rather than guessing when the precondition is missing.

Pass `requires_identity=False` only for probes that attack the *unauthenticated*
surface. Everything else is skipped as `inconclusive` when identity seeding
fails, so an unauthenticated `401` can never be read as a passing attack.

The same principle applies inside a probe: before reporting `secure` off a
refusal, make a **control request** proving the legitimate caller still
succeeds. A route that refuses everyone is not a route that is protecting
anything, and a 5xx or a `429` is a broken or throttled backend, not a control.
