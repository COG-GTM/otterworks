---
name: dast-remediation
description: >
  Repo-specific mechanics for running dynamic application security testing
  against OtterWorks and remediating what it finds. Covers targets, the probe
  suite, the Makefile targets that drive the verification loop, where each
  control lives in the polyglot services, and how to revert.
---

# DAST Remediation — OtterWorks

Repo-specific mechanics behind the `!dast-remediation` Playbook. Auto-loaded
when Devin works in this repository.

## What the harness is

`security/dast/` attacks the **running** application through the API gateway,
using the repository around it — route definitions, compose ports, Helm values —
to decide what to attack. One report, one gate:

| Layer | What it covers | Where |
|---|---|---|
| Probe suite | authenticated abuse cases — cross-tenant reads, identity spoofing, mass assignment, forged tokens, brute force | `security/dast/harness/probes/` |
| Route inventory | the edge-reachable surface, parsed from each service's own route definitions | `security/dast/harness/route_inventory.py` |
| Coverage gate | the inventory vs. the requests the last scan issued — fails when a proxied route was never attacked | `security/dast/harness/dast_coverage.py` |
| OWASP ZAP baseline | unauthenticated passive sweep — headers, cookies, information leakage | `security/dast/zap/zap-baseline.conf` |

`security/dast/attack-surface.yaml` is the target spec all layers share, and
holds `coverage_exemptions` for routes the gate may leave unattacked and
`sweep_exclusions` for routes the anonymous sweep must not send because doing so
would carry out a tenant-wide operation.
`security/dast/README.md` documents adding a probe.

## Commands

```bash
make dast-list                                   # the registered attack cases
make dast-scan  DAST_TARGET=<url>                # full suite, gated by baseline.json
make dast-verify FINDING=<id> DAST_TARGET=<url>  # one probe, baseline ignored — the remediation proof
make dast-zap   DAST_TARGET=<url>                # ZAP sweep merged into the same report
make dast-baseline REASON="..."                  # accept current findings
make dast-routes                                 # the edge routes read from the services' source
make dast-coverage                               # fail if the last scan left a route unattacked
make dast-test                                   # unit-test the harness (parsers, gate, verdicts)
```

`DAST_TARGET` defaults to `http://localhost:8080`. Reports land in
`security/dast/reports/dast-report.{json,md}` (gitignored). To branch on the
result — in CI, or in a loop that stops when a finding is proven closed — call
`./security/dast/run.sh {scan|verify|coverage|routes}` instead: `make` reports
`2` for any failed recipe and would flatten these apart. Exit codes: `0`
clean, `1` findings at or above `--fail-on` (default `medium`), `2` target
unreachable or the scan accounts never registered (the authenticated probes then
attacked nothing), `3` a probe reached no verdict while verifying one finding
(`dast-verify`) — the remediation is unproven, not done — and, from `coverage`,
`4` the route inventory read no routes, so the gate measures nothing.

The anonymous sweep sends each route's real method, so it withholds
POST/PUT/PATCH/DELETE unless you set `DAST_SWEEP_UNSAFE_METHODS=1` to declare the
target yours to destroy. Set it for a stack you brought up yourself and will tear
down; do not set it because the target says `localhost` — the multi-tenant runbook
reaches a live shared tenant at `localhost:8080` via `kubectl port-forward`.

## Targets

| Target | URL | Use |
|---|---|---|
| Local stack | `http://localhost:8080` | after `make up`; the default. Add `DAST_SWEEP_UNSAFE_METHODS=1` once you know the stack is yours, not a port-forward |
| Your tenant | `https://api-t-<id>.demo.otterworks.app` | after `scripts/deploy-tenant.sh <id>` |
| Perpetual tenant | `https://api-t-main.otterworks.app` | tracks `main`; never scan it — it is never reaped, so the accounts and documents a scan writes stay forever |

Always scan through the gateway on port 8080 — hitting a backend port directly
bypasses the controls under test. The exception is
`DAST-GATEWAY-BYPASS-IDENTITY`, whose question *is* whether such an origin
exists: it attacks only origins `docker-compose.yml` or a backend chart's
`ingress.enabled` declares, and grades a published compose port lower than a
chart that puts the backend on the public ingress.

Never scan a tenant someone else is presenting from: each scan registers
accounts and writes documents into the target's database.

