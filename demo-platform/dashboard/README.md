# OtterWorks Demo Ops Dashboard

A self-contained **Next.js 14 (App Router, TypeScript strict)** control-plane UI + API
for the OtterWorks ephemeral demo platform. It implements the API contract in
[`../docs/api-contract.md`](../docs/api-contract.md) against the DynamoDB control table
described in [`../docs/control-table-schema.md`](../docs/control-table-schema.md).

## What it does

- **Passcode auth, server-side enforced.** `POST /api/auth/login` constant-time compares
  the passcode against `DASHBOARD_PASSCODE`, sets a signed HttpOnly/Secure/SameSite=Strict
  `ow_ops_session` cookie (HMAC via `SESSION_SECRET`, ~8h), rate-limits (5 / IP / 15 min with
  backoff), and audits `login_ok`. Rejected attempts (bad passcode or 429) never get their
  own DynamoDB write: they are aggregated in memory and flushed as one `login_fail` item per
  `LOGIN_AUDIT_FLUSH_SECONDS` (default 300). Every audit item carries a `ttl`
  (`AUDIT_RETENTION_DAYS`, default 90). `middleware.ts` gates every non-login route,
  and every `/api/*` handler independently calls `requireSession()` (defense in depth).
- **Tenants.** `GET /api/tenants` joins control-table records with live cluster state
  (namespace phase, ready/total pods, per-service status) cached ~5s. Checkout / check-in /
  extend / inject / reset drive Kubernetes runner **Jobs** in the platform namespace.
- **Reaper.** `GET/PUT /api/reaper` reads/writes `CONFIG#reaper`; `GET /api/reaper/orphans`
  previews live namespaces with no matching tenant record.
- **Audit.** `GET /api/audit` returns recent events across tenants.

## Scripts

```bash
npm run dev        # local dev server
npm run build      # production build (output: standalone)
npm run start      # run the built server
npm run lint       # next lint
npm run typecheck  # tsc --noEmit
```

## Configuration

See [`.env.example`](./.env.example). In-cluster these values come from the
`demo-ops-dashboard` Secret/ConfigMap; the pod runs under the `demo-ops-dashboard`
ServiceAccount (IRSA-bound). AWS and Kubernetes clients are constructed lazily, so
`npm run build` needs no live credentials.

## Runner Jobs

Mutating actions never touch AWS/k8s from the web pod's request path beyond creating a
Kubernetes Job. Each Job (`deploy-<id>-<epoch>`, `teardown-<id>-<epoch>`, `inject-bug-<id>-<epoch>`)
runs the repo's `scripts/deploy-tenant.sh` / `teardown-tenant.sh` / `inject-bug.sh` from the
`RUNNER_IMAGE`, carrying `CONTROL_TABLE` / `TENANT_ID` / `TENANT_BRANCH` etc. as env. Secrets
are referenced via `secretKeyRef` (never placed on argv).

## Docker

Multi-stage `Dockerfile` (node:20-alpine, `output: 'standalone'`) builds a minimal runnable
image serving on port 3000.
