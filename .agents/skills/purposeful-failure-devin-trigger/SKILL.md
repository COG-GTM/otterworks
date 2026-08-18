---
name: purposeful-failure-devin-trigger
description: How to build a deliberate ("purposeful") failure point in an OtterWorks demo tenant and wire it so every occurrence of the failure creates an incident and triggers a Devin session via admin-service. Use when creating demo variants that break a service on purpose, when connecting service failures to Devin auto-triage, or when a change doesn't seem to reach a live tenant.
---

# Purposeful failure points + Devin session triggering on a tenant

This is the end-to-end recipe used for the `coggtm` demo (branch `demo-coggtm`,
tenant `https://t-coggtm.demo.otterworks.app`). Reference PRs: #78/#80 (failure
switch + banner), #82 (Dockerfile bake), #90 (alert route, dedup bypass),
#91 (CD tag fix), #92 (runtime Devin credentials).

## Ground rules

- **Never break upstream `main`** (`Cognition-Partner-Workshops/otterworks`) — it is
  the golden app and drives the perpetual `t-main` tenant. Demo variants live on a
  fork `demo-<id>` / `workshop-<id>` branch; the branch name maps to tenant `<id>`
  (`branch_tenant_id()` in `scripts/lib/tenant-common.sh`). The fork's `main` is
  non-deploying.
- **Keep failures "soft"**: never delete data or mutate real AWS resources. Redirect
  to a nonexistent resource instead, and preserve the "metadata written only after
  success" ordering so failures leave no orphan state.

## Step 1 — Build the failure switch (default OFF)

Don't rely on the transient Redis chaos flags (`chaos:<service>:<scenario>`, set
with SETEX + TTL — they expire and Redis has no persistence). Instead add a
config-level env switch that reuses the same failure mechanism:

- In file-service, `FILE_UPLOAD_ALWAYS_FAIL` (parsed in `src/config.rs`, default
  off) forces `effective_bucket` in `handlers.rs::upload_file` to the nonexistent
  bucket `otterworks-files-chaos-nonexistent`, so S3 returns `NoSuchBucket` and the
  upload 500s. The existing Redis chaos check stays intact for other scenarios.
- The switch must default off everywhere (code, docker-compose, chart values) so
  `main` and other tenants are unaffected.

## Step 2 — Get the switch ON for the tenant (the part everyone gets wrong)

Tenant deploys do NOT read the fork branch's Helm charts or deploy scripts — the
ops-dashboard runner (and upstream CD) deploy from the tree bundled in the runner
image and only take the **service images** from your branch. So:

- Editing `infrastructure/helm/**` values on the demo branch does nothing to the
  live tenant (verified the hard way — uploads kept returning 201).
- `helm --set` by hand gets wiped on the next redeploy (every push, idle-wake, reaper).
- The reliable fork-side mechanism: **bake it into the service image**:
  ```dockerfile
  # services/file-service/Dockerfile on the demo branch ONLY
  ENV FILE_UPLOAD_ALWAYS_FAIL=true
  ```
  A Dockerfile change also guarantees CD rebuilds that service (CD only rebuilds
  services whose files the push touched).

Add a visible frontend surface too if the demo needs it (e.g. the reusable
`frontend/client-app/src/components/chaos/chaos-error-banner.tsx` shown from the
upload `.catch` in `file-upload-dropzone.tsx`).

## Step 3 — Route the failure into admin-service → Devin

admin-service already owns the Devin flow: `DevinSessionService.create_session`
(reads `DEVIN_API_KEY`/`DEVIN_ORG_ID`, no-ops with a warning if missing) and the
Grafana-style webhook `POST /api/v1/admin/alerts/ingest` (auth: `X-Alert-Secret`
or `Authorization: Bearer` matching `ALERT_WEBHOOK_SECRET`; if that env var is
unset the endpoint allows unauthenticated ingest). Reuse it instead of adding a
second Devin client:

