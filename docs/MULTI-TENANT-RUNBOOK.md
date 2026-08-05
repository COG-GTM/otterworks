# OtterWorks Multi-Tenant Demo — Operator Runbook

Execution of `docs/MULTI-TENANT-DEMO-PLAN.md`. Stands up many **isolated,
ephemeral** copies of the golden app on the **shared** `otterworks-dev` EKS
cluster, one per attendee/demo run (`ATTENDEE_ID` → namespace
`otterworks-<ATTENDEE_ID>`).

> The golden app is `main`. Tenants are derived from it; variants/bugs are
> injected per tenant and **never** flow back into `main`
> (see `AGENTS.md`).

## Scripts

| Script | Purpose |
|---|---|
| `scripts/tenant-platform-baseline.sh` | **Run once.** Installs the SHARED ingress-nginx (one NLB) and the namespace TTL reaper CronJob. |
| `scripts/deploy-tenant.sh <ID> [--tier A\|B] [--image-tag TAG] [--ttl 8h\|none] [--host-suffix DOMAIN]` | Deploy/redeploy one tenant. `--ttl none` makes it persistent. |
| `scripts/deploy-tenant-batch.sh [NAME ...]` | Deploy one **persistent** tenant per person in `scripts/tenant-roster.txt`. |
| `scripts/teardown-tenant.sh <ID> [--keep-db] [--keep-trust]` | Delete one tenant (namespace + per-tenant DB + IRSA trust). |
| `scripts/inject-bug.sh <ID> <list\|reset\|scenario>` | Inject/clear a per-tenant bug (chaos flag / config / image). |
| `scripts/tenant-scale.sh <ID> <up\|down>` | Scale a tenant's compute to zero (or back) between sessions. |
| `scripts/bug-catalog.yaml` | The demo-scenario → variant registry. |
| `scripts/lib/tenant-common.sh` | Shared library (naming, TF-output loading, per-service Helm wiring). |

## Prerequisites (per shell)

```bash
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_DEFAULT_REGION=us-east-1
# aws sts get-caller-identity  -> expect the workshop account (<AWS_ACCOUNT_ID>) and a Devin-PartnerWorkshops-Internal IAM identity
export DB_PASSWORD='<shared RDS master password>'
# Stable across redeploys so issued JWTs / Rails sessions stay valid:
export JWT_SECRET='<hex>' SECRET_KEY_BASE='<hex>'
```

Env vars do not persist between separate shell commands in some runners —
re-export within each command or combine into one.

## First-time setup

```bash
./scripts/tenant-platform-baseline.sh          # shared ingress + reaper (once)
```

## Spin up two tenants

```bash
./scripts/deploy-tenant.sh a01 --ttl 8h
./scripts/deploy-tenant.sh a02 --ttl 8h
kubectl get ns -l app.kubernetes.io/managed-by=otterworks-tenant
```

Reach a tenant's API without DNS:

```bash
kubectl -n otterworks-a01 port-forward svc/api-gateway 8080:8080
curl -s localhost:8080/api/v1/... 
```

With wildcard DNS, pass `--host-suffix demo.example.com` → the tenant is served
at `t-a01.demo.example.com` (web) and `api-t-a01.demo.example.com` (gateway)
through the one shared ingress/NLB.

## Persistent tenants (one standing environment per person)

A workshop seat is ephemeral; a per-person environment is not. `--ttl none`
(also `never`) writes **no** `demo/expires-at*` annotation and labels the
namespace `demo/persistent=true`. Both reapers key off the presence of an
expiry, and `demo-platform/reaper/reaper.sh` additionally refuses to GC a
persistent tenant's namespace, database, S3 prefix or DynamoDB partitions even
though it has no control-table item (it would otherwise read as an orphan).
Only `teardown-tenant.sh` removes one.

Deploy the whole roster — one `firstname-lastname` tenant per line of
`scripts/tenant-roster.txt` — with:

```bash
./scripts/deploy-tenant-batch.sh --dry-run          # resolved ids, no changes
./scripts/deploy-tenant-batch.sh --concurrency 4
./scripts/deploy-tenant-batch.sh "Ada Lovelace"     # just one person
```

Names are transliterated to ASCII before slugging (`João Esteves` →
`otterworks-joao-esteves`, database `otterworks_joao_esteves`), and two names
that collide on one id abort the run before anything is deployed. Re-running is
safe and is how a partial run is finished: a tenant whose deploy completed is
skipped (`demo/deployed-at` on its namespace), and one left half-built by an
aborted run is retried rather than mistaken for done — the namespace is created
in the first seconds of a deploy, so its existence alone proves nothing.
Per-tenant logs land in `--log-dir` and the exit status is non-zero if any tenant
failed.

