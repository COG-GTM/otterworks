# OtterWorks Multi-Tenant / Ephemeral Demo Environments — Scoping & Plan

**Goal.** Run many concurrent OtterWorks demos on the **same shared AWS/EKS infrastructure**
without demos stepping on each other, so facilitators/attendees can:

- spin up an **isolated** copy of the app on demand,
- **inject bugs** (or apply demo-specific variants) without affecting anyone else,
- do **immediate redeploys** to fix bugs mid-session,
- and keep **cost** under control by sharing the expensive pieces.

The unit of isolation is a **tenant** = one attendee or one demo run, identified by an
`ATTENDEE_ID` (e.g. `a01`, `smith`, a short UUID). Everything below is organized around that.

> **Golden app first.** `main` is the golden app: the canonical, fully-working initial state
> (fully functional *except* deliberately planted bugs — see `AGENTS.md`). Every tenant is
> **derived from the golden app**; variants never flow back into `main`.

---

## 1. TL;DR recommendation

- **One shared EKS cluster + one shared SPOT node group.** Do **not** give each tenant its own
  cluster or node group (control plane is ~$73/mo each; node groups take ~15 min to create).
- **Namespace-per-tenant** (`otterworks-<ATTENDEE_ID>`) is the isolation boundary: one Helm
  release set + one ConfigMap/Secret + one MeiliSearch per namespace, guarded by a
  `ResourceQuota`, `LimitRange`, and `NetworkPolicy`.
- **Share the stateful backends physically, isolate them logically** via the per-tenant naming
  knobs the app already exposes (table names, S3 prefix, Redis prefix, Meili index, DB schema).
  No new data-store infrastructure per tenant → near-zero marginal cost per tenant.
