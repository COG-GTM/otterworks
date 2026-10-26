# Legacy Billing — database-centric before state

`legacy-billing` is a deliberately database-centric billing application. It
is the durable before-state for the stored-procedure extraction flow: the
running application has server-rendered pages and a small JSON API, while the
business behavior is implemented in PostgreSQL under the `billing` schema.

This component is part of the OtterWorks golden app as a durable before-state.
The extraction target and the modern client are separate components and are
not part of this service.

## Modules

| Module | Procedures/functions | Routes |
|---|---|---|
| Plans | `fn_list_plans`, `fn_entitlement`, `sp_change_plan` | `/plans`, `/plans/<tenant>/entitlement`, `/plans/<tenant>/change` |
| Rating | `fn_usage_rating`, `fn_usage_summary`, `sp_finalize_rating` | `/api/rating/preview`, `/api/rating/finalize` |
| Invoicing | `fn_invoice_preview`, `fn_invoice_lines`, `sp_issue_invoice` | `/api/invoices/<tenant>/preview`, `/api/invoices/<tenant>/issue`, `/api/invoices/<invoice>/lines` |
| Dunning | `fn_overdue_accounts`, `sp_schedule_dunning`, `sp_suspend_overdue` | `/api/dunning/overdue`, `/api/dunning/schedule`, `/api/dunning/suspend` |

The Flask layer intentionally binds request values, calls a database
entrypoint, and renders the returned values. It does not reproduce domain
decisions in Python.

## Authentication and tenant scoping

Every route except `/health` requires `Authorization: Bearer <JWT>`. Tokens are
HS256 access tokens signed with `LEGACY_BILLING_JWT_SECRET` (the platform
`JWT_SECRET` used by auth-service and api-gateway, at least 32 bytes). If the
secret is unset or too short, protected routes return `503` — the service fails
closed. Refresh tokens, `alg` other than `HS256`, and tokens without `exp` or
`sub` are rejected with `401`.

Access is granted by two claims:

- `scope` (space-separated) or `scp` (list): `billing:read`, `billing:write`,
  `billing:admin`. `write` implies `read`; `admin` implies both.
- `tenant_id`: the tenant the caller acts for. Tenant-scoped routes return
  `403` unless it matches the target tenant; `billing:admin` may act for any
  tenant.

| Route | Scope | Tenant check |
|---|---|---|
| `/`, `/plans` | `billing:read` | — (plan catalog) |
| `GET /plans/<tenant>/entitlement`, `GET /api/invoices/<tenant>/preview`, `POST /api/rating/preview` | `billing:read` | path / body `tenant_id` |
| `GET /api/invoices/<invoice>/lines` | `billing:read` | invoice owner (`404` otherwise) |
| `POST /plans/<tenant>/change` | `billing:write` | path tenant |
| `POST /api/rating/finalize`, `POST /api/invoices/<tenant>/issue`, `GET /api/dunning/overdue`, `POST /api/dunning/schedule`, `POST /api/dunning/suspend` | `billing:admin` | — (operator actions) |

A route registered without a policy decorator (`requires`/`public` in
`app/auth.py`) is rejected with `403`.

In a deployment alongside auth-service, set `LEGACY_BILLING_JWT_SECRET` to the
same value as the platform `JWT_SECRET` so issuer and verifier share the key.
auth-service access tokens do not yet carry `scope`/`tenant_id`, so until the
issuer adds those claims they are rejected with `403`.

The local Compose profile has no auth-service. Export a secret before
`make procs-up` and mint test tokens with it:

```bash
export LEGACY_BILLING_JWT_SECRET=$(openssl rand -hex 32)
TOKEN=$(uv run --with pyjwt python -c 'import jwt, os, time; print(jwt.encode({"sub": "ops", "type": "access", "exp": int(time.time()) + 600, "scope": "billing:read", "tenant_id": "00000000-0000-0000-0000-000000000001"}, os.environ["LEGACY_BILLING_JWT_SECRET"], algorithm="HS256"))')
curl -H "Authorization: Bearer $TOKEN" http://localhost:8096/plans/00000000-0000-0000-0000-000000000001/entitlement
```

Tests: `uv run --with flask==3.1.1 --with psycopg[binary]==3.2.9 --with pytest==8.3.5 pytest services/legacy-billing/tests`.

## Why it is an extraction candidate

- The domain boundaries are already grouped into database procedure modules.
- The service has a narrow HTTP surface that maps to those entrypoints.
- PostgreSQL owns the state transitions and computed billing results.
- The database can be reset to a deterministic seed for repeatable recordings.

## Full verification loop

The extracted reference service is `services/billing-service/`, backed by a
separate Postgres database and `billing_svc` schema. The
declarative contract and human-approved ledger live under `procs/`. From the
repository root:

```bash
make procs-up NS=dev
make procs-rules-gate MODULE=plans
make procs-parity NS=dev
make procs-down NS=dev
```

The parity report compares the target's returned fields and target-side state
probes with immutable recordings. Modules not yet extracted remain skipped.
The legacy procedure files and recordings remain the source of truth for the
before-state.

## Run locally

From the repository root:

```bash
make procs-up NS=dev
curl http://localhost:8096/health
make procs-down NS=dev
```

The Compose profile is intentionally separate from the Helm/EKS path. It
models the legacy application running with its own PostgreSQL database.

## Database layout

- `db/schema.sql` — tables and constraints
- `db/procs/` — database entrypoints
- `db/seed.sql` — deterministic starting state
