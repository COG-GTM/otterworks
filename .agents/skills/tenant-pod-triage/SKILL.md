---
name: tenant-pod-triage
description: How to triage a demo-tenant service that will not go ready - crash-loops, stale images, probe kills, DB wiring. Covers the ops-dashboard API for pod state, verifying the CI build -> ECR tag -> node imageID chain, the runner's bundled-tree limitation, and which fixes must be baked into the image vs patched with kubectl. Use whenever a tenant shows fewer ready pods than expected and the cause is not obvious.
---

# Triaging a tenant service that won't go ready

Session AWS creds are the `de-demo-provisioner` user: **no EKS/kubectl access**, and no
ECR reads. Everything below works within that, except where marked *(ask a human with
kubectl)*.

## 1. Read live pod state through the ops dashboard API

`tenant.sh status <id>` only prints ready counts. The dashboard API gives per-pod detail:

```bash
export AWS_REGION=us-east-1
JAR=$(mktemp)
PASS=$(aws secretsmanager get-secret-value --secret-id otterworks/dev/dashboard/passcode \
  --query SecretString --output text)
PASSCODE="$PASS" jq -nc '{passcode: env.PASSCODE}' | curl -s -c "$JAR" \
  -X POST https://ops.otterworks.app/api/auth/login \
  -H 'content-type: application/json' --data-binary @-
curl -s -b "$JAR" https://ops.otterworks.app/api/tenants/<id> | jq '{
  status, live, pods: [.pods[] | {name, phase, ready, restarts}]}'
rm -f "$JAR"   # session cookie lives in the jar; don't leave it behind
```

The record's `.logs` field is the latest runner Job's deploy log — it shows which image
tag each service resolved (`Deploying admin-service (tag ...)`) and a `kubectl get pods`
snapshot. Pod **logs/events are not exposed**; for those, ask a human to run
`kubectl -n otterworks-<id> logs <pod> --previous --tail=40` and
`kubectl -n otterworks-<id> describe pod <pod> | tail -25`.

Two pods for one service = a stuck rollout: old ReplicaSet pod + new one that never went
ready. Rising `restarts` with `phase: Running` = crash loop or probe kills.

## 2. Verify the image chain: CI build -> ECR tag -> node imageID

Symptoms like "I fixed the code but the pod still runs the old bug" are almost always a
break in this chain. Check each link:

1. **CI built and pushed**: `gh run view <run> -R <repo> --job <build-job-id> --log |
   grep -a "pushing manifest"` — note the digest and tags. The build pushes an immutable
   `<branch-slug>-<sha7>` tag first (e.g. branch `demo-coggtm` at `3c18da3` →
   `demo-coggtm-3c18da3`; a fork with the `TENANT_PREFIX` repo variable set prepends it,
   and the branch is slugified — see `branch_tag_slug` in `scripts/lib/tenant-common.sh`;
   trust the tag the build log actually printed); if the job then fails on `tenant-<id>` ("tag is
   immutable and cannot be overwritten"), **the unique tag is still usable** — the
   failure is only the moving pointer tag (known CD bug, see PR #87).
2. **ECR tag points where you think** *(ask a human)*:
   `aws ecr describe-images --repository-name otterworks/<service> --region us-east-1`.
3. **The node runs that digest** *(ask a human)*:
   `kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].imageID}'`.
   Buildx pushes an OCI **index**, so the pod's imageID is the child manifest digest, not
   the index digest — different digests are not automatically a mismatch. But if the
   imageID is a digest that does not exist in ECR at all, the node has a **stale local
   image cached under the same tag** and `pullPolicy: IfNotPresent` keeps reusing it.

**Escape hatch for both stale caches and broken pointer tags**: deploy the unique
immutable tag directly *(ask a human)*:

```bash
kubectl -n otterworks-<id> set image deployment/<service> \
  <service>=<registry>/otterworks/<service>:<branch-slug>-<sha7>
```

A unique tag is never cached on the node, so it always forces a genuine pull.
Teardown/redeploy does NOT fix a stale node cache — the new pod lands on the same node
and reuses the same cached tag.

## 3. The runner deploys its bundled tree, not your branch

Unless `GITHUB_TOKEN` and `REPO_HTTPS_URL` are configured for the runner, the runner Job
cannot check out tenant branches — the deploy log prints `branch checkout of <branch>
failed; continuing with the image's bundled tree` whenever checkout fails (unset
credentials — the current state — but also a nonexistent branch or a token without
repo read; a run with no `TENANT_BRANCH` at all logs `no TENANT_BRANCH set; using
image's bundled checkout` instead). While the fallback is in effect:

- **Helm chart / values / probe / resource changes on a demo branch never reach the
  tenant.** Only changes baked into a service's Docker image ship.
- Fixes must either go in the image (app code, Dockerfile) or be `kubectl patch`ed by a
  human — and patches are reverted by the next dashboard sync/redeploy.

## 4. Failure signatures seen in production triage

| Signature | Cause | Fix |
|---|---|---|
| Puma log: `Invalid HTTP format ... SSL connection to a non-SSL Puma?` at probe cadence; events: `server gave HTTP response to HTTPS client` | Rails `config.force_ssl = true` 301-redirects `/health` to https; kubelet follows the redirect and TLS-handshakes Puma's plain port; liveness kills the pod (exit 137, reason `Error`, not OOM) | `config.force_ssl = false` in the image (TLS terminates at the shared ingress) |
| `/health` returns 503, `db: 0.0` in request logs; `db:migrate` aborts at boot | Deploy wires `DATABASE_HOST/PORT/USER/PASSWORD` but **no database name**; Rails' `database.yml` hardcodes `admin_service_production`, which doesn't exist — the tenant DB is `otterworks_<id>` | make `database.yml` read `ENV["DATABASE_NAME"]` and wire `config.DATABASE_NAME=${T_DB_NAME}` in `scripts/lib/tenant-common.sh` (admin-service case). A tenant-specific fallback baked into an image is acceptable **only** on that tenant's own `demo-<id>` branch — never on golden/`main`, whose image every tenant shares |
| `bin/rails aborted! NoMethodError ... TaggedLogging.logger` | The upstream planted bug (`production.rb`); fixed on this fork, intentional upstream | Ensure the pod runs a fork-built image, not `:main` |
| Build job fails: `The image tag 'tenant-<id>' already exists ... immutable` | CD re-pushes the moving `tenant-<id>` pointer to an immutable registry on every rebuild | Use the immutable `<branch-slug>-<sha7>` tag it already pushed (see §2); durable fix tracked in PR #87 |
| Pod `Pending` forever during rollout | Old crash-looping pod holds quota/capacity; surge pod can't schedule | Resolve why the old pod is unhealthy first; the rollout completes once the new pod goes ready |

## 5. Order of operations

1. Dashboard API: pod list + runner log (which tags deployed?).
2. If crash-looping: get pod logs/events via a human — do not guess between OOM, probe
   kill, and app crash; `lastState.terminated.reason`/`exitCode` distinguishes them.
3. If code fix needed: commit to the tenant's `demo-<id>` branch, let CD build, then
   deploy the **unique** `<branch-slug>-<sha7>` tag (see §2) via `set image` (the deploy job is skipped whenever any
   service build fails on the immutable pointer tag, so don't wait for it).
4. Re-check via the dashboard until `ready: true`, then verify externally:
   `curl -s -o /dev/null -w '%{http_code}' https://api-t-<id>.demo.otterworks.app/<path>`
   (401 from an authed endpoint proves the service is up and routed).
5. Remember every `kubectl` patch/`set image` is temporary — record what must be
   re-applied after the next dashboard sync, or bake it into the image.
