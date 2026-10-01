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
- Alternative (blunter — breaks downloads/previews too, so prefer the chaos flag): set
  `S3_BUCKET=otterworks-does-not-exist` for file-service in docker-compose.yml and restart it
  locally, or on a k8s tenant `scripts/inject-bug.sh <id> file-bad-bucket`.
- Upload-failure alerts carry `dedup=false`, so every failed upload opens a new incident and a
  new Slack message (unlike Grafana-ingested alerts, which dedupe against an open incident for
  the same service) — safe to repeat for multiple test runs.

## Users / logins
- Web app registration is open at http://localhost:3000/register (min 8-char password).
  The JWT `email` claim of the logged-in user is what reaches the alert as `labels.reporter_email`
  (api-gateway injects `X-User-Email` from the JWT and strips any client-supplied value).
- Admin dashboard (localhost:4200) login: `admin@otterworks.dev` / `Admin123!`
  (seeded by auth-service migration V1). Incidents page: /incidents.

## Driving an upload from the web UI (browser testing)
- /files → "Upload" button (top right) reveals the dropzone; click the dropzone to open Chrome's
  native file chooser, then `ctrl+l` and type the absolute host path + Enter to select the file.
- Success state: green "Upload complete — closing shortly" row that AUTO-DISMISSES after ~3s —
  screenshot within ~1s of selecting the file or you will miss it. Failure state: red
  "FILE UPLOAD FAILED" banner that persists with a Retry button.
- Do NOT press `ctrl+w` to close an extra tab: with a single tab it kills Chrome and drops the
  session (re-login needed). Use the tab's X or navigate back instead.
- Verify the object really landed in the configured bucket:
  `docker exec otterworks-localstack awslocal s3 ls s3://otterworks-files --recursive | wc -l`
  before/after, plus `docker logs otterworks-file-service | grep "File uploaded"` (status 201).
  The file-detail Preview/Download URL is a presigned localstack URL that visibly contains the
  bucket name — good screenshot evidence that uploads are not going to a chaos bucket.
- Good adversarial pairing for "upload works again" fixes: run the happy path, then SET the
  Redis chaos flag and re-upload to prove the UI still surfaces 500s, then DEL and re-upload.
- Admin dashboard login also accepts any email + non-empty password (client-side mock) at
  localhost:4200; each failed upload creates a new "File upload failed: <name>" incident with a
  timestamp — compare timestamps to attribute incidents to intentional vs unexpected failures.

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