`DAST-RATE-LIMIT-BYPASS` also puts real load on the cluster — two bursts of
1500 requests at 64-way concurrency — and every tenant shares one ingress
controller and node group. While others are presenting, turn it down with
`OTTERWORKS_DAST_RATE_LIMIT_BURST=300 OTTERWORKS_DAST_RATE_LIMIT_WORKERS=16`
(the probe reports `inconclusive`, not `secure`, if the smaller burst can no
longer distinguish a bypass).

The local Java builds (`auth-service`, `notification-service`) pull from Maven
Central; if that is rate-limited in your environment, scan a deployed tenant
instead of the local stack.

## Where each control lives

| Control | Service | File |
|---|---|---|
| JWT validation, public/protected path lists | api-gateway (Go) | `services/api-gateway/internal/middleware/jwt.go` |
| Identity forwarding to backends (`X-User-ID`) | api-gateway (Go) | `services/api-gateway/internal/proxy/router.go` (`proxy.Director`) |
| Global middleware stack (where a new one is registered) | api-gateway (Go) | `services/api-gateway/cmd/server/main.go` |
| CORS allowlist | api-gateway (Go) | `services/api-gateway/internal/middleware/cors.go` |
| Per-IP rate limiting | api-gateway (Go) | `services/api-gateway/internal/middleware/ratelimit.go` |
| Login, tokens, password handling | auth-service (Java) | `services/auth-service/src/main/java/...` |
| Document ownership checks, request schemas | document-service (Python) | `services/document-service/app/api/documents.py`, `app/schemas/document.py` |
| Search tenant scoping | search-service (Python) | `services/search-service/app/api/search.py`, `app/middleware/auth.py` |
| File ownership checks | file-service (Rust) | `services/file-service/src/handlers.rs` |
| Network policies | platform | `security/policies/` |

An edge control (headers, CORS, rate limiting, identity forwarding) belongs in
the gateway middleware stack — registering it in `main.go` fixes it for all 11
backends at once. An object-ownership control belongs in the owning service;
the gateway cannot know which rows belong to whom.

## Fixing and proving

1. Reproduce: `make dast-scan DAST_TARGET=<url>` and read
   `security/dast/reports/dast-report.md` for the request/response evidence.
2. Fix in the owning service (table above).
3. Redeploy the target so the fix is actually running:
   - local — `docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d --build <service>`
   - tenant — build and push the image, then
     `scripts/deploy-tenant.sh <id> --image-tag <tag>` (or
     `BUG_IMAGE_TAG_<service_with_underscores>=<tag>`)
4. Prove the finding is closed: `make dast-verify FINDING=<id> DAST_TARGET=<url>`.
5. Prove nothing regressed: `make dast-scan` plus the service's own tests
   (`cd services/api-gateway && go test ./...`, `cd services/document-service && pytest`,
   `make test-api-flows`).
6. If the fix added or moved a route, `make dast-coverage` — a new endpoint is
   swept anonymously the moment it is declared, but nothing attacks it as a
   logged-in caller until a probe does. Coverage is graded from a full
   `make dast-scan` (step 5): a `dast-verify` run marks its report `partial`,
   and the gate refuses to grade one rather than calling the surface unattacked.

A finding is only closed when the probe that reproduced it reports `secure`
against a target running the new code.

## Verdicts

- `vulnerable` — the attack worked; evidence is in the report.
- `secure` — the attack failed **and** the control request confirms the
  legitimate caller still succeeds.
- `inconclusive` — no verdict possible (backend down, precondition unmet). Not
  a pass. Investigate the target before rerunning; a route that rejects the
  owner as well as the attacker is `inconclusive`, not `secure`.

## Golden-app policy

`main` is the durable before-state. Do **not** commit remediations that erase
the findings this harness demonstrates — fixes land on a branch and its PR.
Planted bugs (see `AGENTS.md`) stay in place. Adding a probe to
`security/dast/harness/probes/` is always welcome on `main`.

`DAST-GATEWAY-BYPASS-IDENTITY` reproduces against the local stack because
`docker-compose.yml` publishes backend ports — that is a development
convenience, not something to "fix" by unpublishing them, which would break
local development. It is graded `low` from that origin for exactly that reason;
the deployment-relevant half is each backend chart's `ingress.enabled`.

## Revert

The harness only writes to `security/dast/reports/` (gitignored) plus the
accounts and documents it creates in the target. To clean up: tear the local
stack down with `make down`, or let the tenant reaper collect the namespace
(`scripts/teardown-tenant.sh <id>` to do it now).