- From the failing service, fire-and-forget (`tokio::spawn`, never block or change
  the error the client receives) a Grafana-shaped alert payload to
  `http://admin-service:8089/api/v1/admin/alerts/ingest`. See
  `services/file-service/src/alerts.rs`: labels `alertname`, `severity`,
  `affected_service`, annotations summary/description, `startsAt`. Config via env
  `ADMIN_SERVICE_URL` (default `http://admin-service:8089` resolves in-namespace)
  and optional `ALERT_WEBHOOK_SECRET`. Missing config → warn and skip. Never log
  secrets.
- **Dedup**: `alerts_controller#process_alert` normally skips creating an incident
  when one is already open for the `affected_service`. To get one incident + one
  Devin session per failure, the alert carries label `"dedup": "false"`, which the
  controller honors by bypassing the skip. Devin sessions also only fire when
  `AdminSettingsService.auto_investigate_enabled?` is true (fail-open default).

## Step 4 — Devin credentials on the tenant

Nothing in the deploy scripts wires `DEVIN_API_KEY`/`DEVIN_ORG_ID` to any service,
so out of the box `DevinSessionService` no-ops on tenants.

`DevinSessionService` resolves a whole pair from the first source that has one:
`DEVIN_API_KEY` + `DEVIN_ORG_ID` env (`source: env`) → Secrets Manager
(`source: secrets_manager`) → the settings store (`source: settings`).
`GET /api/v1/admin/settings/devin_credentials?verify=true` reports which, plus
`valid` / `unreachable`.

- **Secrets Manager (preferred)**: set `DEVIN_CREDENTIALS_SECRET_ID` on
  admin-service (export it before the deploy; `tenant-common.sh` passes it
  through) pointing at a secret holding `{"api_key": ..., "org_id": ...}`, named
  `otterworks/<env>/devin-<tenant>` (e.g. `otterworks/dev/devin-coggtm`) — the
  IRSA policy in `infrastructure/terraform/main.tf` matches
  `otterworks/<env>/devin-*` in the deploying account only, so a name like
  `otterworks/dev/devin_api` gets AccessDenied. Encrypted at rest, rotatable
  without touching the tenant, cached 5 minutes in-process; a read failure keeps
  serving the last good pair for at most 15 minutes, and a deleted or
  access-denied secret drops it immediately. `secrets_manager_unusable: true` in
  the status response means the secret is wired but unreadable or malformed.
  Needs an **upstream** deploy plus `terraform apply`.
- **Runtime settings endpoint**: `PUT /api/v1/admin/settings/devin_credentials`
  (JWT-authenticated via api-gateway) verifies the pair against the Devin API
  before storing it — `422` if the API rejects it, `503` if the API is
  unreachable (retry or pass `force=true`) — then stores it in Postgres
  (`system_configs`), so it survives Redis restarts and redeploys. A pair left in
  the old Redis keys is adopted on first read. `DELETE` on the same path revokes
  it durably. Load once; no infra access needed.
- One-off with cluster access: `kubectl -n otterworks-<id> set env deploy/admin-service DEVIN_API_KEY=... DEVIN_ORG_ID=...`
  (overwritten by the next redeploy).
- GitHub Actions cannot talk to EKS: the OIDC role
  (`demo-platform/infra/terraform/iam_github_actions.tf`) has ECR push + dashboard
  passcode only, by design. Don't design workflows that run helm/kubectl from CI
  without changing that role.

## Step 5 — Verify live

1. Merge to the demo branch; CD rebuilds the touched services and redeploys the
   tenant (~3–4 min). Known pitfall: ECR tags are immutable and the CI role lacks
   `ecr:BatchDeleteImage`; #91/#92 pin deploys to the immutable `<slug>-<sha>` tag.
2. Register a throwaway user on `https://api-t-<id>.demo.otterworks.app`
   (`email`, `password`, `displayName`).
3. Trigger the failure: `POST /api/v1/files/upload` (NOT `/api/v1/files`) → expect 5xx,
   and confirm no metadata row appears while listing/downloading existing files works.
4. Repeat 2–3 times and confirm one incident per failure (admin API/dashboard), each
   with its own `devin_session_id`/`devin_session_url` once credentials are loaded.
5. Never fire real Devin sessions from local tests — use a fake key locally
   (compose wires `DEVIN_API_KEY: ${DEVIN_API_KEY:-}`, so an exported real key WILL
   create real sessions).
