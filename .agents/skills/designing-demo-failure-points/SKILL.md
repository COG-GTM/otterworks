---
name: designing-demo-failure-points
description: Design pattern for adding a new intentional AWS/service failure point to OtterWorks for demos - picking the failure, building the switch, making it click-triggered and tenant-scoped, surfacing it in the UI, wiring the alert/Slack path, keeping the app demoable, and the test matrix. Use when asked to add a new intentional error, chaos scenario, or demo failure mode. For the deploy/Devin-trigger mechanics, also use purposeful-failure-devin-trigger.
---

# Designing a new intentional failure point for demos

Reference implementations: the S3 upload failure (`FILE_UPLOAD_ALWAYS_FAIL`, PRs
#78–#92) and the SNS share-notification failure (`FILE_SHARE_EVENT_ALWAYS_FAIL`,
PR #209). Companion skill `purposeful-failure-devin-trigger` covers how the
switch reaches a live tenant and how incidents spawn Devin sessions — read both.

## 1. Pick the failure point

- Each demo failure should showcase a **different AWS service / architectural
  layer** than existing ones (S3 = storage, SNS = eventing/producer,
  SQS consumer = background processing). Check `scripts/bug-catalog.yaml` for
  what already exists.
- Make the AWS error **real, not simulated**: redirect the operation to a
  real-looking but nonexistent resource (bucket/topic/queue named
  `<real-name>-chaos-nonexistent`) so AWS/LocalStack itself returns the error
  (`NoSuchBucket`, `NotFound: Topic does not exist`, `QueueDoesNotExist`).
  Never delete or mutate real shared AWS resources, and never create new ones.
- Prefer a **click-triggered** failure (upload, share, etc.): the audience sees
  cause → red banner → Slack alert in seconds. Background failures (consumer
  polling) are fine as a durable "on-call" story but have no visible trigger.
- Constraint to remember: SNS/SQS eventing is **disabled on live tenants**
  (shared-queue isolation), so consumer-side failures only demo on the local
  compose stack; producer-side failures (publish to a nonexistent topic) work
  anywhere.

## 2. Build the switch

- One env var per failure, `<SERVICE>_<THING>_ALWAYS_FAIL`, parsed in the
  service's config (`parse_bool_env(..., false)`), **default off** in the code
  default and `docker-compose.yml` (`${VAR:-false}`). Chart values follow the
  branch: off on the golden app, but on a demo-variant branch keep them in
  agreement with the image ENVs (see the `FILE_UPLOAD_ALWAYS_FAIL` comment in
  `infrastructure/helm/file-service/values.yaml`) so the two never contradict —
  meaning any tenant deployed *from that checkout* inherits the failure.
- Don't use the Redis chaos flags for demos that must survive restarts — they
  expire. Bake `ENV VAR=true` into the service Dockerfile **on the demo branch
  only** (this is also what forces CD to rebuild that service's image).
- Scope the failure narrowly: only the targeted operation uses the chaos
  resource (e.g. only `file_shared` publishes to the failing topic; all other
  events keep the real one).
- Keep failures "soft": preserve write ordering so a failed operation leaves no
  orphan state, or (share-style) persist the record and fail only the
  notification step — decide which story you want and document it.

## 3. Surface it in the UI

- Show a red, `role="alert"` banner in the triggering component with a concise,
  AWS-flavored message ("Sharing failed. AWS SNS error: ... NotFound: Topic
  does not exist"). Extract only the AWS error `code(): message()` via
  `ProvideErrorMetadata` — never leak raw SDK debug dumps.
- Only prefix "AWS" for backend error categories that are actually AWS
  (`event_error`, `storage_error`), not validation errors.
- Return the HTTP error to the caller **only when the switch is on**; with the
  switch off, event-publish failures stay fire-and-forget so real deployments
  never surface a 500 for a persisted operation.
- Exclude adjacent flows that share the endpoint (e.g. permission updates go
  through the share endpoint — they must not hit the forced failure).
- Invalidate/refresh client queries in `finally` so persisted-but-failed
  operations still render consistent state.

## 4. Wire the alert (same pipeline every time)

- From the failing service, fire-and-forget a Grafana-shaped payload to
  `${ADMIN_SERVICE_URL}/api/v1/admin/alerts/ingest` (see
  `services/file-service/src/alerts.rs`). Distinct `alertname` per failure
  point, `severity: critical`, `affected_service`, and `"dedup": "false"` so
  every click creates its own incident + Slack message.
- Attribute the click: pass the acting user's email (api-gateway injects
  `X-User-Email`) as the `reporter_email` label — Slack @-mentions the user via
  `SLACK_USER_MAP`/lookup, falling back to plain email or `SLACK_ONCALL_MEMBER`.
- Make repeated clicks re-fire: when the switch is on, attempt the failing
  operation on every trigger (including re-shares), so the demo is repeatable.

## 5. Keep the app demoable

Failures compound: if uploads always fail, there is nothing to share. Seed
deterministic phony data so every failure remains reachable — see
`services/file-service/src/seed.rs` (`FILE_SEED_DEMO_DOCS`): seed only when the
user's listing is empty, use UUIDv5 ids derived from owner+name so concurrent
seeding is idempotent, write via the normal (non-chaos) storage path, and never
fail the caller.

## 6. Add injector support

Add a scenario to `scripts/bug-catalog.yaml` and a handler in
`scripts/inject-bug.sh` so the failure can also be toggled per-tenant at
runtime (config override + rollout restart) without a redeploy.

## 7. Test matrix (local compose, never live without approval)

```bash
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d --build <service>
```

With all demo switches ON (the tenant image config):
1. trigger via the UI click → red banner with the concise AWS error;
2. incident on the admin dashboard + Slack message in #automated-alerts,
   attributed to the clicking user;
3. repeat the click → a second incident/alert;
4. any seeded data present and other flows still usable.

With all switches OFF (golden behavior): no seeding, operation succeeds with
the normal toast, no incident, and no duplicate notifications on re-tries.

Never push `demo-*`/`workshop-*` branches or merge to the fork's `main` without
explicit user approval — both trigger tenant deploys. Never export a real
`DEVIN_API_KEY` in local tests.