- **Route by host/path through one shared ingress** (ingress-nginx + one ALB/NLB), not one
  `LoadBalancer` Service per tenant (each ELB is ~$18/mo and there's a per-account limit).
- **Bug injection is config/variant, not infra:** use the app's built-in **chaos-injection Redis
  flags** for runtime faults, and a thin **variant overlay** (branch/patch or image tag) for code
  bugs. Immediate redeploy = `helm upgrade` scoped to the tenant namespace (seconds).
- **Cost control:** per-tenant replica count = 1, shared heavy singletons, `scale-to-zero` idle
  namespaces, and a reaper that deletes namespaces past TTL.

---

## 2. What can be shared vs. what must be isolated

| Layer | Strategy | Why / how |
|---|---|---|
| EKS control plane | **Shared** | Fixed cost per cluster; one cluster serves all tenants. |
| Node group (SPOT) | **Shared** | Bin-pack all tenant pods; autoscale nodes, not clusters. |
| ingress controller + ALB/NLB | **Shared** | One ingress routes all tenants by host/path. |
| Observability (Prometheus/Grafana/OTel/Fluent Bit) | **Shared** | Cluster-wide DaemonSets/Operators; label metrics/logs by namespace. |
| **k8s namespace** | **Per tenant** | Hard boundary for RBAC, quota, NetworkPolicy, releases. |
| Helm releases (13 backends + 2 FE) | **Per tenant** | Independent versions, config, and redeploys. |
| ConfigMap / Secret | **Per tenant** | Points each tenant at its logical data slice. |
| MeiliSearch | **Per tenant (small) or shared w/ index prefix** | 256Mi pod; cheap to run one per namespace for full isolation. |
| RDS Postgres (instance) | **Shared instance, per-tenant database/schema** | `otterworks_<ATTENDEE_ID>` DB or schema; one `db.t3.micro` serves many. |
| ElastiCache Redis | **Shared, per-tenant key prefix or logical DB** | Namespacing via key prefix; collab/session isolation. |
| DynamoDB tables | **Shared account, per-tenant table name prefix** | Table names are already env-configurable (see §4). |
| S3 buckets | **Shared bucket, per-tenant key prefix** | `s3://otterworks-files-dev/<ATTENDEE_ID>/...`. |
| SNS/SQS | **Shared topic, per-tenant queue or filter** | Per-tenant SQS queue subscribed with a filter policy. |
| IRSA roles | **Shared per-service role** (dev) → **per-tenant role** (strict) | Dev can reuse; strict isolation scopes policies to the tenant's resource prefixes. |

**Isolation tiers** (pick per event):

- **Tier A — Compute-isolated (cheapest, fastest).** Per-tenant namespace + releases; **shared**
  data stores with logical prefixes. Blast radius: a tenant can only touch its own prefixes.
  Best default for large workshops.
- **Tier B — Data-isolated.** Tier A + per-tenant RDS database/schema and per-tenant DynamoDB
  tables (created on demand). Stronger separation for data-centric demos; slightly slower spin-up.
- **Tier C — Fully isolated.** Separate cluster/account per tenant. Only for security demos that
  require it; highest cost/latency. Not recommended as default.

---

## 3. Ease-of-ephemeralization by component

**Easy (stateless — just a namespaced Helm release):** api-gateway, auth-service, file-service,
document-service, collab-service, notification-service, search-service, analytics-service,
audit-service, report-service, admin-service, web-app, admin-dashboard, in-cluster MeiliSearch.
All already read their endpoints from ConfigMap/Secret, so a per-tenant deploy just injects a
per-tenant value set. `deploy-dev.sh`'s `build_helm_args()` is the seam to parameterize.

**Medium (needs a per-tenant naming convention):** the data stores. The app **already**
parameterizes the relevant names via env (see §4), so ephemeralization is a wiring change, not a
code change. Tier A uses prefixes on shared stores; Tier B provisions per-tenant stores.

**Hard / keep shared (platform):** EKS cluster, node group, ingress controller, cert-manager,
observability stack. These belong in `platform-engineering-shared-services` and are shared by all
tenants; do **not** duplicate them per tenant.

---

## 4. The per-tenant naming knobs already in the app

The golden app's config is already tenant-parameterizable — no code changes needed for Tier A:

| Concern | Env var(s) | Per-tenant value |
|---|---|---|
| File metadata / folders / versions / shares | `DYNAMODB_TABLE`, `DYNAMODB_FOLDERS_TABLE`, `DYNAMODB_VERSIONS_TABLE`, `DYNAMODB_SHARES_TABLE` | prefix table name with `<ATTENDEE_ID>-` (Tier B) or share table + partition by owner (Tier A) |
| Audit / notifications | `Aws__DynamoDbTable`, `DYNAMODB_TABLE_NOTIFICATIONS` | same |
| Object storage | `S3_BUCKET` (+ app key prefixes) | shared bucket, `<ATTENDEE_ID>/` key prefix |
| Search | `MEILISEARCH_URL`, `MEILISEARCH_DOCUMENTS_INDEX`, `MEILISEARCH_FILES_INDEX` | per-tenant MeiliSearch Service **or** shared server + `<ATTENDEE_ID>-documents` index |
| Cache / sessions / collab | `REDIS_HOST`, `REDIS_PORT` | shared Redis + per-tenant key prefix (app-level) |
| Relational | `SPRING_DATASOURCE_URL`, `DOC_SVC_DATABASE_URL`, `DATABASE_*`, `DB_*` | shared instance, `otterworks_<ATTENDEE_ID>` database/schema |
| Eventing | `SNS_TOPIC_ARN`, `SQS_QUEUE_URL` | shared topic, per-tenant queue |
| Routing | `API_GATEWAY_URL` (frontends) | `http://api-gateway.<namespace>:8080` |

---

## 5. Routing & access

- **Shared ingress-nginx** with host- or path-based routing:
  - Host: `t-<ATTENDEE_ID>.otterworks.<domain>` → that tenant's `web-app` Service.
  - Or path: `/<ATTENDEE_ID>/` if a wildcard host isn't available.
- One ALB/NLB (via AWS Load Balancer Controller) fronts ingress-nginx; **avoid** per-tenant
  `type: LoadBalancer` Services (ELB cost + account limits). The golden dev deploy uses
  `LoadBalancer` for simplicity; the multi-tenant overlay switches frontends to `ClusterIP` +
  ingress.
- TLS via cert-manager wildcard cert (`*.otterworks.<domain>`).

---

## 6. Bug injection & immediate redeploys

Three layers, from lightest to heaviest — none touch other tenants:

1. **Runtime chaos flags (no redeploy).** The app supports **chaos injection via Redis flags**
   (e.g. `search-suggest-500`). Set a tenant-scoped flag to fault a specific operation live — ideal
   for "find and fix the incident" demos. Clears instantly.
2. **Config/variant flags (seconds).** `helm upgrade` the tenant's release with a changed value
   (feature flag, bad env value, resource starvation) — scoped to `otterworks-<ATTENDEE_ID>`.
3. **Code bug (image swap).** Build a variant image (planted bug on a variant branch/patch off the
   golden app) and `helm upgrade --set image.tag=<variant>` for just that tenant. Immediate
   rollback = re-point to the golden tag.

Immediate redeploy to **fix** a bug mid-demo is the same mechanism: `helm upgrade` the one service
in the one namespace (a few seconds), or `kubectl rollout restart` to reload config. Because the
charts don't checksum the ConfigMap, config-only changes need a `rollout restart` (or add a
`checksum/config` pod annotation to the charts to automate it — recommended follow-up).

