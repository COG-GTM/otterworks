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
│   ├── route_inventory.py  the edge-reachable route list, read from the services' source
│   ├── dast_coverage.py    coverage gate: the inventory vs. the requests the scan issued
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

## What the source buys the scan

Three of the controls here exist because the harness lives *in the repository*
rather than being pointed at a URL:

- **`route_inventory.py`** reads the gateway's route table
  (`api-gateway/internal/config/config.go`) and each service's own route
  definitions — FastAPI, Flask, Actix, Spring and Ktor — and produces the list of
  endpoints reachable at the edge. A crawler can only find what something links
  to; this finds what exists. `make dast-routes` prints it.
- **`DAST-ANONYMOUS-ROUTE-SWEEP`** attacks that whole list with no credentials.
  A route added tomorrow is attacked the day it lands, without anyone writing a
  probe for it. It sends each route's own method, so a route that turns out to
  be unauthenticated is also *performed*: routes that act on the whole tenant
  are listed under `sweep_exclusions` in `attack-surface.yaml` and left to a
  hand-written probe, and the coverage gate reports them with that reason.
- **`make dast-coverage`** diffs the inventory against the requests the last
  scan actually issued (recorded in `dast-report.json`), so "attacked and held"
  and "never attacked" stop looking the same in a green report. It reports three
  depths: *reached* by any probe, *attacked by a written probe*, and *attacked
  as a logged-in caller*. Only the first is gated, and it is the weakest of the
  three: within one scan the sweep walks the same inventory the gate reads, so
  the gate's teeth are the remainder — routes excluded from the sweep, routes it
  could not deliver, and routes added since the report being graded was written.
  The lower two numbers are what says how deep the suite goes.
- **`DAST-GATEWAY-BYPASS-IDENTITY`** reads `docker-compose.yml` port mappings
  and each backend chart's `ingress.enabled`, then attacks whatever origin those
  declare. Identity here is a header the gateway forwards, so any origin that
  reaches a backend directly is an unauthenticated impersonation endpoint — and
  it is not linked from anywhere the gateway serves, so a scanner aimed at the
  deployed URL has no way to reach it. Severity follows the origin: a published
  compose port is a developer's own host, a chart that publishes its own ingress
  is the public internet.

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
make dast-coverage                              # did the scan actually touch every route?
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

# list the edge-reachable routes read from the services' source
make dast-routes

# fail if the last scan left a proxied route unattacked
make dast-coverage

# one probe only, with baseline suppression off
make dast-verify FINDING=DAST-MISSING-SECURITY-HEADERS DAST_TARGET=...

# add the ZAP passive sweep and merge it into the same report
make dast-zap DAST_TARGET=...
```

The make targets are for people; anything that *branches* on the result should
call `./security/dast/run.sh {scan|verify|coverage|routes}`, which passes the
harness's exit code through. `make` reports `2` for any failed recipe whatever
the command returned, which would flatten the distinctions below.

Exit codes: `0` clean, `1` findings at or above `--fail-on` (default `medium`),
`2` target unreachable or misconfigured — including a run whose scan accounts
never registered, since the authenticated probes then attacked nothing — `3`
nothing gating but a probe could not reach a verdict. `3` applies when a single
finding is being verified
(`--only`, i.e. `make dast-verify`) or with `--fail-on-inconclusive`: a
remediation is proven by an attack that ran and failed, so "could not tell"
must not exit clean.

## Scanning safely

- Always scan **through the gateway**. Hitting a backend port directly bypasses
  the very controls under test and produces findings that do not exist at the
  deployed edge. The one exception is `DAST-GATEWAY-BYPASS-IDENTITY`, whose
  whole question is whether such an origin exists. Even then it stays inside the
  target you named: a compose port only counts for a local target, and a chart
  hostname only when the target covers it. To reach a chart host the target does
  not cover, name it yourself in `DAST_ALLOW_ORIGIN_HOSTS`.
- Scan a **tenant namespace or the local stack**, never a namespace someone else
  is presenting from. Every scan registers accounts and writes documents; those
  live in the target's database until the tenant is reaped.
- Identities and seeded objects are namespaced by a per-run id, so concurrent
  scans (CI, several sessions, several tenants) do not collide.
- `DAST-RATE-LIMIT-BYPASS` is a load generator: two bursts of
  `OTTERWORKS_DAST_RATE_LIMIT_BURST` (default 1500) requests at
  `OTTERWORKS_DAST_RATE_LIMIT_WORKERS` (default 64) concurrency. A tenant's data
  is its own, but the ingress controller and the node group are shared with
  every other tenant, so turn the burst down (or scan locally) while someone
  else is presenting:

  ```bash
  OTTERWORKS_DAST_RATE_LIMIT_BURST=300 OTTERWORKS_DAST_RATE_LIMIT_WORKERS=16 \
    make dast-scan DAST_TARGET=https://api-t-<id>.demo.otterworks.app
  ```

  A smaller burst may no longer separate a bypass from a generous allowance, in
  which case the probe says so and reports `inconclusive` rather than passing.

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
