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
- Alternative (needs a rollout): point file-service at a bucket that does not exist, e.g.
  `S3_BUCKET=otterworks-does-not-exist` in the compose env (the `file-bad-bucket` scenario).
- Upload-failure alerts carry `dedup=false`, so every failed upload opens a new incident and a
  new Slack message (unlike Grafana-ingested alerts, which dedupe against an open incident for
  the same service) — safe to repeat for multiple test runs.

## Users / logins
- Web app registration is open at http://localhost:3000/register (min 8-char password).
  The JWT `email` claim of the logged-in user is what reaches the alert as `labels.reporter_email`
  (api-gateway injects `X-User-Email` from the JWT and strips any client-supplied value).
- Admin dashboard (localhost:4200) login: `admin@otterworks.dev` / `Admin123!`
  (seeded by auth-service migration V1). Incidents page: /incidents.

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