---

## 7. Cost balancing

- **Compute:** shared SPOT node group + Cluster Autoscaler/Karpenter; per-tenant replicas = 1;
  right-sized requests (JVM services 512Mi req / 1Gi limit, others small). Bin-packing many small
  tenants onto few nodes is far cheaper than isolated clusters.
- **`ResourceQuota` + `LimitRange` per namespace** so no tenant can starve the cluster (align with
  org standard: default 500m CPU / 256Mi mem, quota e.g. 2 CPU / 4Gi / 20 pods per tenant).
- **Scale-to-zero when idle:** `kubectl scale --replicas=0` all deployments in a namespace between
  sessions (or KEDA cron scaler); the namespace and data survive, compute cost drops to ~0.
- **TTL reaper:** label namespaces with `demo/expires-at`; a scheduled job deletes expired tenants
  (and Tier B per-tenant data) to stop drift and cost.
- **Shared singletons:** one observability stack; optionally one shared MeiliSearch with per-tenant
  indexes instead of one pod per tenant if pod count gets large.
- **Reuse ECR images:** tenants pull the same golden image tag; only variants build new images.

---

## 8. Proposed implementation phases

1. **Parameterize the deploy on `ATTENDEE_ID`.** Add `scripts/deploy-tenant.sh <ATTENDEE_ID>
   [--tier A|B] [--image-tag TAG]` that wraps the existing wiring in `deploy-dev.sh`:
   namespace = `otterworks-<ID>`, per-tenant ConfigMap/Secret values from §4, frontends on
   ingress not LoadBalancer, apply `ResourceQuota`/`LimitRange`/`NetworkPolicy`, deploy a
   per-tenant (or shared) MeiliSearch. Companion `teardown-tenant.sh <ATTENDEE_ID>`.
2. **Shared platform baseline.** Ensure ingress-nginx + cert-manager + AWS LB Controller +
   observability live in `platform-engineering-shared-services` (shared by all tenants).
3. **Logical data isolation (Tier A).** S3 key prefix + Redis key prefix + Meili index prefix +
   DynamoDB owner partitioning; verify no cross-tenant reads.
4. **Optional data isolation (Tier B).** On-demand per-tenant RDS schema + DynamoDB tables
   (extend `modules/database` with a `for_each` over active tenants, or create via the tenant
   script) + per-tenant IRSA policy scoped to the tenant's prefixes.
5. **Lifecycle automation.** Namespace TTL labels + reaper CronJob + scale-to-zero scheduler;
   dashboard of active tenants and cost.
6. **Variant & bug-injection catalog.** A small registry mapping demo name → variant (chaos flag,
   config override, or image tag) so facilitators pick a scenario per tenant.

---

## 9. Risks & open questions

- **Shared-store blast radius (Tier A).** Logical prefixes rely on app-level enforcement; a bug
  could cross tenants. Tier B removes this at the cost of per-tenant provisioning time.
- **IRSA granularity.** Dev reuses one role per service across tenants; strict isolation needs
  per-tenant roles scoped to per-tenant resource ARNs (more IAM objects).
- **Chart config-reload.** Add `checksum/config` annotations so `helm upgrade` auto-rolls pods on
  config change (today a manual `rollout restart` is needed).
- **DNS/wildcard cert** must exist for host-based routing; otherwise fall back to path routing.
- **Account limits** (ELB count, IAM roles, DynamoDB tables) inform how far Tier B/C scale.