Before deploying, the batch measures the roster against the free addresses in
the node subnets and refuses a run that cannot fit — over the ceiling nothing
fails fast, pods simply sit `Pending` and tenants time out one at a time,
leaving the roster half deployed. `--no-preflight` overrides it, and the check
is advisory (a warning) if EC2 cannot be queried.

**Persistent is not the same as awake.** A persistent tenant still scales to
zero after an hour with no ingress traffic, and nothing wakes it by itself:
opening the URL of a suspended tenant returns 503 from the shared ingress, and
the dashboard's check-out wake needs a `TENANT#<id>` control-table item, which a
batch-deployed tenant does not have. The only wake is
`./scripts/tenant-scale.sh <id> up` (~60–90s to ready). Pass `--always-on` to
exempt it: that labels the namespace `demo/always-on=true` and `idle-suspend.sh`
leaves it alone — and scales it back up if it finds it at zero, since a tenant
suspended before the label went on would otherwise be exempted into a permanent
503 — so the URL answers cold with no wake step. It is opt-in because
the exemption is what costs money — an always-on tenant holds its requests and
pod IPs whether or not anyone opens it. Dropping the flag on a redeploy removes
the label and the tenant idles normally again; to park one by hand, remove the
label first (`kubectl label ns otterworks-<id> demo/always-on-`), or the next
idle scan puts it straight back up.

```bash
./scripts/deploy-tenant-batch.sh --always-on --concurrency 4   # whole roster stays up
```

**Capacity.** An always-on tenant reserves its requests indefinitely — ~1.5 vCPU
/ 3.5 GiB on `full`, ~0.5 vCPU / 1.3 GiB on `core` — and holds ~15 (`full`) or
~7 (`core`) pod IPs for as long as it exists. A batch also brings the whole
roster up at once regardless of the flag, so the peak is the same either way at
deploy time. Before deploying a roster of this size, check four ceilings:

| Ceiling | Where | Room |
|---|---|---|
| Pod IPs | node subnets — the `/24`s hold ~500 total, `aws_subnet.pods` adds a `/20` per AZ | ~30 `full` before, ~500 after |
| Pods per node | `kubelet.maxPods` on the Karpenter `EC2NodeClass` | 58 before, 110 after |
| Node CPU | `limits.cpu` on the Karpenter NodePool | ~130 `full` / ~400 `core` |
| DB clients | PgBouncer `max_client_conn` | ~125 awake `full` |

Raising `maxPods` is a one-time recycle: it is part of the `EC2NodeClass` spec
Karpenter hashes for drift, so the `install-karpenter.sh` run that first applies
it replaces every node it owns (20% at a time) and restarts every tenant that is
awake. Do it before the roster exists, or in a quiet window.

A ~95-person roster is ~140 vCPU (`full`, the default) or ~47 vCPU (`core`) —
roughly $3,600 vs $800/month of spot compute if it is `--always-on`, and a
fraction of that otherwise, since idle tenants scale to zero between uses.
`full` is what a bug-hunt lab needs (`core` omits `admin-service`); `core` is
the lever if the estate is larger than the lab. Either way the ceilings above
are what decide whether the roster fits. See
[`cost-and-scale.md`](../demo-platform/docs/cost-and-scale.md) §5.

## Isolation model (what is shared vs. per-tenant)

| Concern | Per-tenant mechanism |
|---|---|
| Compute | namespace + `ResourceQuota` + `LimitRange` + `NetworkPolicy`, `replicas=1` |
| Chaos flags / sessions / collab | **per-tenant in-cluster Redis** (`redis.<ns>`) — chaos keys are un-prefixed, so a shared Redis would leak bug injection across tenants; a dedicated Redis fully isolates it |
| Search | **per-tenant in-cluster MeiliSearch** |
| Relational data | **per-tenant RDS database** `otterworks_<ID>` on the shared instance (auth-service Flyway + document-service `create_all` self-provision the schema on boot) |
| Object storage | shared `otterworks-files-dev` bucket (objects keyed by UUID); listing is driven by the per-tenant DB / DynamoDB, so no cross-tenant listing |
| DynamoDB / S3 access | shared per-service **IRSA roles**; `deploy-tenant.sh` extends each role's trust policy to the tenant namespace's service accounts (dev-reuse model; the Terraform `modules/irsa` change makes this the reproducible default) |

