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

`security/dast/` attacks the **running** application through the API gateway.
Two layers, one report, one gate:

| Layer | What it covers | Where |
|---|---|---|
| Probe suite | authenticated abuse cases — cross-tenant reads, identity spoofing, mass assignment, forged tokens, brute force | `security/dast/harness/probes/` |
| OWASP ZAP baseline | unauthenticated passive sweep — headers, cookies, information leakage | `security/dast/zap/zap-baseline.conf` |

`security/dast/attack-surface.yaml` is the target spec both layers share.
`security/dast/README.md` documents adding a probe.

## Commands

```bash
make dast-list                                   # the registered attack cases
make dast-scan  DAST_TARGET=<url>                # full suite, gated by baseline.json
make dast-verify FINDING=<id> DAST_TARGET=<url>  # one probe, baseline ignored — the remediation proof
make dast-zap   DAST_TARGET=<url>                # ZAP sweep merged into the same report
make dast-baseline REASON="..."                  # accept current findings
```

`DAST_TARGET` defaults to `http://localhost:8080`. Reports land in
`security/dast/reports/dast-report.{json,md}` (gitignored). Exit codes: `0`
clean, `1` findings at or above `--fail-on` (default `medium`), `2` target
unreachable, `3` a probe reached no verdict while verifying one finding
(`dast-verify`) — the remediation is unproven, not done.

## Targets

| Target | URL | Use |
|---|---|---|
| Local stack | `http://localhost:8080` | after `make up`; the default |
| Your tenant | `https://api-t-<id>.demo.otterworks.app` | after `scripts/deploy-tenant.sh <id>` |
| Perpetual tenant | `https://api-t-main.otterworks.app` | tracks `main`; never scan it — it is never reaped, so the accounts and documents a scan writes stay forever |

Always scan through the gateway on port 8080 — hitting a backend port directly
bypasses the controls under test. Never scan a tenant someone else is
presenting from: each scan registers accounts and writes documents into the
target's database.

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

## Revert

The harness only writes to `security/dast/reports/` (gitignored) plus the
accounts and documents it creates in the target. To clean up: tear the local
stack down with `make down`, or let the tenant reaper collect the namespace
(`scripts/teardown-tenant.sh <id>` to do it now).
