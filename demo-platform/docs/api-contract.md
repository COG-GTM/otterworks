# Demo Ops Dashboard — API contract

The dashboard is a **Next.js** app (server + UI in one deployable) in namespace
`otterworks-platform`, served at `https://ops.otterworks.app`. All routes below are Next.js
**server** route handlers (`app/api/...`) — enforcement is server-side, never trust the client.

## Auth (passcode, server-side)
- `POST /api/auth/login` `{ passcode }` → sets an HttpOnly, Secure, SameSite=Strict signed
  session cookie (`ow_ops_session`, ~8h). **Constant-time compare** against the passcode from
  env `DASHBOARD_PASSCODE` (mounted from the `demo-ops-dashboard` Secret). **Rate-limit**:
  max 5 attempts / IP / 15 min, exponential backoff, audit `login_ok`/`login_fail`.
- `POST /api/auth/logout` → clears cookie.
- **Every** other `/api/*` handler calls `requireSession()` first (401 if missing/invalid).
  A Next.js `middleware.ts` also gates all non-login routes.

## Tenants
- `GET /api/tenants` → `Tenant[]` — control-table items **joined with live cluster state**
  (namespace phase, ready/total pods, per-service status, url). Cached ~5s.
- `GET /api/tenants/:id` → `Tenant` + `pods[]` + recent `audit[]`.
- `POST /api/tenants/checkout` `{ id?, branch, owner, tier?, ttl?, image_tag? }` →
  atomic lock (409 if taken), upsert `TENANT#`, enqueue a **deploy runner Job**, status
  `deploying`. Returns the `Tenant`.
- `POST /api/tenants/:id/checkin` → enqueue **teardown runner Job**, status `draining`.
- `POST /api/tenants/:id/extend` `{ ttl }` → bump `expires_at`.
- `POST /api/tenants/:id/inject` `{ scenario }` / `POST /api/tenants/:id/reset` → drive the bug
  catalog via a runner Job (optional; nice-to-have).

## Reaper
- `GET /api/reaper` → `CONFIG#reaper`.
- `PUT /api/reaper` `{ schedule_cron, grace_seconds, enabled, sweep_orphans, suspend_idle,
  idle_after_seconds, sweep_infra, sweep_infra_delete }` → update config
  (the reaper CronJob reads this each run; changing the cron also patches the CronJob schedule).
- `GET /api/reaper/orphans` → resources with no matching tenant (preview before sweep).

## Audit
- `GET /api/audit?limit=100` → recent events across tenants.

## Types (shared `lib/types.ts`)
```ts
type TenantStatus = "free"|"reserved"|"deploying"|"active"|"draining"|"error";
interface Tenant {
  id: string; status: TenantStatus; owner?: string; branch?: string; tier: "A"|"B";
  imageTag?: string; url?: string; apiUrl?: string; dbName: string; namespace: string;
  createdAt: number; expiresAt: number; lastSeenAt: number; note?: string;
  live?: { phase: string; readyPods: number; totalPods: number;
           services: { name: string; ready: boolean; restarts: number }[] };
}
```

## How actions execute (runner Jobs)
The web pod stays light: mutating actions create a Kubernetes **Job** (`otterworks-platform`
ns) from the `otterworks-demo-runner` image, which carries the repo + `aws/kubectl/helm/
terraform/jq` and runs `scripts/deploy-tenant.sh` / `teardown-tenant.sh` / `inject-bug.sh`.
The Job uses the dashboard's IRSA role + a ClusterRole that can manage `otterworks-*`
namespaces. Job name = `deploy-<id>-<epoch>` / `teardown-<id>-<epoch>`; logs stream back via
`GET /api/tenants/:id` (reads Job pod logs). The runner reads/writes the control table so
status transitions survive even if the web pod restarts.
