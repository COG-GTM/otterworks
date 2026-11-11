# Billing Service

This FastAPI service is the extraction target for the plans module. It owns a
separate Postgres `billing_svc` schema, keeps the HTTP layer thin, and places
plans behavior in a plain-Python domain layer.

## Development

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8097
uv run pytest
uv run ruff check app scripts tests
```

The deterministic target seed is generated from
`services/legacy-billing/db/seed.sql`:

```bash
python scripts/generate_seed.py
```

The generated-seed test prevents the target fixture from drifting from the
legacy before-state. `POST /internal/reset` applies the migration, truncates
the `billing_svc` schema, and reseeds it so the parity harness can isolate
every scenario.

The reset endpoint is disabled by default and always requires the service token. Disposable local/CI Compose stacks
enable it with `BILLING_SVC_ALLOW_INTERNAL_RESET=true`; published deployments
should leave the setting disabled.

## Authentication

Tenant routes (`/api/tenants/{tenant_id}/...`) require
`Authorization: Bearer <token>` and the service fails closed when nothing is
configured:

- an HS256 JWT signed with `BILLING_SVC_JWT_SECRET`, carrying `sub`, `exp` and a
  `tenant_id` claim that must equal the path's `tenant_id` (otherwise `403`);
- or the trusted-caller token `BILLING_SVC_SERVICE_TOKEN`, which may act on any
  tenant (used by the parity harness).

Missing or invalid credentials return `401`. `POST /internal/reset` requires
both `BILLING_SVC_ALLOW_INTERNAL_RESET=true` and the service token. The plan
catalog (`GET /api/plans`) is not tenant data and stays public.

`make procs-up` / `make procs-parity` pass a per-namespace
`BILLING_SVC_SERVICE_TOKEN` (override with `PROCS_SERVICE_TOKEN=...`). To use
the billing screens through the Vite proxy, start the dev server with
`BILLING_SERVICE_TOKEN=<the same token>`; the proxy adds the header server-side
so the token never reaches the browser bundle.

For the extracted target, a plan change with an already-scheduled later
subscription preserves that later row. The response's `latest_*` fields always
identify the subscription created by the request, rather than relying on row
ordering.

The legacy procedure attempts a second insert for an identical plan change and
therefore relies on the database uniqueness error. The extracted target returns
HTTP 409 with an explicit conflict detail instead of leaking a 500; this is
target-side error handling, not an additional parity rule.

When using the workshop client with the default disposable stack, the Vite
development proxy forwards `/billing-api/*` to the service on port `12109`.
The billing screens are part of this local parity fixture only. Vite dev
enables their routes by default; a preview requires building with
`VITE_ENABLE_BILLING_FIXTURE=true` and then running `npm run start`. The
`/billing-api` proxy is used by the dev server and by that explicitly flagged
preview. Builds without the flag leave the routes unregistered. No deployed
app or shared-infrastructure deployment is provided for this fixture.