**Tier A (default, implemented):** shared physical stores, isolated logically as
above. Blast radius: the shared S3 bucket and DynamoDB dev tables are physically
shared (mitigated because listings come from the per-tenant DB and objects use
UUID keys). Redis, MeiliSearch and the relational DB are fully per-tenant.

**Tier B (data-isolated):** additionally provision per-tenant DynamoDB tables and
scoped IRSA. **Not enabled by default** because the shared file-service IAM
policy is pinned to the `*-dev` table ARNs; enabling Tier B requires broadening
that policy resource to `otterworks-*` (or minting per-tenant roles) — see
"Known limitations". The per-tenant RDS database already gives Tier-B-grade
isolation for all Postgres-backed services today.

## Bug injection (per tenant, never touches others)

```bash
./scripts/inject-bug.sh a01 list
./scripts/inject-bug.sh a01 file-upload-fails     # chaos flag in a01's Redis only
./scripts/inject-bug.sh a01 reset                 # clear a01's chaos flags
```

Mechanisms: `chaos` (Redis flag, instant, auto-expiring), `config` (helm upgrade
+ rollout restart), `image` (variant image tag for one service). Fixing a bug
mid-demo is the same lever scoped to the one namespace (seconds).

## Cost controls

- One shared EKS cluster + node group; `replicas=1` per tenant; `ResourceQuota`
  caps each tenant (4 CPU / 8Gi requests, 40 pods).
- One shared ingress/NLB for all tenants (no per-tenant ELB).
- **Scale-to-zero** idle tenants: `./scripts/tenant-scale.sh <ID> down`.
- **TTL reaper** CronJob (every 15m) deletes tenant namespaces whose
  `demo/expires-at-epoch` annotation is in the past (integer compare only, so the
  reaper image needs nothing more than `date +%s`). Namespaces without that
  annotation — i.e. persistent tenants — are left alone.
- Tenants reuse the golden ECR image tags; only variants build new images.

## Teardown

```bash
./scripts/teardown-tenant.sh a01     # drops ns + per-tenant DB + IRSA trust subs
```

## Verified live (2026-07-13, cluster `otterworks-dev`)

Stood up `a01` + `a02` concurrently on the shared cluster and confirmed:

- **Separate namespaces**, each 12/13 pods Running (`admin-service` crash-loops by
  design). Every tenant Service is `ClusterIP` — **no per-tenant LoadBalancer**;
  the only ELBs are the one shared `ingress-nginx` NLB and the golden app's.
- **Shared ingress routing:** `curl -H "Host: api-t-a01..." $NLB/health` → 200 and
  the same for `a02`; web hosts `t-a01/t-a02` → 200; unknown host → 404 — all
  through the single NLB.
- **Relational isolation:** a user registered in `a01` (`201`, login `200`) does
  **not** exist in `a02` (login `400`); re-registering the same email in `a02`
  succeeds (`201`) — proving independent per-tenant databases.
- **Bug isolation:** injecting `search-suggest-500` into `a01` only → `a01`
  `/search/suggest` returns `500` while `a02` stays `200`; `reset` restores `a01`.
- **Cost controls:** `tenant-scale.sh a02 down` → 15/15 deployments at 0 replicas
  (0 running pods), `up` restores them; the reaper kept both live tenants and
  deleted a synthetic expired namespace.
- **Teardown/cleanup:** both tenants removed — namespaces gone, per-tenant DBs
  dropped, and tenant subjects removed from the shared IRSA role trust policies.

Note: the 2-node SPOT group is sized for the golden app; running two extra full
tenants required scaling the shared node group to 4 (`t3.large` SPOT). Size the
shared group for the expected number of concurrent tenants (or enable an
autoscaler) rather than per-tenant node groups.

## Known limitations / honest gaps

- **Tier B DynamoDB** is documented but not enabled by default (IAM policy is
  ARN-pinned to the dev tables — see above). Postgres isolation via per-tenant DB
  is fully implemented.
- **Shared SNS/SQS eventing is left unwired for tenants** (`T_WIRE_EVENTING=false`)
  to avoid competing-consumer cross-talk on the shared queue. notification/search
  event pipelines are therefore inert per tenant; the request/response paths work.
- **NetworkPolicy** is applied for correctness but is only *enforced* if the
  cluster CNI has network-policy enforcement enabled.
- **`admin-service` crash-loops by design** (planted Rails logger bug on the
  golden app) — it is intentionally left broken in every tenant.
- Path-based ingress (no `--host-suffix`) serves an SPA under a sub-path with a
  rewrite; host-based routing is cleaner when wildcard DNS is available.
