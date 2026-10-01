---
name: testing-slack-alert-flow
description: How to test OtterWorks' failed-upload → admin-service → Slack alert pipeline on a local docker-compose stack, including inducing upload failures, wiring the Slack bot token, and reading the resulting alert/incident.
---

# Testing the Slack upload-failure alert flow locally

## Stack setup
- `make infra-up && make up` (web-app :3000, admin-dashboard :4200, api-gateway :8080).
- To exercise real Slack delivery, bind `SLACK_BOT_TOKEN` (org secret) into the environment of the
  shell that runs `docker compose ... up` — docker-compose.yml passes
  `SLACK_BOT_TOKEN/SLACK_WEBHOOK_URL/SLACK_USER_MAP/SLACK_ONCALL_MEMBER` through to admin-service.
  Leave `SLACK_USER_MAP` unset to exercise the dynamic `users.lookupByEmail` path.
- Verify inside the container: `docker exec otterworks-admin-service sh -c 'test -n "$SLACK_BOT_TOKEN" && echo TOKEN_SET'`.

## Inducing an upload failure
- Redis chaos flag (no rebuild, instant): `docker exec otterworks-redis redis-cli SET chaos:file-service:upload_s3_error 1`
  (DEL to clear). file-service then targets a nonexistent S3 bucket → 500 storage_error.
- Same flag is what the admin dashboard's "Break File Uploads" demo control sets (with a 10-min TTL).
- Upload-failure alerts carry `dedup=false`, so every failed upload opens a new incident and a
  new Slack message (unlike Grafana-ingested alerts, which dedupe against an open incident for
  the same service) — safe to repeat for multiple test runs.

## Users / logins
- Web app registration is open at http://localhost:3000/register (min 8-char password).
  The JWT `email` claim of the logged-in user is what reaches the alert as `labels.reporter_email`
  (api-gateway injects `X-User-Email` from the JWT and strips any client-supplied value).
- Admin dashboard (localhost:4200) login: `admin@otterworks.dev` / `Admin123!`
  (seeded by auth-service migration V1). Incidents page: /incidents.

## Verifying a *successful* upload (e.g. after fixing an upload bug)
- UI path: http://localhost:3000/files → blue **Upload** button → the dropzone appears above the
  folder grid → click it to open the native GTK file chooser → double-click the file.
- The web-app file grid is paginated/ordered server-side, so a freshly uploaded root-level file
  may NOT show up on /files or /recent even after a refresh. Use the **Search** page instead
  (type the exact filename and press Enter — the search box is debounced and fuzzy, so a short
  prefix like "probe" matches unrelated "Process" docs). Search results link to
  `/files/<id>`, which has a working **Download** button.
- Ground truth for the storage write:
  `docker exec otterworks-localstack awslocal s3 ls s3://otterworks-files --recursive | grep <file_id>`
  (the S3 key is `files/<owner_id>/<file_id>`, not the filename).
- HTTP status + bucket used: `docker logs otterworks-file-service` prints
  `Uploaded object to S3 {key, bucket}` and `Request completed ... status 201`.
- Downloads land in ~/Downloads named after the file id (no extension); compare `md5sum` with
  the source file to prove byte-for-byte round-trip.
- Injecting env overrides for a single service without a rebuild:
  `docker compose -f docker-compose.infra.yml -f docker-compose.yml -f /tmp/override.yml up -d --no-deps file-service`
  (both base compose files are required; docker-compose.yml alone fails with
  "depends on undefined service redis"). Re-run without the override file to revert.

## Verifying the Slack side
- Alerts go to #automated-alerts (as of 2026-08: channel id C0ALNRR4PSQ, team "Cog GTM [DEMO]";
  re-resolve via the Slack tool if the workspace changes). The Devin Slack
  tool can read this channel's history directly — easier than conversations.history with the bot
  token (bot scopes are only chat:write, users:read, users:read.email).
- A resolved reporter renders as `<@MEMBERID>` in the second *On-Call* field; unresolvable emails
  render as the plain email and admin-service logs
  `Slack users.lookupByEmail failed: users_not_found` (visible via `docker logs otterworks-admin-service`).
- Example (as of 2026-08): preston.pressoir@cognition.ai resolves to Slack member U0B6ZD08Q3W.

## Devin session link in alerts
- Requires both `DEVIN_API_KEY`/`DEVIN_ORG_ID` bound into admin-service's env AND auto-investigate
  enabled in admin settings (`AdminSettingsService.auto_investigate_enabled?`, default on); otherwise the
  alert shows ":robot_face: No Devin session" and the incident shows a "Launch Devin" button —
  that is normal, not a failure. Binding the real key spawns real Devin sessions per alert, so
  avoid it unless the test requires it.

## Devin Secrets Needed
- `SLACK_BOT_TOKEN` (xoxb-, scopes chat:write, users:read, users:read.email)
- Optional: `DEVIN_API_KEY`, `DEVIN_ORG_ID` for the session-spawn path.
