---
name: local-stack-fix-verification
description: How to verify an OtterWorks service fix end-to-end on the local docker-compose stack (LocalStack S3), including building a "pre-fix" control image from the base branch so a recording shows broken-vs-fixed. Use when validating a bug fix in a backend service through the web app at :3000.
---

# Verifying a service fix on the local stack

## Bring the stack up
```bash
docker compose -f docker-compose.infra.yml up -d
docker compose -f docker-compose.infra.yml -f docker-compose.yml build      # ~10 min warm cache
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d
```
A VM snapshot whose build failed partway may have **no docker images and no volumes** — check
`docker images` / `docker volume ls` first; if empty you must build and re-seed.

## Seed the drive (needed for login)
Login with `DRIVE_EMAIL` / `DRIVE_PASSWORD` fails with "Invalid credentials" on empty volumes.
`--register` creates the account, and a reduced `--scale` seeds in ~15 s instead of several minutes:
```bash
python3 -m venv /tmp/seed && /tmp/seed/bin/pip install -r testdata/generated/retail-drive/requirements.txt
/tmp/seed/bin/python testdata/generated/retail-drive/generate_drive.py \
  --gateway http://localhost:8080 --email "$DRIVE_EMAIL" --password "$DRIVE_PASSWORD" \
  --departments all --scale 0.15 --workers 6 --register
```
Verify with `curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8080/api/v1/auth/login ...` → 200.

## Build a pre-fix control image (makes the recording conclusive)
A "it works now" clip alone can't distinguish a fix from a test that never exercised the bug.
Build the base-branch image in a worktree and run it under the compose network alias, then swap back:
```bash
git worktree add /tmp/prefix-wt <base-branch>
docker build -t otterworks-<svc>:prefix -f services/<svc>/Dockerfile services/<svc>
docker stop otterworks-<svc> && docker rm otterworks-<svc>
docker run -d --name otterworks-<svc> --network otterworks-network --network-alias <svc> \
  -p 8082:8082 <same -e env as compose> otterworks-<svc>:prefix
# restore afterwards:
docker rm -f otterworks-<svc>
docker compose -f docker-compose.infra.yml -f docker-compose.yml up -d <svc>
```
Env baked into a Dockerfile (`ENV FILE_UPLOAD_ALWAYS_FAIL=true`) reappears in the control container
even though compose no longer sets it — that's the point of building the control from the image.

## Evidence sources for file uploads
- UI: /files → **Upload** → dropzone; failure renders a red "FILE UPLOAD FAILED" banner and an
  "Upload failed" row (`components/files/file-upload-dropzone.tsx`), success just lists the file.
- Storage: `docker exec otterworks-localstack awslocal s3 ls s3://otterworks-files/files/ --recursive`
  (compare object count and byte size before/after).
- Incidents: `GET /api/v1/admin/incidents` via the gateway with a login bearer token — a failed
  upload opens `File upload failed: <name>`; a successful one must add nothing.
- Service logs: `docker logs otterworks-file-service` — look for "nonexistent bucket" / `S3 error`.
- Baked env check: `docker exec otterworks-file-service env | grep FILE_UPLOAD`.

## Devin Secrets Needed
- `DRIVE_EMAIL`, `DRIVE_PASSWORD` — web-app login / seeding.
